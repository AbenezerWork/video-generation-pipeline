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
            primary: dict[str, Any] = {"name": first} if isinstance(first, str) else dict(first)
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


#: What the end card says when ``end_card.text`` does not name the language: a headline line, then
#: smaller lines. A language without its own text gets the English one.
DEFAULT_END_CARD_TEXT = {
    "en": (
        "AI-generated video\n"
        "The story, images, motion, voices and music were made with AI models.\n"
        "Any resemblance to real people or voices is coincidental."
    ),
    "am": (
        "በሰው ሰራሽ አስተውሎት (AI) የተሰራ ቪዲዮ\n"
        "ታሪኩ፣ ምስሎቹ፣ እንቅስቃሴው፣ ድምጾቹ እና ሙዚቃው በAI ሞዴሎች የተሰሩ ናቸው።\n"
        "ከእውነተኛ ሰዎች ወይም ድምጾች ጋር ያለ ማንኛውም መመሳሰል በአጋጣሚ ነው።\n"
        "AI-generated video"
    ),
}


class EndCardConfig(BaseModel):
    """A closing card after the last shot that says the video is AI-generated. The music plays on
    under it and fades out; the subtitles' font is used for its language."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    seconds: float = Field(default=5.0, gt=0, le=15)
    #: Per language: the first line is the headline, the others are smaller.
    text: dict[str, str] = Field(default_factory=dict)

    def text_for(self, language: str) -> str:
        return (
            self.text.get(language)
            or DEFAULT_END_CARD_TEXT.get(language)
            or DEFAULT_END_CARD_TEXT["en"]
        ).strip()


class OutputSize(BaseModel):
    """The rendered frame when it differs from the generated one: the picture is scaled to cover
    it and cropped to its shape (``1280x720`` from 640x352 trims 2% of the width)."""

    model_config = ConfigDict(extra="forbid")

    width: int = Field(gt=0)
    height: int = Field(gt=0)

    @model_validator(mode="after")
    def _even(self) -> OutputSize:
        if self.width % 2 or self.height % 2:
            raise ValueError("output_size needs even numbers (H.264 with yuv420p)")
        return self


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
    #: Rendered frame size; unset renders at ``width`` x ``height``.
    output_size: OutputSize | None = None
    #: Stages after which the run pauses for approval (see `vidpipe.gates`); `[]` for none.
    gates: list[str] = Field(default_factory=lambda: list(DEFAULT_GATES))
    subtitles: SubtitleConfig = Field(default_factory=SubtitleConfig)
    mix: MixConfig = Field(default_factory=MixConfig)
    #: Off unless the project has an ``end_card:`` block (``end_card: {}`` uses the defaults).
    end_card: EndCardConfig | None = None
    comfyui: ComfyUIConfig = Field(default_factory=ComfyUIConfig)
    #: Missing ``script``, ``storyboard`` and ``translation`` entries default to
    #: ``DEFAULT_TEXT_CHAIN``.
    providers: dict[str, ProviderSelection]

    @property
    def render_size(self) -> tuple[int, int]:
        """The final videos' frame: ``output_size``, or the generated ``width`` x ``height``."""
        size = self.output_size
        return (size.width, size.height) if size else (self.width, self.height)

    @property
    def end_card_seconds(self) -> float:
        """How long the end card adds to every render (0 without one)."""
        card = self.end_card
        return card.seconds if card is not None and card.enabled else 0.0

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
