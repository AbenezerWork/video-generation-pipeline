"""The stage graph.

Stages run in :data:`STAGES` order (narration precedes video so durations are known; music needs
the fit plan's total length). Each stage reads the artifacts of earlier stages from ``build/`` and
writes its own, returning their paths relative to ``build/``.

Every generated artifact goes through :meth:`StageContext.produce`, which is where a stage declares
what the artifact depends on (see ``vidpipe.artifacts``). A stage that finds all its artifacts
up to date generates nothing and reports itself skipped.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, TypeVar

from vidpipe.artifacts import ArtifactStore, Inputs, Made, Produced
from vidpipe.assembly import Assembler, AssemblyJob, LanguageRender, ShotSegment
from vidpipe.config import STAGE_KINDS
from vidpipe.contracts import (
    ImageToVideoProvider,
    ImageToVideoRequest,
    KeyframeRequest,
    KeyframerProvider,
    MusicProvider,
    MusicRequest,
    Provider,
    TextProvider,
    TextRequest,
    TranslationProvider,
    TranslationRequest,
    TTSProvider,
    TTSRequest,
)
from vidpipe.fit import FIT_VERSION, NarrationInput, limits_for, plan_fit
from vidpipe.fit_inputs import collect_shots, translation_files
from vidpipe.models import (
    Brief,
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
        return produced

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

    @abstractmethod
    def run(self, ctx: StageContext) -> list[str]:
        """Generate this stage's artifacts; return their paths relative to ``build/``."""


def _rels(ctx: StageContext, produced: Produced) -> list[str]:
    return [p.relative_to(ctx.project.build).as_posix() for p in produced.paths]


def _item(ctx: StageContext, shot_id: int | None, path: Path) -> MediaItem:
    return MediaItem(shot_id=shot_id, path=path.relative_to(ctx.project.build).as_posix())


def _write_index(ctx: StageContext, name: str, items: list[MediaItem]) -> list[str]:
    return [ctx.project.write_model(name, MediaIndex(items=items)), *(i.path for i in items)]


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
        prompt = (
            f"Write a short narration script in language {ctx.project.config.primary_language!r}, "
            f"one sentence per line, for a video titled {brief.title!r}.\n\n{brief.body}"
        )

        def make() -> Made:
            response = provider.complete(
                TextRequest(prompt=prompt, json_schema=ScriptDraft.model_json_schema())
            )
            draft = ScriptDraft.model_validate(response.data)
            script = Script(
                language=ctx.project.config.primary_language,
                title=brief.title,
                lines=[ScriptLine(id=i, text=t) for i, t in enumerate(draft.lines, start=1)],
            )
            return Made([ctx.project.write_model("script.json", script)])

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

    def run(self, ctx: StageContext) -> list[str]:
        script = ctx.script(ctx.project.config.primary_language)
        provider = ctx.provider("translation", TranslationProvider)
        outputs: list[str] = []
        for lang in self._targets(ctx):

            def make(lang: str = lang) -> Made:
                response = provider.translate(
                    TranslationRequest(
                        texts=[line.text for line in script.lines],
                        source_language=script.language,
                        target_language=lang,
                    )
                )
                if len(response.texts) != len(script.lines):
                    raise StageError(
                        f"translation into {lang!r} returned the wrong number of lines"
                    )
                translated = Script(
                    language=lang,
                    title=script.title,
                    lines=[
                        ScriptLine(id=line.id, text=text)
                        for line, text in zip(script.lines, response.texts, strict=True)
                    ],
                )
                return Made([ctx.project.write_model(f"translation/{lang}.json", translated)])

            made = ctx.produce(
                f"translation/{lang}",
                inputs=Inputs(files=["script.json"]),
                parameters={"source_language": script.language, "target_language": lang},
                make=make,
            )
            outputs += _rels(ctx, made)
        return outputs


class StoryboardStage(Stage):
    name = "storyboard"

    def run(self, ctx: StageContext) -> list[str]:
        script = ctx.script(ctx.project.config.primary_language)
        provider = ctx.provider("storyboard", TextProvider)
        lines = "\n".join(f"{line.id}. {line.text}" for line in script.lines)
        prompt = (
            "Storyboard this script as shots, each with a visual description and a motion type "
            f"(push_in, pan or ambient).\n\n{lines}"
        )

        def make() -> Made:
            response = provider.complete(
                TextRequest(prompt=prompt, json_schema=StoryboardDraft.model_json_schema())
            )
            draft = StoryboardDraft.model_validate(response.data)
            valid_ids = {line.id for line in script.lines}
            bad = [s.line_id for s in draft.shots if s.line_id not in valid_ids]
            if bad:
                raise StageError(f"storyboard refers to unknown script lines: {bad}")
            storyboard = Storyboard(
                shots=[
                    Shot(id=i, line_id=s.line_id, visual=s.visual, motion_type=s.motion_type)
                    for i, s in enumerate(draft.shots, start=1)
                ]
            )
            return Made([ctx.project.write_model("storyboard.json", storyboard)])

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
        # Continuation clips are planned (see `vidpipe plan`) but generating them is ticket 12.
        # Stop here, before any GPU work, rather than render frozen frames.
        planned = project.read_model("fit_plan.json", FitPlan)
        needing = [s.shot_id for s in planned.shots if s.continuation_clips]
        if needing:
            raise StageError(
                f"shots {needing} need continuation clips, which cannot be generated yet; "
                "`vidpipe plan` shows them. Shorten those narration lines (a shot plays at most "
                "one clip, slowed by up to 1.3x) and run again"
            )
        return _rels(ctx, made)


class KeyframesStage(Stage):
    name = "keyframes"

    def run(self, ctx: StageContext) -> list[str]:
        provider = ctx.provider("keyframes", KeyframerProvider)
        config = ctx.project.config
        items: list[MediaItem] = []
        for shot in ctx.project.read_model("storyboard.json", Storyboard).shots:
            key = f"keyframes/shot_{shot.id:02d}"

            def make(shot: Shot = shot, key: str = key) -> Made:
                result = provider.generate(
                    KeyframeRequest(
                        prompt=shot.visual,
                        width=config.width,
                        height=config.height,
                        seed=shot.id,
                        output_path=ctx.project.artifact_path(f"{key}.png"),
                    )
                )
                return Made([result.path])

            made = ctx.produce(
                key,
                inputs=Inputs(values={"prompt": shot.visual}),
                parameters={"width": config.width, "height": config.height},
                seed=shot.id,
                make=make,
            )
            items.append(_item(ctx, shot.id, made.paths[0]))
        return _write_index(ctx, "keyframes.json", items)


class VideoStage(Stage):
    """Generates each shot's first clip, from its keyframe, once per visual set in the fit plan.

    Continuation clips are planned (``fit_plan.json``) but not generated yet.
    """

    name = "video"

    def run(self, ctx: StageContext) -> list[str]:
        provider = ctx.provider("video", ImageToVideoProvider)
        plan = {s.shot_id: s for s in ctx.project.read_model("fit_plan.json", FitPlan).shots}
        keyframes = ctx.project.read_model("keyframes.json", MediaIndex)
        items: list[MediaItem] = []
        for shot in ctx.project.read_model("storyboard.json", Storyboard).shots:
            image = ctx.project.build / keyframes.for_shot(shot.id)
            for visual_set in plan[shot.id].visual_sets.values():
                # ``shared`` keeps the plain key; per-language sets live under their language.
                unit = f"shot_{shot.id:02d}"
                key = (
                    f"video/{unit}"
                    if visual_set.id == "shared"
                    else f"video/{visual_set.id}/{unit}"
                )
                seconds = visual_set.clips[0].seconds

                def make(
                    shot: Shot = shot, image: Path = image, key: str = key, seconds: float = seconds
                ) -> Made:
                    result = provider.animate(
                        ImageToVideoRequest(
                            image=image,
                            prompt=shot.visual,
                            motion_type=shot.motion_type,
                            duration_s=seconds,
                            seed=shot.id,
                            output_path=ctx.project.artifact_path(f"{key}.mp4"),
                        )
                    )
                    return Made([result.path], data={"duration_s": result.duration_s})

                made = ctx.produce(
                    key,
                    inputs=Inputs(files=[image], values={"prompt": shot.visual}),
                    parameters={"motion_type": shot.motion_type.value, "duration_s": seconds},
                    seed=shot.id,
                    make=make,
                )
                items.append(
                    MediaItem(
                        shot_id=shot.id,
                        visual_set=visual_set.id,
                        path=made.paths[0].relative_to(ctx.project.build).as_posix(),
                    )
                )
        return _write_index(ctx, "video.json", items)


class MusicStage(Stage):
    name = "music"

    def run(self, ctx: StageContext) -> list[str]:
        provider = ctx.provider("music", MusicProvider)
        brief = ctx.project.read_model("brief.json", Brief)
        # Whole seconds: the render is trimmed to each language, and a small narration edit must
        # not regenerate the music.
        total = float(math.ceil(ctx.project.read_model("fit_plan.json", FitPlan).total_seconds))
        prompt = f"Instrumental score for: {brief.title}"

        def make() -> Made:
            out = ctx.project.artifact_path("music/music.wav")
            result = provider.compose(
                MusicRequest(prompt=prompt, duration_s=total, output_path=out)
            )
            return Made([result.path])

        made = ctx.produce(
            "music",
            inputs=Inputs(values={"prompt": prompt}),
            parameters={"duration_s": total},
            seed=0,
            make=make,
        )
        return _write_index(ctx, "music.json", [_item(ctx, None, made.paths[0])])


class AssemblyStage(Stage):
    name = "assembly"

    def problems(self, ctx: StageContext) -> list[str]:
        return ctx.assembler.problems()

    def run(self, ctx: StageContext) -> list[str]:
        project = ctx.project
        plan = {s.shot_id: s for s in project.read_model("fit_plan.json", FitPlan).shots}
        narration = project.read_model("narration.json", Narration)
        video = project.read_model("video.json", MediaIndex)
        music_item = project.read_model("music.json", MediaIndex).items[0]
        renders: list[LanguageRender] = []
        for lang in ctx.languages:
            segments = [
                ShotSegment(
                    shot_id=shot.id,
                    video=project.build
                    / video.for_shot(shot.id, plan[shot.id].languages[lang].visual_set),
                    narration=project.build
                    / next(
                        c.path
                        for c in narration.clips
                        if c.shot_id == shot.id and c.language == lang
                    ),
                    seconds=plan[shot.id].languages[lang].seconds,
                    speed=plan[shot.id].languages[lang].clips[0].speed,
                )
                for shot in project.read_model("storyboard.json", Storyboard).shots
            ]
            output = project.out / f"{project.config.output_name}_{lang}.mp4"
            renders.append(
                LanguageRender(
                    language=lang,
                    output=output,
                    segments=segments,
                    music=project.build / music_item.path,
                )
            )
        config = project.config
        outputs: list[str] = []
        for render in renders:

            def make(render: LanguageRender = render) -> Made:
                job = AssemblyJob(
                    renders=[render], width=config.width, height=config.height, fps=config.fps
                )
                return Made(ctx.assembler.assemble(job))

            made = ctx.produce(
                f"assembly/{render.language}",
                inputs=Inputs(
                    files=[
                        *(s.video for s in render.segments),
                        *(s.narration for s in render.segments),
                        *([render.music] if render.music else []),
                    ],
                    values={
                        "seconds": [s.seconds for s in render.segments],
                        "speeds": [s.speed for s in render.segments],
                    },
                ),
                parameters={
                    "language": render.language,
                    "width": config.width,
                    "height": config.height,
                    "fps": config.fps,
                },
                make=make,
            )
            outputs += [p.relative_to(project.root).as_posix() for p in made.paths]
        return outputs


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
