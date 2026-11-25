"""Project configuration (``vidpipe.yaml``)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from vidpipe.contracts import ProviderKind

CONFIG_FILENAME = "vidpipe.yaml"


class Visuals(StrEnum):
    SHARED = "shared"
    PER_LANGUAGE = "per_language"
    PRIMARY_ONLY = "primary_only"


class ProviderSelection(BaseModel):
    """Which provider implements a stage. YAML accepts ``name`` or ``{name:, options:}``."""

    model_config = ConfigDict(frozen=True)

    name: str
    options: dict[str, Any] = Field(default_factory=dict)
    #: Providers to fall back to, in order, after this one fails or is rate limited. Acted on for
    #: text stages (e.g. ``script: [gemini-cli, claude-cli]``); for other stages it is declared and
    #: validated only (``narration: {name: edge-tts, fallback: [mms-tts]}``).
    fallback: tuple[ProviderSelection, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _from_string_or_chain(cls, value: Any) -> Any:
        """YAML forms: ``name``, ``{name:, options:}``, or a list (primary, then fallbacks)."""
        if isinstance(value, str):
            return {"name": value}
        if isinstance(value, list) and value:
            first, *rest = cast(list[Any], value)
            primary: dict[str, Any] = {"name": first} if isinstance(first, str) else dict(first)
            return {**primary, "fallback": rest}
        return cast(Any, value)

    @property
    def label(self) -> str:
        """``gemini-cli`` or, for a chain, ``gemini-cli > claude-cli``."""
        return " > ".join([self.name, *(f.name for f in self.fallback)])


#: What ``script`` and ``storyboard`` use when ``vidpipe.yaml`` does not choose a provider.
DEFAULT_TEXT_CHAIN = ["gemini-cli", "claude-cli"]


#: Stage name -> the contract kind that implements it.
STAGE_KINDS: dict[str, ProviderKind] = {
    "script": ProviderKind.TEXT,
    "translation": ProviderKind.TRANSLATION,
    "storyboard": ProviderKind.TEXT,
    "narration": ProviderKind.TTS,
    "keyframes": ProviderKind.KEYFRAMER,
    "video": ProviderKind.IMAGE_TO_VIDEO,
    "music": ProviderKind.MUSIC,
}


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The first language is the primary one: the script is written in it.
    languages: list[str] = Field(default_factory=lambda: ["en"], min_length=1)
    visuals: Visuals = Visuals.SHARED
    output_name: str = "demo"
    width: int = 160
    height: int = 90
    fps: int = 8
    #: Missing ``script`` and ``storyboard`` entries default to ``DEFAULT_TEXT_CHAIN``.
    providers: dict[str, ProviderSelection]

    @field_validator("providers", mode="before")
    @classmethod
    def _default_text_chains(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        defaults = {stage: DEFAULT_TEXT_CHAIN for stage in ("script", "storyboard")}
        return {**defaults, **cast(dict[str, Any], value)}

    @field_validator("providers")
    @classmethod
    def _known_stages(cls, value: dict[str, ProviderSelection]) -> dict[str, ProviderSelection]:
        unknown = sorted(set(value) - set(STAGE_KINDS) - {"song"})
        if unknown:
            raise ValueError(f"unknown stage(s) in providers: {', '.join(unknown)}")
        return value

    @property
    def primary_language(self) -> str:
        return self.languages[0]
