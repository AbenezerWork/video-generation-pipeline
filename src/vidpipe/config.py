"""Project configuration (``vidpipe.yaml``)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from vidpipe.contracts import ProviderKind

CONFIG_FILENAME = "vidpipe.yaml"


#: Where the run pauses unless `gates:` says otherwise.
DEFAULT_GATES = ("script", "storyboard", "keyframes")


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
            try:
                primary: dict[str, Any] = {"name": first} if isinstance(first, str) else dict(first)
            except (TypeError, ValueError) as exc:
                raise ValueError("A provider chain must start with a name or mapping") from exc
            return {**primary, "fallback": rest}
        return cast(Any, value)

    @property
    def label(self) -> str:
        """``gemini-cli`` or, for a chain, ``gemini-cli > claude-cli``."""
        return " > ".join([self.name, *(f.name for f in self.fallback)])


#: What ``script``, ``storyboard`` and ``translation`` use when ``vidpipe.yaml`` names no provider.
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


#: The font burned-in Amharic subtitles use (it is bundled with vidpipe, see ``assets/fonts``).
GEEZ_FONT = "Noto Sans Ethiopic"


class SubtitleConfig(BaseModel):
    """Subtitles: a sidecar ``.srt`` per language, burned in unless ``burn_in`` is off."""

    model_config = ConfigDict(extra="forbid")

    burn_in: bool = True
    #: Folder of font files libass may use, relative to the project directory (or absolute). Unset:
    #: the project's own ``fonts/`` folder if it has one, else the fonts bundled with vidpipe.
    fonts_dir: str | None = None
    #: Font family per language. A language not listed uses the system default font (fine for Latin
    #: script); Amharic needs Ethiopic glyphs, so it gets the bundled Noto Sans Ethiopic.
    fonts: dict[str, str] = Field(default_factory=lambda: {"am": GEEZ_FONT})
    #: Text size in libass script units, where the video's height is 288 (so it scales with it).
    font_size: int = Field(default=20, gt=0)


class MixConfig(BaseModel):
    """The soundtrack: music sits at ``music_level`` and ducks under narration."""

    model_config = ConfigDict(extra="forbid")

    #: Music gain (1.0 is the music provider's own level) while nobody is speaking.
    music_level: float = Field(default=0.4, gt=0, le=2)
    #: How hard narration pushes the music down (a sidechain compressor's ratio: higher is deeper).
    duck_ratio: float = Field(default=8.0, ge=1, le=20)


class ComfyUIConfig(BaseModel):
    """The ComfyUI server every ``comfyui-*`` provider talks to (it runs outside vidpipe)."""

    model_config = ConfigDict(extra="forbid")

    #: Default ``http://127.0.0.1:8188``. A provider's own ``url`` option wins over this.
    url: str | None = None


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The first language is the primary one: the script is written in it.
    languages: list[str] = Field(default_factory=lambda: ["en"], min_length=1)
    visuals: Visuals = Visuals.SHARED
    output_name: str = "demo"
    width: int = 160
    height: int = 90
    fps: int = 8
    #: Stages after which the run pauses for approval (see `vidpipe.gates`); `[]` for none.
    gates: list[str] = Field(default_factory=lambda: list(DEFAULT_GATES))
    subtitles: SubtitleConfig = Field(default_factory=SubtitleConfig)
    mix: MixConfig = Field(default_factory=MixConfig)
    comfyui: ComfyUIConfig = Field(default_factory=ComfyUIConfig)
    #: Missing ``script``, ``storyboard`` and ``translation`` entries default to
    #: ``DEFAULT_TEXT_CHAIN``.
    providers: dict[str, ProviderSelection]

    @field_validator("providers", mode="before")
    @classmethod
    def _default_text_chains(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        defaults = {stage: DEFAULT_TEXT_CHAIN for stage in ("script", "storyboard", "translation")}
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
