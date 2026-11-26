"""Typed data passed between stages (each is persisted as JSON under ``build/``)."""

from __future__ import annotations

import math
import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from vidpipe.config import Visuals
from vidpipe.contracts import MotionType


class Brief(BaseModel):
    title: str
    body: str

    @classmethod
    def from_markdown(cls, text: str) -> Brief:
        match = re.search(r"^#\s+(.+?)\s*$", text, flags=re.MULTILINE)
        title = match.group(1) if match else "Untitled"
        body = text.replace(match.group(0), "", 1) if match else text
        return cls(title=title, body=body.strip())


class ScriptDraft(BaseModel):
    """What a text provider returns when asked to write the script."""

    lines: list[str] = Field(min_length=1)


class ScriptLine(BaseModel):
    id: int
    text: str


class Script(BaseModel):
    language: str
    title: str
    lines: list[ScriptLine]


NonBlank = Annotated[str, StringConstraints(pattern=r"\S")]


class ShotDraft(BaseModel):
    reason: NonBlank
    line_id: int
    visual: str
    motion_type: MotionType
    #: Ids from the project bible (see ``vidpipe.bible``): no ``character`` means the
    #: protagonist, ``"none"`` means nobody appears.
    character: str | None = None
    location: str | None = None


class StoryboardDraft(BaseModel):
    """What a text provider returns when asked to storyboard the script."""

    shots: list[ShotDraft] = Field(min_length=1)


class Shot(BaseModel):
    id: int
    line_id: int
    reason: str | None = None
    visual: str
    motion_type: MotionType
    character: str | None = None
    location: str | None = None


class Storyboard(BaseModel):
    shots: list[Shot]


class ContractShot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: int = Field(gt=0)
    reason: NonBlank
    narration: dict[str, NonBlank] = Field(min_length=1)
    visual: NonBlank
    motion_type: MotionType
    character: NonBlank | None = None
    location: NonBlank | None = None


class MusicCue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    shot: int = Field(gt=0)
    note: NonBlank


class StoryboardMusic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    prompt: NonBlank
    bpm: int | None = Field(default=None, gt=0)
    keyscale: NonBlank | None = None
    cues: list[MusicCue] = Field(default_factory=list[MusicCue])


CONTRACT_STAGES = frozenset({"script", "translation", "storyboard"})


class StoryboardContract(BaseModel):
    """The editable storyboard shared by the text and generation stages."""

    model_config = ConfigDict(extra="forbid", strict=True)

    title: NonBlank
    shots: list[ContractShot] = Field(min_length=1)
    music: StoryboardMusic

    @model_validator(mode="after")
    def _shot_references(self) -> StoryboardContract:
        ids = {shot.id for shot in self.shots}
        if len(ids) != len(self.shots):
            raise ValueError("shot ids must be unique")
        if unknown := sorted({cue.shot for cue in self.music.cues} - ids):
            raise ValueError(f"music cues refer to unknown shots: {unknown}")
        return self

    def script(self, language: str) -> Script:
        return Script(
            language=language,
            title=self.title,
            lines=[ScriptLine(id=shot.id, text=shot.narration[language]) for shot in self.shots],
        )

    def storyboard(self) -> Storyboard:
        return Storyboard(
            shots=[
                Shot(
                    id=shot.id,
                    line_id=shot.id,
                    reason=shot.reason,
                    visual=shot.visual,
                    motion_type=shot.motion_type,
                    character=shot.character,
                    location=shot.location,
                )
                for shot in self.shots
            ]
        )


class NarrationClip(BaseModel):
    shot_id: int
    language: str
    path: str  # relative to build/
    duration_s: float


class Narration(BaseModel):
    clips: list[NarrationClip]


class MediaItem(BaseModel):
    shot_id: int | None = None
    #: Which visual set a clip belongs to (see ``VisualSet.id``); ``None`` for other media.
    visual_set: str | None = None
    #: Which clip of the shot this is (0 is the first; later ones are continuation clips).
    clip: int = 0
    path: str  # relative to build/


class MediaIndex(BaseModel):
    """Index of the media files a stage produced (providers choose the real file suffix)."""

    items: list[MediaItem]

    def for_shot(self, shot_id: int, visual_set: str | None = None) -> str:
        """The shot's first clip."""
        return self.for_clip(shot_id, visual_set, 0)

    def for_clip(self, shot_id: int, visual_set: str | None, clip: int) -> str:
        return next(
            i.path
            for i in self.items
            if i.shot_id == shot_id
            and i.clip == clip
            and (visual_set is None or i.visual_set == visual_set)
        )


class FitLimits(BaseModel):
    """The numbers a fit plan was made with: the video provider's clip range and the house rules."""

    min_clip_s: float
    max_clip_s: float
    #: A clip may play at most this much faster or slower than it was generated.
    max_speed: float
    #: Each language's render must stay within this many seconds.
    max_render_s: float


class ClipPlan(BaseModel):
    """One clip to generate for a shot. The first starts from the shot's keyframe; every later
    one is a continuation, started from the previous clip's last frame."""

    index: int
    seconds: float
    #: Index of the clip whose last frame this one starts from (``None`` for the first clip).
    continues: int | None = None
    #: The narration this clip covers (in the language that sized it).
    text: str = ""


class VisualSet(BaseModel):
    """The clips generated for a shot, and which languages' renders use them."""

    #: ``shared``, or a language code (``per_language``, ``primary_only``).
    id: str
    #: The language whose narration sized the clips.
    driver: str
    languages: list[str]
    clips: list[ClipPlan]

    @property
    def seconds(self) -> float:
        return sum(c.seconds for c in self.clips)


class ClipUse(BaseModel):
    """How one render plays one clip: ``source_s`` of it (the rest trimmed) at ``speed`` times
    normal speed (below 1 is slower), lasting ``seconds`` on screen (``source_s / speed``)."""

    clip: int
    speed: float
    source_s: float
    seconds: float


class SegmentPlan(BaseModel):
    """A stretch of narration cut at a natural boundary, timed within the shot's render."""

    text: str
    start_s: float
    end_s: float
    #: The clip playing when this segment starts.
    clip: int


class LanguageFit(BaseModel):
    """How one language's render covers one shot."""

    language: str
    visual_set: str
    narration_s: float
    #: Whether ``narration_s`` is an estimate from the text (dry-run before narration exists).
    estimated: bool = False
    #: How long the shot lasts in this render: exactly as long as its narration.
    seconds: float
    clips: list[ClipUse]
    segments: list[SegmentPlan]


class ShotPlan(BaseModel):
    shot_id: int
    visual_sets: dict[str, VisualSet]
    languages: dict[str, LanguageFit]

    @property
    def continuation_clips(self) -> int:
        return sum(len(v.clips) - 1 for v in self.visual_sets.values())


class FitPlan(BaseModel):
    """Per shot: the clips to generate, and how each language's render plays them."""

    visuals: Visuals
    limits: FitLimits
    shots: list[ShotPlan]
    #: Length of each language's render.
    render_seconds: dict[str, float]
    #: Why the plan cannot be used (a render over the limit, narration no clip can cover).
    problems: list[str] = Field(default_factory=list[str])

    @property
    def total_seconds(self) -> float:
        """The longest render: what music must cover."""
        return max(self.render_seconds.values(), default=0.0)

    @property
    def music_seconds(self) -> int:
        """Round up so small timing changes can reuse the soundtrack."""
        return math.ceil(self.total_seconds)

    @property
    def clip_count(self) -> int:
        return sum(len(v.clips) for s in self.shots for v in s.visual_sets.values())

    @property
    def clip_seconds(self) -> float:
        """Video to generate, over every shot and visual set."""
        return sum(v.seconds for s in self.shots for v in s.visual_sets.values())


class StageRecord(BaseModel):
    stage: str
    provider: str | None
    outputs: list[str]
    #: Artifacts generated this run vs reused because their inputs were unchanged.
    generated: int = 0
    reused: int = 0

    @property
    def skipped(self) -> bool:
        return self.generated == 0


class Manifest(BaseModel):
    stages: list[StageRecord] = Field(default_factory=list[StageRecord])
