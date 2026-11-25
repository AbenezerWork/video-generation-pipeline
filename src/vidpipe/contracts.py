"""Typed provider contracts.

One contract per stage kind: text, translation, TTS, keyframer, image-to-video, music, song.
Each provider:

* declares a ``kind`` (which contract it implements) and a unique ``name``;
* declares ``capabilities`` (a typed model, checked at plan time before anything is generated);
* accepts a request model that carries an ``extras`` dict for provider-specific options;
* writes any media to ``request.output_path`` and returns a small result model.

Providers raise :class:`UnsupportedRequest` when a request falls outside their capabilities.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field


class ProviderKind(StrEnum):
    TEXT = "text"
    TRANSLATION = "translation"
    TTS = "tts"
    KEYFRAMER = "keyframer"
    IMAGE_TO_VIDEO = "image_to_video"
    MUSIC = "music"
    SONG = "song"


class MotionType(StrEnum):
    """Shot motion vocabulary, limited to what image-to-video models do well."""

    PUSH_IN = "push_in"
    PAN = "pan"
    AMBIENT = "ambient"


class UnsupportedRequest(Exception):
    """A request needs something the provider's capabilities do not declare."""


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Request(BaseModel):
    """Base request: provider-specific options go in ``extras``."""

    extras: dict[str, Any] = Field(default_factory=dict)


class Capabilities(Frozen):
    """Base capability declaration. Subclasses add typed fields per contract."""


# --------------------------------------------------------------------------------------- text


class TextCapabilities(Capabilities):
    structured_output: bool = True


class TextRequest(Request):
    prompt: str
    json_schema: dict[str, Any]


class TextResponse(BaseModel):
    data: dict[str, Any]


# ---------------------------------------------------------------------------------- translation


class TranslationCapabilities(Capabilities):
    source_languages: frozenset[str]
    target_languages: frozenset[str]


class TranslationRequest(Request):
    texts: list[str]
    source_language: str
    target_language: str


class TranslationResponse(BaseModel):
    texts: list[str]


# ------------------------------------------------------------------------------------------ tts


class TTSCapabilities(Capabilities):
    languages: frozenset[str]


class TTSRequest(Request):
    text: str
    language: str
    voice: str | None = None
    output_path: Path


class TTSResult(BaseModel):
    path: Path
    duration_s: float


# -------------------------------------------------------------------------------------- keyframer


class KeyframerCapabilities(Capabilities):
    reference_images: bool = False
    max_width: int = 1024
    max_height: int = 1024


class KeyframeRequest(Request):
    prompt: str
    width: int
    height: int
    seed: int = 0
    reference_images: list[Path] = Field(default_factory=list)
    output_path: Path


class KeyframeResult(BaseModel):
    path: Path
    width: int
    height: int


# ------------------------------------------------------------------------------ image-to-video


class ImageToVideoCapabilities(Capabilities):
    min_seconds: float = 2.0
    max_seconds: float = 5.0
    motion_types: frozenset[MotionType] = frozenset(MotionType)
    max_width: int = 1024
    max_height: int = 1024


class ImageToVideoRequest(Request):
    image: Path
    prompt: str
    motion_type: MotionType
    duration_s: float
    seed: int = 0
    output_path: Path


class ImageToVideoResult(BaseModel):
    path: Path
    duration_s: float


# ------------------------------------------------------------------------------------- music


class MusicCapabilities(Capabilities):
    max_seconds: float = 120.0


class MusicRequest(Request):
    prompt: str
    duration_s: float
    seed: int = 0
    output_path: Path


class MusicResult(BaseModel):
    path: Path
    duration_s: float


# -------------------------------------------------------------------------------------- song


class SongCapabilities(Capabilities):
    max_seconds: float = 120.0
    vocal_languages: frozenset[str] = frozenset({"en"})


class SongRequest(Request):
    prompt: str
    lyrics: str
    language: str = "en"
    duration_s: float
    seed: int = 0
    output_path: Path


class SongResult(BaseModel):
    path: Path
    duration_s: float


# ------------------------------------------------------------------------------------ providers


class Provider(ABC):
    """Base class for every provider. Subclasses also inherit one contract class below."""

    kind: ClassVar[ProviderKind]
    name: ClassVar[str]
    #: Fakes run in CI; real providers run the same conformance suite under ``integration``.
    fake: ClassVar[bool] = False
    capabilities: Capabilities

    def __init__(self, **options: Any) -> None:
        self.options = options


class TextProvider(Provider):
    kind = ProviderKind.TEXT
    capabilities: TextCapabilities = TextCapabilities()

    @abstractmethod
    def complete(self, request: TextRequest) -> TextResponse: ...


class TranslationProvider(Provider):
    kind = ProviderKind.TRANSLATION
    capabilities: TranslationCapabilities

    @abstractmethod
    def translate(self, request: TranslationRequest) -> TranslationResponse: ...


class TTSProvider(Provider):
    kind = ProviderKind.TTS
    capabilities: TTSCapabilities

    @abstractmethod
    def synthesize(self, request: TTSRequest) -> TTSResult: ...


class KeyframerProvider(Provider):
    kind = ProviderKind.KEYFRAMER
    capabilities: KeyframerCapabilities

    @abstractmethod
    def generate(self, request: KeyframeRequest) -> KeyframeResult: ...


class ImageToVideoProvider(Provider):
    kind = ProviderKind.IMAGE_TO_VIDEO
    capabilities: ImageToVideoCapabilities

    @abstractmethod
    def animate(self, request: ImageToVideoRequest) -> ImageToVideoResult: ...


class MusicProvider(Provider):
    kind = ProviderKind.MUSIC
    capabilities: MusicCapabilities

    @abstractmethod
    def compose(self, request: MusicRequest) -> MusicResult: ...


class SongProvider(Provider):
    kind = ProviderKind.SONG
    capabilities: SongCapabilities

    @abstractmethod
    def sing(self, request: SongRequest) -> SongResult: ...
