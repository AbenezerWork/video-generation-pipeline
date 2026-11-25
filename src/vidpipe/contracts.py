"""Typed provider contracts.

One contract per stage kind: text, translation, TTS, keyframer, image-to-video, music, song.
Each provider:

* declares a ``kind`` (which contract it implements) and a unique ``name``;
* declares ``capabilities`` (a typed model, checked at plan time before anything is generated);
* accepts a request model that carries an ``extras`` dict for provider-specific options;
* writes any media to ``request.output_path`` and returns a small result model.

Providers raise :class:`UnsupportedRequest` when a request falls outside their capabilities, and
:class:`GenerationError` when they cannot produce the asset (after any retries of their own). What
they had to do to produce it (retries, a quality step-down) goes back in a
:class:`GenerationRecord`, which the pipeline stores with the artifact.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
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


MOTION_DESCRIPTIONS: dict[MotionType, str] = {
    MotionType.PUSH_IN: "the camera slowly pushes in towards the subject",
    MotionType.PAN: "the camera slowly pans sideways across the scene",
    MotionType.AMBIENT: "the camera is still; only gentle motion in the scene (wind, steam, light)",
}


class UnsupportedRequest(Exception):
    """A request needs something the provider's capabilities do not declare."""


class GenerationError(Exception):
    """The provider could not produce the asset; the stage fails (completed artifacts are kept)."""


class Cancelled(Exception):  # noqa: N818 (not an error: the run asked for it)
    """The run asked the provider to drop the artifact in progress (stop now).

    Not a :class:`GenerationError`: nothing failed, so nothing is retried and the stage does not
    fail. A provider raises it after cleaning up (a ComfyUI job is taken out of the queue).
    """


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class ProjectContext(Frozen):
    """What the pipeline tells a provider about the project it works for (see ``attach``)."""

    #: The project directory; relative paths in provider options are resolved against it.
    root: Path
    #: ``comfyui.url`` from ``vidpipe.yaml``.
    comfyui_url: str | None = None
    #: True once the run is asked to stop now. A provider that can drop a long job polls it while
    #: it waits and then raises :class:`Cancelled`; one that cannot just finishes the artifact.
    stop_now: Callable[[], bool] | None = Field(default=None, exclude=True)


class GenerationRecord(BaseModel):
    """What a provider actually did to produce an asset, recorded with the artifact."""

    #: The seed that produced the output, when it differs from the requested one (a retry).
    seed: int | None = None
    #: In words: retries made and any quality step-down applied. ``None``: first try, as asked.
    fallback: str | None = None
    #: Exact GPU seconds, when the backend reports them.
    gpu_seconds: float | None = None
    #: JSON-able details worth keeping (settings used, attempts); stored in the ledger's ``data``.
    details: dict[str, Any] = Field(default_factory=dict[str, Any])


class Request(BaseModel):
    """Base request: provider-specific options go in ``extras``."""

    extras: dict[str, Any] = Field(default_factory=dict)


class Capabilities(Frozen):
    """Base capability declaration. Subclasses add typed fields per contract."""


class CostUnit(StrEnum):
    """What a :class:`CostModel` is priced per."""

    CALL = "call"  # per provider call (one image, one request)
    OUTPUT_SECOND = "output_second"  # per second of audio/video produced


class Cost(Frozen):
    """An estimated cost: local GPU minutes and/or hosted dollars."""

    gpu_minutes: float = 0.0
    dollars: float = 0.0

    def __add__(self, other: Cost) -> Cost:
        return Cost(
            gpu_minutes=self.gpu_minutes + other.gpu_minutes, dollars=self.dollars + other.dollars
        )


class CostModel(Frozen):
    """What a provider's work costs: GPU minutes locally, dollars for hosted providers.

    Priced per ``unit``: per call, or per second of output. A provider fills in only one of
    ``gpu_minutes`` (it runs on the local GPU) or ``dollars`` (it is hosted); the default is free.
    ``vidpipe plan`` multiplies this out before anything is generated.
    """

    unit: CostUnit = CostUnit.CALL
    gpu_minutes: float = Field(default=0.0, ge=0)
    dollars: float = Field(default=0.0, ge=0)

    def estimate(self, *, calls: int = 0, output_seconds: float = 0.0) -> Cost:
        units = calls if self.unit is CostUnit.CALL else output_seconds
        return Cost(gpu_minutes=self.gpu_minutes * units, dollars=self.dollars * units)


# --------------------------------------------------------------------------------------- text


class TextCapabilities(Capabilities):
    structured_output: bool = True


class TextRequest(Request):
    prompt: str
    json_schema: dict[str, Any]
    #: Optional check of each candidate answer; raises ``ValueError`` to reject it. Providers
    #: that can re-prompt (the CLI adapters) feed the error message back to the model.
    validator: Callable[[dict[str, Any]], None] | None = Field(default=None, exclude=True)


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
    #: Typical speaking time per character of text, for dry-run estimates made before narration
    #: exists (the planner uses real durations once they are known).
    seconds_per_char: float = 0.08


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
    #: How many reference images one request may carry (0: text prompts only).
    max_reference_images: int = 0
    min_width: int = 1
    min_height: int = 1
    max_width: int = 1024
    max_height: int = 1024
    #: Cap on width x height, when the two maxima cannot be used together.
    max_pixels: int | None = None
    width_multiple: int = 1
    height_multiple: int = 1

    def size_problems(self, width: int, height: int) -> list[str]:
        """Why this size cannot be drawn (empty when it can)."""
        found: list[str] = []
        sides = (
            ("width", width, self.min_width, self.max_width, self.width_multiple),
            ("height", height, self.min_height, self.max_height, self.height_multiple),
        )
        for name, value, low, high, multiple in sides:
            if not low <= value <= high:
                found.append(f"{name} {value} is outside {low}-{high}")
            if value % multiple:
                found.append(f"{name} {value} is not a multiple of {multiple}")
        if self.max_pixels is not None and width * height > self.max_pixels:
            found.append(f"{width}x{height} is more than {self.max_pixels} pixels")
        return found


class KeyframeRequest(Request):
    #: English description of the still. It calls the reference images "image 1", "image 2", ...
    prompt: str
    width: int
    height: int
    seed: int = 0
    #: In order of importance: the character first, then the location or style (ADR 0001).
    reference_images: list[Path] = Field(default_factory=list[Path])
    output_path: Path


class KeyframeResult(BaseModel):
    path: Path
    width: int
    height: int
    record: GenerationRecord = Field(default_factory=GenerationRecord)


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
    record: GenerationRecord = Field(default_factory=GenerationRecord)


# ------------------------------------------------------------------------------------- music


class MusicCapabilities(Capabilities):
    max_seconds: float = Field(default=120.0, gt=0)
    min_seconds: float = Field(default=0.0, ge=0)

    def duration_problem(self, seconds: float) -> str | None:
        if seconds > 0 and self.min_seconds <= seconds <= self.max_seconds:
            return None
        lower = f"at least {self.min_seconds:g} s" if self.min_seconds > 0 else "greater than 0 s"
        return f"music duration {seconds:g} s must be {lower} and at most {self.max_seconds:g} s"


class MusicRequest(Request):
    prompt: str
    duration_s: float
    seed: int = 0
    output_path: Path


class MusicResult(BaseModel):
    path: Path
    duration_s: float
    record: GenerationRecord = Field(default_factory=GenerationRecord)


# -------------------------------------------------------------------------------------- song


class SongCapabilities(Capabilities):
    max_seconds: float = 120.0
    vocal_languages: frozenset[str] = frozenset({"en"})


class SongRequest(Request):
    """A song prompt and the lyrics and language for its vocal performance."""

    prompt: str
    lyrics: str
    language: str = "en"
    duration_s: float
    seed: int = 0
    output_path: Path


class SongResult(BaseModel):
    """One audio mix containing the song and its vocals."""

    path: Path
    duration_s: float


# ------------------------------------------------------------------------------------ providers


class Provider[C: Capabilities](ABC):
    """Base class for every provider. Subclasses also inherit one contract class below."""

    kind: ClassVar[ProviderKind]
    name: ClassVar[str]
    #: Fakes run in CI; real providers run the same conformance suite under ``integration``.
    fake: ClassVar[bool] = False
    #: Generation runs on the local GPU, so the call's wall time is recorded as GPU time.
    uses_gpu: ClassVar[bool] = False
    #: Options that cannot change the output (a server address, a timeout), so changing them
    #: regenerates nothing. ``fingerprint`` must leave them out too.
    unhashed_options: ClassVar[frozenset[str]] = frozenset()
    capabilities: C
    #: What this provider's work costs (free unless it declares otherwise); see ``vidpipe plan``.
    cost: CostModel = CostModel()

    def __init__(self, **options: Any) -> None:
        self.options = options

    def fingerprint(self) -> dict[str, Any]:
        """Identity hashed into every artifact this provider produces.

        Override to add anything else that changes the output (workflow JSON, checkpoint, model
        version): the artifacts it made are then regenerated when that changes.
        """
        return {"name": self.name, "options": self.options}

    def attach(self, context: ProjectContext) -> None:  # noqa: B027 - optional hook
        """Called once by the pipeline before the provider is used on a project."""

    def release(self) -> None:  # noqa: B027 - optional hook
        """Give back what the provider holds (GPU memory). The pipeline calls it after each stage
        that used the provider, also when the stage failed; it must not raise."""


class TextProvider(Provider[TextCapabilities]):
    kind = ProviderKind.TEXT
    capabilities = TextCapabilities()

    @abstractmethod
    def complete(self, request: TextRequest) -> TextResponse: ...


class TranslationProvider(Provider[TranslationCapabilities]):
    kind = ProviderKind.TRANSLATION

    @abstractmethod
    def translate(self, request: TranslationRequest) -> TranslationResponse: ...


class TTSProvider(Provider[TTSCapabilities]):
    kind = ProviderKind.TTS

    @abstractmethod
    def synthesize(self, request: TTSRequest) -> TTSResult: ...


class KeyframerProvider(Provider[KeyframerCapabilities]):
    kind = ProviderKind.KEYFRAMER

    @abstractmethod
    def generate(self, request: KeyframeRequest) -> KeyframeResult: ...


class ImageToVideoProvider(Provider[ImageToVideoCapabilities]):
    kind = ProviderKind.IMAGE_TO_VIDEO

    @abstractmethod
    def animate(self, request: ImageToVideoRequest) -> ImageToVideoResult: ...


class MusicProvider(Provider[MusicCapabilities]):
    kind = ProviderKind.MUSIC

    @abstractmethod
    def compose(self, request: MusicRequest) -> MusicResult: ...


class SongProvider(Provider[SongCapabilities]):
    kind = ProviderKind.SONG

    @abstractmethod
    def sing(self, request: SongRequest) -> SongResult: ...
