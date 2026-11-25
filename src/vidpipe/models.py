"""Typed data passed between stages (each is persisted as JSON under ``build/``)."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

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


class ShotDraft(BaseModel):
    line_id: int
    visual: str
    motion_type: MotionType


class StoryboardDraft(BaseModel):
    """What a text provider returns when asked to storyboard the script."""

    shots: list[ShotDraft] = Field(min_length=1)


class Shot(BaseModel):
    id: int
    line_id: int
    visual: str
    motion_type: MotionType


class Storyboard(BaseModel):
    shots: list[Shot]


class NarrationClip(BaseModel):
    shot_id: int
    language: str
    path: str  # relative to build/
    duration_s: float


class Narration(BaseModel):
    clips: list[NarrationClip]


class MediaItem(BaseModel):
    shot_id: int | None = None
    path: str  # relative to build/


class MediaIndex(BaseModel):
    """Index of the media files a stage produced (providers choose the real file suffix)."""

    items: list[MediaItem]

    def for_shot(self, shot_id: int) -> str:
        return next(i.path for i in self.items if i.shot_id == shot_id)


class ShotPlan(BaseModel):
    shot_id: int
    clip_seconds: float
    clips: int = 1


class FitPlan(BaseModel):
    shots: list[ShotPlan]

    @property
    def total_seconds(self) -> float:
        return sum(s.clip_seconds * s.clips for s in self.shots)


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
