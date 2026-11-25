"""The stage graph.

Stages run in :data:`STAGES` order (narration precedes video so durations are known; music needs
the fit plan's total length). Each stage reads the artifacts of earlier stages from ``build/`` and
writes its own, returning their paths relative to ``build/``.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, TypeVar, cast

from vidpipe.assembly import Assembler, AssemblyJob, LanguageRender, ShotSegment
from vidpipe.config import STAGE_KINDS
from vidpipe.contracts import (
    ImageToVideoProvider,
    ImageToVideoRequest,
    KeyframerProvider,
    KeyframeRequest,
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
    ShotPlan,
    Storyboard,
    StoryboardDraft,
)
from vidpipe.project import Project

P = TypeVar("P", bound=Provider)


class StageError(Exception):
    pass


@dataclass
class StageContext:
    project: Project
    providers: dict[str, Provider]
    assembler: Assembler

    def provider(self, stage: str, expected: type[P]) -> P:
        provider = self.providers.get(stage)
        if provider is None:
            raise StageError(f"no provider configured for stage {stage!r}")
        if not isinstance(provider, expected):
            raise StageError(f"stage {stage!r} has a {provider.kind.value} provider; wrong kind")
        return cast(P, provider)

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


def _item(ctx: StageContext, shot_id: int | None, path: Path) -> MediaItem:
    return MediaItem(shot_id=shot_id, path=path.relative_to(ctx.project.build).as_posix())


def _write_index(ctx: StageContext, name: str, items: list[MediaItem]) -> list[str]:
    return [ctx.project.write_model(name, MediaIndex(items=items)), *(i.path for i in items)]


class BriefStage(Stage):
    name = "brief"

    def run(self, ctx: StageContext) -> list[str]:
        return [ctx.project.write_model("brief.json", ctx.project.load_brief())]


class ScriptStage(Stage):
    name = "script"

    def run(self, ctx: StageContext) -> list[str]:
        brief = ctx.project.read_model("brief.json", Brief)
        provider = ctx.provider("script", TextProvider)
        prompt = (
            f"Write a short narration script in language {ctx.project.config.primary_language!r}, "
            f"one sentence per line, for a video titled {brief.title!r}.\n\n{brief.body}"
        )
        response = provider.complete(
            TextRequest(prompt=prompt, json_schema=ScriptDraft.model_json_schema())
        )
        draft = ScriptDraft.model_validate(response.data)
        script = Script(
            language=ctx.project.config.primary_language,
            title=brief.title,
            lines=[ScriptLine(id=i, text=t) for i, t in enumerate(draft.lines, start=1)],
        )
        return [ctx.project.write_model("script.json", script)]


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
                f"translation provider cannot translate from {ctx.project.config.primary_language!r}"
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
            response = provider.translate(
                TranslationRequest(
                    texts=[line.text for line in script.lines],
                    source_language=script.language,
                    target_language=lang,
                )
            )
            if len(response.texts) != len(script.lines):
                raise StageError(f"translation into {lang!r} returned the wrong number of lines")
            translated = Script(
                language=lang,
                title=script.title,
                lines=[
                    ScriptLine(id=line.id, text=text)
                    for line, text in zip(script.lines, response.texts, strict=True)
                ],
            )
            outputs.append(ctx.project.write_model(f"translation/{lang}.json", translated))
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
        return [ctx.project.write_model("storyboard.json", storyboard)]


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
                out = ctx.project.artifact_path(f"narration/{lang}/shot_{shot.id:02d}.wav")
                result = provider.synthesize(
                    TTSRequest(text=lines[shot.line_id], language=lang, output_path=out)
                )
                clips.append(
                    NarrationClip(
                        shot_id=shot.id,
                        language=lang,
                        path=result.path.relative_to(ctx.project.build).as_posix(),
                        duration_s=result.duration_s,
                    )
                )
        return [
            ctx.project.write_model("narration.json", Narration(clips=clips)),
            *(c.path for c in clips),
        ]


class FitPlanningStage(Stage):
    """Sizes each shot's clip to the longest narration across languages (``visuals: shared``)."""

    name = "fit-planning"

    def problems(self, ctx: StageContext) -> list[str]:
        visuals = ctx.project.config.visuals
        if visuals.value != "shared":
            return [f"visuals: {visuals.value} is not supported yet (only 'shared')"]
        return []

    def run(self, ctx: StageContext) -> list[str]:
        narration = ctx.project.read_model("narration.json", Narration)
        caps = ctx.provider("video", ImageToVideoProvider).capabilities
        shots: list[ShotPlan] = []
        for shot in ctx.project.read_model("storyboard.json", Storyboard).shots:
            longest = max(c.duration_s for c in narration.clips if c.shot_id == shot.id)
            seconds = max(caps.min_seconds, math.ceil(longest * 4) / 4)
            if seconds > caps.max_seconds:
                raise StageError(
                    f"shot {shot.id} narration is {longest:.2f}s but the video provider makes at "
                    f"most {caps.max_seconds}s per clip (continuation clips are a later ticket)"
                )
            shots.append(ShotPlan(shot_id=shot.id, clip_seconds=seconds))
        return [ctx.project.write_model("fit_plan.json", FitPlan(shots=shots))]


class KeyframesStage(Stage):
    name = "keyframes"

    def run(self, ctx: StageContext) -> list[str]:
        provider = ctx.provider("keyframes", KeyframerProvider)
        config = ctx.project.config
        items: list[MediaItem] = []
        for shot in ctx.project.read_model("storyboard.json", Storyboard).shots:
            out = ctx.project.artifact_path(f"keyframes/shot_{shot.id:02d}.png")
            result = provider.generate(
                KeyframeRequest(
                    prompt=shot.visual,
                    width=config.width,
                    height=config.height,
                    seed=shot.id,
                    output_path=out,
                )
            )
            items.append(_item(ctx, shot.id, result.path))
        return _write_index(ctx, "keyframes.json", items)


class VideoStage(Stage):
    name = "video"

    def run(self, ctx: StageContext) -> list[str]:
        provider = ctx.provider("video", ImageToVideoProvider)
        plan = {s.shot_id: s for s in ctx.project.read_model("fit_plan.json", FitPlan).shots}
        keyframes = ctx.project.read_model("keyframes.json", MediaIndex)
        items: list[MediaItem] = []
        for shot in ctx.project.read_model("storyboard.json", Storyboard).shots:
            image = ctx.project.build / keyframes.for_shot(shot.id)
            out = ctx.project.artifact_path(f"video/shot_{shot.id:02d}.mp4")
            result = provider.animate(
                ImageToVideoRequest(
                    image=image,
                    prompt=shot.visual,
                    motion_type=shot.motion_type,
                    duration_s=plan[shot.id].clip_seconds,
                    seed=shot.id,
                    output_path=out,
                )
            )
            items.append(_item(ctx, shot.id, result.path))
        return _write_index(ctx, "video.json", items)


class MusicStage(Stage):
    name = "music"

    def run(self, ctx: StageContext) -> list[str]:
        provider = ctx.provider("music", MusicProvider)
        brief = ctx.project.read_model("brief.json", Brief)
        total = ctx.project.read_model("fit_plan.json", FitPlan).total_seconds
        out = ctx.project.artifact_path("music/music.wav")
        result = provider.compose(
            MusicRequest(prompt=f"Instrumental score for: {brief.title}", duration_s=total,
                         output_path=out)
        )
        return _write_index(ctx, "music.json", [_item(ctx, None, result.path)])


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
                    video=project.build / video.for_shot(shot.id),
                    narration=project.build
                    / next(
                        c.path for c in narration.clips if c.shot_id == shot.id and c.language == lang
                    ),
                    seconds=plan[shot.id].clip_seconds,
                )
                for shot in project.read_model("storyboard.json", Storyboard).shots
            ]
            output = project.out / f"{project.config.output_name}_{lang}.mp4"
            renders.append(LanguageRender(language=lang, output=output, segments=segments, music=project.build / music_item.path))
        config = project.config
        written = ctx.assembler.assemble(
            AssemblyJob(renders=renders, width=config.width, height=config.height, fps=config.fps)
        )
        return [p.relative_to(project.root).as_posix() for p in written]


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
