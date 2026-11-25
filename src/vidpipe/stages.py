"""The stage graph.

Stages run in :data:`STAGES` order (narration precedes video so durations are known; music needs
the fit plan's total length). Each stage reads the artifacts of earlier stages from ``build/`` and
writes its own, returning their paths relative to ``build/``.

Every generated artifact goes through :meth:`StageContext.produce`, which is where a stage declares
what the artifact depends on (see ``vidpipe.artifacts``). A stage that finds all its artifacts
up to date generates nothing and reports itself skipped.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel

from vidpipe.artifacts import ArtifactStore, Inputs, Made, Produced, digest
from vidpipe.assembly import (
    Assembler,
    AssemblyJob,
    ClipPlay,
    LanguageRender,
    MixSettings,
    ShotSegment,
    SubtitleTrack,
    extract_last_frame,
)
from vidpipe.bible import (
    Bible,
    BibleError,
    KeyframeBrief,
    keyframe_brief,
    load_bible,
    reference_problems,
)
from vidpipe.config import STAGE_KINDS
from vidpipe.contracts import (
    MOTION_DESCRIPTIONS,
    GenerationError,
    GenerationRecord,
    ImageToVideoProvider,
    ImageToVideoRequest,
    KeyframeRequest,
    KeyframerProvider,
    MotionType,
    MusicProvider,
    MusicRequest,
    Provider,
    TextProvider,
    TranslationProvider,
    TTSProvider,
    TTSRequest,
    UnsupportedRequest,
)
from vidpipe.fit import FIT_VERSION, NarrationInput, limits_for, plan_fit
from vidpipe.fit_inputs import collect_shots, translation_files
from vidpipe.models import (
    Brief,
    ClipPlan,
    FitPlan,
    MediaIndex,
    MediaItem,
    Narration,
    NarrationClip,
    Script,
    ScriptDraft,
    ScriptLine,
    Shot,
    Storyboard,
    StoryboardDraft,
)
from vidpipe.project import Project
from vidpipe.subtitles import Cue, font_files, font_problems, resolve_fonts_dir, write_srt
from vidpipe.text import TextProviderError, ask, failure_count, fallback_note
from vidpipe.translate import TextTranslator, TranslationError, review_path, translate_script

P = TypeVar("P", bound=Provider[Any])


class StageError(Exception):
    pass


@dataclass
class StageContext:
    project: Project
    providers: dict[str, Provider[Any]]
    assembler: Assembler
    #: Name of the stage being run (set by the runner); selects the provider recorded and hashed.
    stage: str = ""
    #: Artifacts generated / reused so far by the stage being run.
    generated: int = 0
    reused: int = 0
    #: Called after each artifact the stage finishes (generated or reused): the runner publishes
    #: progress here, between artifacts.
    on_artifact: Callable[[], None] | None = None
    store: ArtifactStore = field(init=False)

    def __post_init__(self) -> None:
        self.store = ArtifactStore(self.project)

    def begin(self, stage: str) -> None:
        self.stage, self.generated, self.reused = stage, 0, 0

    def produce(
        self,
        key: str,
        *,
        inputs: Inputs,
        make: Callable[[], Made],
        parameters: Mapping[str, Any] | None = None,
        seed: int | None = None,
    ) -> Produced:
        """Return artifact ``key``, calling ``make`` only if its declared inputs changed."""
        selection = self.project.config.providers.get(self.stage)
        produced = self.store.produce(
            key,
            stage=self.stage,
            provider=self.providers.get(self.stage),
            options=selection.options if selection else None,
            inputs=inputs,
            make=make,
            parameters=parameters,
            seed=seed,
        )
        if produced.reused:
            self.reused += 1
        else:
            self.generated += 1
        if self.on_artifact is not None:
            self.on_artifact()
        return produced

    def shot_seed(self, shot_id: int) -> int:
        return self.store.shot_seed(shot_id)

    def provider(self, stage: str, expected: type[P]) -> P:
        provider = self.providers.get(stage)
        if provider is None:
            raise StageError(f"no provider configured for stage {stage!r}")
        if not isinstance(provider, expected):
            raise StageError(f"stage {stage!r} has a {provider.kind.value} provider; wrong kind")
        return provider

    @property
    def languages(self) -> list[str]:
        return self.project.config.languages

    def script(self, language: str) -> Script:
        if language == self.project.config.primary_language:
            return self.project.read_model("script.json", Script)
        return self.project.read_model(f"translation/{language}.json", Script)


class Stage(ABC):
    name: ClassVar[str]

    def problems(self, ctx: StageContext) -> list[str]:  # noqa: ARG002
        """Plan-time check (capabilities etc.) made before anything is generated."""
        return []

    def artifact_count(self, ctx: StageContext) -> int:  # noqa: ARG002
        """How many artifacts :meth:`run` will produce, worked out from what is on disk.

        Raises (a missing earlier artifact, say) when that cannot be known yet.
        """
        return 1

    @abstractmethod
    def run(self, ctx: StageContext) -> list[str]:
        """Generate this stage's artifacts; return their paths relative to ``build/``."""


def _generate[R](what: str, call: Callable[[], R]) -> R:
    """Call a media provider; a failure (after its own retries) fails the stage, naming ``what``.
    Artifacts already made are kept, so the next run resumes after them."""
    try:
        return call()
    except (GenerationError, UnsupportedRequest) as exc:
        raise StageError(f"{what}: {exc}") from exc


def _recorded(path: Path, record: GenerationRecord, *, seed: int, **data: Any) -> Made:
    """The artifact a provider made, with what it did (``record``) kept in the ledger: the seed
    that was used, retries and step-downs (``fallback``), GPU time and the provider's details."""
    return Made(
        [path],
        data={**record.details, **data, "seed": seed if record.seed is None else record.seed},
        gpu_seconds=record.gpu_seconds,
        fallback=record.fallback,
    )


def _rels(ctx: StageContext, produced: Produced) -> list[str]:
    return [p.relative_to(ctx.project.build).as_posix() for p in produced.paths]


def _item(ctx: StageContext, shot_id: int | None, path: Path) -> MediaItem:
    return MediaItem(shot_id=shot_id, path=path.relative_to(ctx.project.build).as_posix())


def _write_index(ctx: StageContext, name: str, items: list[MediaItem]) -> list[str]:
    return [ctx.project.write_model(name, MediaIndex(items=items)), *(i.path for i in items)]


def _ask[M: BaseModel](
    provider: TextProvider, prompt: str, model: type[M], check: Callable[[M], None]
) -> M:
    """Ask a text provider for a validated ``model``; a provider failure fails the stage."""
    try:
        return ask(provider, prompt, model, check)
    except TextProviderError as exc:
        raise StageError(str(exc)) from exc


def _check_script(draft: ScriptDraft) -> None:
    if blank := [i for i, line in enumerate(draft.lines, start=1) if not line.strip()]:
        raise ValueError(f"script lines are blank: {blank}")


class BriefStage(Stage):
    name = "brief"

    def run(self, ctx: StageContext) -> list[str]:
        made = ctx.produce(
            "brief",
            inputs=Inputs(files=[ctx.project.root / "brief.md"]),
            make=lambda: Made([ctx.project.write_model("brief.json", ctx.project.load_brief())]),
        )
        return _rels(ctx, made)


class ScriptStage(Stage):
    name = "script"

    def run(self, ctx: StageContext) -> list[str]:
        brief = ctx.project.read_model("brief.json", Brief)
        provider = ctx.provider("script", TextProvider)
        language = ctx.project.config.primary_language
        prompt = (
            f"Write the narration script for a short video titled {brief.title!r}, in the "
            f"language with code {language!r}. It will be read aloud over a sequence of shots, "
            f"one line per shot.\n\n"
            f"Rules:\n"
            f"- Put one sentence per entry of `lines`, in the order they are spoken.\n"
            f"- Keep each line short enough to speak in 3 to 5 seconds (at most 14 words).\n"
            f"- Use 6 to 12 lines, so the whole video stays under 60 seconds.\n"
            f"- Plain narration only: no stage directions, headings, numbering or markup.\n\n"
            f"Brief:\n{brief.body}"
        )

        def make() -> Made:
            since = failure_count(provider)
            draft = _ask(provider, prompt, ScriptDraft, _check_script)
            script = Script(
                language=ctx.project.config.primary_language,
                title=brief.title,
                lines=[ScriptLine(id=i, text=t) for i, t in enumerate(draft.lines, start=1)],
            )
            return Made(
                [ctx.project.write_model("script.json", script)],
                fallback=fallback_note(provider, since),
            )

        made = ctx.produce(
            "script",
            inputs=Inputs(files=["brief.json"], values={"prompt": prompt}),
            parameters={"language": ctx.project.config.primary_language},
            make=make,
        )
        return _rels(ctx, made)


class TranslationStage(Stage):
    name = "translation"

    def _targets(self, ctx: StageContext) -> list[str]:
        return ctx.languages[1:]

    def problems(self, ctx: StageContext) -> list[str]:
        if not self._targets(ctx):
            return []
        caps = ctx.provider("translation", TranslationProvider).capabilities
        found: list[str] = []
        if ctx.project.config.primary_language not in caps.source_languages:
            found.append(
                "translation provider cannot translate from "
                f"{ctx.project.config.primary_language!r}"
            )
        found += [
            f"translation provider cannot translate into {lang!r}"
            for lang in self._targets(ctx)
            if lang not in caps.target_languages
        ]
        return found

    def artifact_count(self, ctx: StageContext) -> int:
        targets = self._targets(ctx)
        if not targets:
            return 0
        reviewed = isinstance(ctx.provider("translation", TranslationProvider), TextTranslator)
        return len(targets) * (2 if reviewed else 1)

    def run(self, ctx: StageContext) -> list[str]:
        script = ctx.script(ctx.project.config.primary_language)
        provider = ctx.provider("translation", TranslationProvider)
        outputs: list[str] = []
        for lang in self._targets(ctx):

            def make(lang: str = lang) -> Made:
                try:
                    done = translate_script(provider, script, lang)
                except TranslationError as exc:
                    raise StageError(str(exc)) from exc
                path = ctx.project.write_model(f"translation/{lang}.json", done.script)
                return Made([path], data=done.data, fallback=done.fallback)

            made = ctx.produce(
                f"translation/{lang}",
                inputs=Inputs(files=["script.json"]),
                parameters={"source_language": script.language, "target_language": lang},
                make=make,
            )
            outputs += _rels(ctx, made)
            if isinstance(provider, TextTranslator):
                outputs += self._review(ctx, provider, script, lang, made.data)
        return outputs

    def _review(
        self,
        ctx: StageContext,
        provider: TextTranslator,
        script: Script,
        lang: str,
        translator: dict[str, Any],
    ) -> list[str]:
        """Back-translation check of ``lang``'s translation, re-run when the translated text (a
        hand edit, say) or the translator changes. Flags land in ``translation/<lang>.review.json``.
        """

        def make() -> Made:
            try:
                reviewed = provider.review(
                    script,
                    ctx.script(lang),
                    translator=translator.get("translator", provider.name),
                    translator_fingerprint=translator.get("translator_fingerprint"),
                )
            except TranslationError as exc:
                raise StageError(str(exc)) from exc
            path = ctx.project.write_model(review_path(lang), reviewed.review)
            return Made(
                [path],
                data={
                    "drifted": [line.id for line in reviewed.review.drifted],
                    "same_model": reviewed.review.same_model,
                    "checker": reviewed.review.checker,
                    "translator": reviewed.review.translator,
                },
                fallback=reviewed.fallback,
            )

        made = ctx.produce(
            f"translation/{lang}/review",
            inputs=Inputs(
                files=["script.json", f"translation/{lang}.json"], values={"translator": translator}
            ),
            parameters={"source_language": script.language, "target_language": lang},
            make=make,
        )
        return _rels(ctx, made)


class StoryboardStage(Stage):
    name = "storyboard"

    def problems(self, ctx: StageContext) -> list[str]:
        _bible(ctx)  # a broken bible fails the plan before anything is generated
        return []

    def run(self, ctx: StageContext) -> list[str]:
        script = ctx.script(ctx.project.config.primary_language)
        provider = ctx.provider("storyboard", TextProvider)
        lines = "\n".join(f"{line.id}. {line.text}" for line in script.lines)
        motions = "\n".join(f"  - {m.value}: {MOTION_DESCRIPTIONS[m]}" for m in MotionType)
        prompt = (
            "Storyboard this narration script for a short stylized video. Give each script line "
            "one shot, in script order.\n\n"
            "For each shot:\n"
            "- `line_id`: the number of the script line the shot illustrates.\n"
            "- `visual`: one concrete sentence describing a single still image: subject, setting, "
            "light and mood. No complex action, no text or lettering in the image.\n"
            "- `motion_type`: exactly one of the following (the video model can do nothing else):\n"
            f"{motions}\n\n"
            f"Script:\n{lines}"
        )
        valid_ids = {line.id for line in script.lines}
        bible = _bible(ctx)
        if casting := bible.casting_instructions():
            prompt += f"\n\nThe cast. For each shot also give:\n{casting}"

        def check(draft: StoryboardDraft) -> None:
            used = {s.line_id for s in draft.shots}
            if unknown := sorted(used - valid_ids):
                raise ValueError(f"shots refer to script lines that do not exist: {unknown}")
            if missing := sorted(valid_ids - used):
                raise ValueError(f"script lines with no shot: {missing}")
            if casting:
                for shot in draft.shots:
                    try:
                        bible.cast(shot.character, shot.location)
                    except BibleError as exc:
                        raise ValueError(str(exc)) from exc

        def make() -> Made:
            since = failure_count(provider)
            draft = _ask(provider, prompt, StoryboardDraft, check)
            storyboard = Storyboard(
                shots=[
                    Shot(
                        id=i,
                        line_id=s.line_id,
                        visual=s.visual,
                        motion_type=s.motion_type,
                        character=s.character if casting else None,
                        location=s.location if casting else None,
                    )
                    for i, s in enumerate(draft.shots, start=1)
                ]
            )
            return Made(
                [ctx.project.write_model("storyboard.json", storyboard)],
                fallback=fallback_note(provider, since),
            )

        made = ctx.produce(
            "storyboard",
            inputs=Inputs(files=["script.json"], values={"prompt": prompt}),
            make=make,
        )
        return _rels(ctx, made)


class NarrationStage(Stage):
    name = "narration"

    def problems(self, ctx: StageContext) -> list[str]:
        supported = ctx.provider("narration", TTSProvider).capabilities.languages
        return [
            f"narration provider does not support language {lang!r}"
            for lang in ctx.languages
            if lang not in supported
        ]

    def artifact_count(self, ctx: StageContext) -> int:
        shots = ctx.project.read_model("storyboard.json", Storyboard).shots
        return len(ctx.languages) * len(shots)

    def run(self, ctx: StageContext) -> list[str]:
        storyboard = ctx.project.read_model("storyboard.json", Storyboard)
        provider = ctx.provider("narration", TTSProvider)
        clips: list[NarrationClip] = []
        for lang in ctx.languages:
            lines = {line.id: line.text for line in ctx.script(lang).lines}
            for shot in storyboard.shots:
                text = lines[shot.line_id]
                key = f"narration/{lang}/shot_{shot.id:02d}"

                def make(text: str = text, lang: str = lang, key: str = key) -> Made:
                    out = ctx.project.artifact_path(f"{key}.wav")
                    result = provider.synthesize(
                        TTSRequest(text=text, language=lang, output_path=out)
                    )
                    return Made([result.path], data={"duration_s": result.duration_s})

                made = ctx.produce(
                    key,
                    inputs=Inputs(values={"text": text}),
                    parameters={"language": lang, "voice": None},
                    make=make,
                )
                clips.append(
                    NarrationClip(
                        shot_id=shot.id,
                        language=lang,
                        path=_rels(ctx, made)[0],
                        duration_s=made.data["duration_s"],
                    )
                )
        return [
            ctx.project.write_model("narration.json", Narration(clips=clips)),
            *(c.path for c in clips),
        ]


class FitPlanningStage(Stage):
    """Plans each shot's clips from the real narration durations (see :mod:`vidpipe.fit`)."""

    name = "fit-planning"

    def run(self, ctx: StageContext) -> list[str]:
        project = ctx.project
        narration = project.read_model("narration.json", Narration)
        caps = ctx.provider("video", ImageToVideoProvider).capabilities
        config = project.config
        measured = {(c.language, c.shot_id): c.duration_s for c in narration.clips}
        shots = collect_shots(
            project,
            project.read_model("storyboard.json", Storyboard),
            lambda lang, shot_id, text: NarrationInput(text, measured[lang, shot_id]),
        )

        def make() -> Made:
            plan = plan_fit(
                shots,
                languages=config.languages,
                primary_language=config.primary_language,
                visuals=config.visuals,
                limits=limits_for(caps),
            )
            if plan.problems:
                raise StageError("; ".join(plan.problems))
            return Made([project.write_model("fit_plan.json", plan)])

        made = ctx.produce(
            "fit_plan",
            inputs=Inputs(
                files=["narration.json", "storyboard.json", *translation_files(project)],
                values={
                    "visuals": config.visuals,
                    "languages": config.languages,
                    "video_capabilities": caps,
                    "fit_version": FIT_VERSION,
                },
            ),
            make=make,
        )
        return _rels(ctx, made)


def _bible(ctx: StageContext) -> Bible:
    try:
        return load_bible(ctx.project.root)
    except BibleError as exc:
        raise StageError(str(exc)) from exc


class KeyframesStage(Stage):
    """One still per shot, drawn with the bible's reference pictures (see :mod:`vidpipe.bible`)."""

    name = "keyframes"

    def problems(self, ctx: StageContext) -> list[str]:
        config = ctx.project.config
        capabilities = ctx.provider("keyframes", KeyframerProvider).capabilities
        return [
            *capabilities.size_problems(config.width, config.height),
            *reference_problems(_bible(ctx), ctx.project.root),
        ]

    def _briefs(self, ctx: StageContext, max_references: int) -> list[tuple[Shot, KeyframeBrief]]:
        """What to draw for every shot. Casting mistakes fail here, before any drawing."""
        bible = _bible(ctx)
        briefs: list[tuple[Shot, KeyframeBrief]] = []
        for shot in ctx.project.read_model("storyboard.json", Storyboard).shots:
            try:
                brief = keyframe_brief(
                    bible,
                    ctx.project.root,
                    shot.visual,
                    character=shot.character,
                    location=shot.location,
                    max_references=max_references,
                )
            except BibleError as exc:
                raise StageError(f"shot {shot.id}: {exc}") from exc
            briefs.append((shot, brief))
        return briefs

    def artifact_count(self, ctx: StageContext) -> int:
        return len(ctx.project.read_model("storyboard.json", Storyboard).shots)

    def run(self, ctx: StageContext) -> list[str]:
        provider = ctx.provider("keyframes", KeyframerProvider)
        config = ctx.project.config
        items: list[MediaItem] = []
        for shot, brief in self._briefs(ctx, provider.capabilities.max_reference_images):
            key = f"keyframes/shot_{shot.id:02d}"
            seed = ctx.shot_seed(shot.id)
            references = [
                {"id": r.id, "path": r.name, "sha256": ctx.store.hash_path(r.path)}
                for r in brief.references
            ]

            def make(
                shot: Shot = shot,
                key: str = key,
                seed: int = seed,
                brief: KeyframeBrief = brief,
                references: list[dict[str, str]] = references,
            ) -> Made:
                request = KeyframeRequest(
                    prompt=brief.prompt,
                    width=config.width,
                    height=config.height,
                    seed=seed,
                    reference_images=[r.path for r in brief.references],
                    output_path=ctx.project.artifact_path(f"{key}.png"),
                )
                result = _generate(
                    f"keyframe for shot {shot.id}", lambda: provider.generate(request)
                )
                return _recorded(
                    result.path,
                    result.record,
                    seed=seed,
                    prompt=brief.prompt,
                    references=references,
                )

            values: dict[str, Any] = {"prompt": brief.prompt}
            if references:
                values["references"] = [[r["id"], r["sha256"]] for r in references]
            made = ctx.produce(
                key,
                inputs=Inputs(values=values),
                parameters={"width": config.width, "height": config.height},
                seed=seed,
                make=make,
            )
            items.append(_item(ctx, shot.id, made.paths[0]))
        return _write_index(ctx, "keyframes.json", items)


class VideoStage(Stage):
    """Animate each visual set from its keyframe, then from each preceding clip's last frame."""

    name = "video"

    def artifact_count(self, ctx: StageContext) -> int:
        plan = {s.shot_id: s for s in ctx.project.read_model("fit_plan.json", FitPlan).shots}
        return sum(
            len(visual_set.clips)
            for shot in ctx.project.read_model("storyboard.json", Storyboard).shots
            for visual_set in plan[shot.id].visual_sets.values()
        )

    def run(self, ctx: StageContext) -> list[str]:
        provider = ctx.provider("video", ImageToVideoProvider)
        plan = {s.shot_id: s for s in ctx.project.read_model("fit_plan.json", FitPlan).shots}
        keyframes = ctx.project.read_model("keyframes.json", MediaIndex)
        items: list[MediaItem] = []
        for shot in ctx.project.read_model("storyboard.json", Storyboard).shots:
            keyframe = ctx.project.build / keyframes.for_shot(shot.id)
            for visual_set in plan[shot.id].visual_sets.values():
                # ``shared`` keeps the plain key; per-language sets live under their language.
                unit = f"shot_{shot.id:02d}"
                base = (
                    f"video/{unit}"
                    if visual_set.id == "shared"
                    else f"video/{visual_set.id}/{unit}"
                )
                paths: dict[int, Path] = {}
                for clip in visual_set.clips:
                    key = f"{base}_clip_{clip.index:02d}" if clip.index else base
                    source = keyframe if clip.continues is None else paths[clip.continues]
                    path = self._animate(ctx, provider, shot, key, clip, source)
                    paths[clip.index] = path
                    items.append(
                        MediaItem(
                            shot_id=shot.id,
                            visual_set=visual_set.id,
                            clip=clip.index,
                            path=path.relative_to(ctx.project.build).as_posix(),
                        )
                    )
        return _write_index(ctx, "video.json", items)

    @staticmethod
    def _animate(
        ctx: StageContext,
        provider: ImageToVideoProvider,
        shot: Shot,
        key: str,
        clip: ClipPlan,
        source: Path,
    ) -> Path:
        prompt = shot.visual
        seed = ctx.shot_seed(shot.id)
        label = f"video for shot {shot.id}"
        if clip.continues is not None:
            prompt = (
                f"{prompt}\nContinue the same shot from the supplied frame. "
                "Maintain the subject, setting, lighting, and camera motion. "
                "Keep the scene moving continuously without a cut or reset.\n"
                f"Narration for this segment: {clip.text}"
            )
            seed = int(digest([seed, clip.index])[:8], 16) % 2**31
            label += f" continuation {clip.index}"

        def make() -> Made:
            with ExitStack() as stack:
                image = source
                if clip.continues is not None:
                    temp = Path(stack.enter_context(TemporaryDirectory()))
                    image = temp / f"{source.stem}_last.png"
                    extract_last_frame(source, image)
                request = ImageToVideoRequest(
                    image=image,
                    prompt=prompt,
                    motion_type=shot.motion_type,
                    duration_s=clip.seconds,
                    seed=seed,
                    output_path=ctx.project.artifact_path(f"{key}.mp4"),
                )
                result = provider.animate(request)
            return _recorded(
                result.path, result.record, seed=request.seed, duration_s=result.duration_s
            )

        made = ctx.produce(
            key,
            inputs=Inputs(files=[source], values={"prompt": prompt}),
            parameters={"motion_type": shot.motion_type.value, "duration_s": clip.seconds},
            seed=seed,
            make=lambda: _generate(label, make),
        )
        return made.paths[0]


class MusicStage(Stage):
    name = "music"

    def run(self, ctx: StageContext) -> list[str]:
        provider = ctx.provider("music", MusicProvider)
        brief = ctx.project.read_model("brief.json", Brief)
        total = float(ctx.project.read_model("fit_plan.json", FitPlan).music_seconds)
        if problem := provider.capabilities.duration_problem(total):
            raise StageError(problem)
        prompt = f"Instrumental score for: {brief.title}"
        seed = 0

        def make() -> Made:
            out = ctx.project.artifact_path("music/music.wav")
            request = MusicRequest(prompt=prompt, duration_s=total, seed=seed, output_path=out)
            result = _generate("music", lambda: provider.compose(request))
            if not result.duration_s >= total:
                raise StageError(
                    f"music: provider returned {result.duration_s:g} s for a {total:g} s score"
                )
            return _recorded(
                result.path, result.record, seed=request.seed, duration_s=result.duration_s
            )

        made = ctx.produce(
            "music",
            inputs=Inputs(values={"prompt": prompt}),
            parameters={"duration_s": total},
            seed=seed,
            make=make,
        )
        return _write_index(ctx, "music.json", [_item(ctx, None, made.paths[0])])


class AssemblyStage(Stage):
    """Mixes, subtitles and renders one video per language (``out/<output_name>_<lang>.mp4``), plus
    each language's sidecar ``out/<output_name>_<lang>.srt``."""

    name = "assembly"

    def problems(self, ctx: StageContext) -> list[str]:
        config = ctx.project.config
        return [
            *ctx.assembler.problems(),
            *font_problems(config.subtitles, ctx.languages, ctx.project.root),
        ]

    def artifact_count(self, ctx: StageContext) -> int:
        return len(ctx.languages)

    def run(self, ctx: StageContext) -> list[str]:
        project = ctx.project
        config = project.config
        plan = project.read_model("fit_plan.json", FitPlan)
        narration = project.read_model("narration.json", Narration)
        video = project.read_model("video.json", MediaIndex)
        music_item = project.read_model("music.json", MediaIndex).items[0]
        shots = {s.shot_id: s for s in plan.shots}
        storyboard = project.read_model("storyboard.json", Storyboard)
        outputs: list[str] = []
        for lang in ctx.languages:
            if (seconds := plan.render_seconds[lang]) > plan.limits.max_render_s:
                raise StageError(
                    f"the {lang} render would last {seconds:.1f} s; the limit is "
                    f"{plan.limits.max_render_s:g} s (shorten the narration and plan again)"
                )
            segments: list[ShotSegment] = []
            cues: list[Cue] = []
            offset = 0.0
            for shot in storyboard.shots:
                fit = shots[shot.id].languages[lang]
                segments.append(
                    ShotSegment(
                        shot_id=shot.id,
                        narration=project.build
                        / next(
                            c.path
                            for c in narration.clips
                            if c.shot_id == shot.id and c.language == lang
                        ),
                        seconds=fit.seconds,
                        clips=[
                            ClipPlay(
                                video=project.build
                                / video.for_clip(shot.id, fit.visual_set, use.clip),
                                speed=use.speed,
                                source_s=use.source_s,
                                seconds=use.seconds,
                            )
                            for use in fit.clips
                            if use.source_s > 0
                        ],
                    )
                )
                cues += [
                    Cue(text=s.text, start_s=offset + s.start_s, end_s=offset + s.end_s)
                    for s in fit.segments
                ]
                offset += fit.seconds
            stem = f"{config.output_name}_{lang}"
            outputs += self._render(
                ctx, lang, segments, cues, project.build / music_item.path, stem
            )
        return outputs

    def _render(
        self,
        ctx: StageContext,
        lang: str,
        segments: list[ShotSegment],
        cues: list[Cue],
        music: Path,
        stem: str,
    ) -> list[str]:
        project = ctx.project
        config = project.config
        subtitles = config.subtitles
        font = subtitles.fonts.get(lang)
        fonts_dir = resolve_fonts_dir(project.root, subtitles)
        fonts = font_files(fonts_dir, font) if font and fonts_dir.is_dir() else []
        track = SubtitleTrack(
            srt=project.out / f"{stem}.srt",
            burn_in=subtitles.burn_in,
            fonts_dir=fonts_dir if font else None,
            font=font,
            font_size=subtitles.font_size,
        )
        render = LanguageRender(
            language=lang,
            output=project.out / f"{stem}.mp4",
            segments=segments,
            music=music,
            subtitles=track,
        )

        def make() -> Made:
            write_srt(track.srt, cues)
            job = AssemblyJob(
                renders=[render],
                width=config.width,
                height=config.height,
                fps=config.fps,
                mix=MixSettings(
                    music_level=config.mix.music_level, duck_ratio=config.mix.duck_ratio
                ),
            )
            return Made([*ctx.assembler.assemble(job), track.srt])

        made = ctx.produce(
            f"assembly/{lang}",
            inputs=Inputs(
                files=[
                    *(clip.video for s in segments for clip in s.clips),
                    *(s.narration for s in segments),
                    music,
                ],
                values={
                    # Fonts may live outside the project (the bundled ones do): hash them here.
                    "fonts": {
                        f.name: ctx.store.hash_path(f) for f in (fonts if subtitles.burn_in else [])
                    },
                    "clips": [
                        [(c.speed, c.source_s, c.seconds) for c in s.clips] for s in segments
                    ],
                    "seconds": [s.seconds for s in segments],
                    "cues": cues,
                },
            ),
            parameters={
                "language": lang,
                "width": config.width,
                "height": config.height,
                "fps": config.fps,
                "burn_in": subtitles.burn_in,
                "font": font if subtitles.burn_in else None,
                "font_size": subtitles.font_size,
                "music_level": config.mix.music_level,
                "duck_ratio": config.mix.duck_ratio,
            },
            make=make,
        )
        return [p.relative_to(project.root).as_posix() for p in made.paths]


STAGES: list[Stage] = [
    BriefStage(),
    ScriptStage(),
    TranslationStage(),
    StoryboardStage(),
    NarrationStage(),
    FitPlanningStage(),
    KeyframesStage(),
    VideoStage(),
    MusicStage(),
    AssemblyStage(),
]

#: Stages that talk to a provider, and which provider config key they use.
PROVIDER_STAGES = tuple(STAGE_KINDS)
STAGE_NAMES = [s.name for s in STAGES]
