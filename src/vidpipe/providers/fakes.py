"""Fake providers: one per contract, returning tiny deterministic assets with no GPU or network.

They run in CI and in the walking-skeleton demo, and pass the same conformance suite as every real
provider. Two extra variants (``fake-translation-upper``, ``fake-tts-en-only``) exist so that
"swap a provider in YAML" and plan-time capability rejection are observable.
"""

from __future__ import annotations

from typing import Any

from vidpipe.contracts import (
    CostModel,
    CostUnit,
    ImageToVideoCapabilities,
    ImageToVideoProvider,
    ImageToVideoRequest,
    ImageToVideoResult,
    KeyframerCapabilities,
    KeyframeRequest,
    KeyframeResult,
    KeyframerProvider,
    MotionType,
    MusicCapabilities,
    MusicProvider,
    MusicRequest,
    MusicResult,
    SongCapabilities,
    SongProvider,
    SongRequest,
    SongResult,
    TextCapabilities,
    TextProvider,
    TextRequest,
    TextResponse,
    TranslationCapabilities,
    TranslationProvider,
    TranslationRequest,
    TranslationResponse,
    TTSCapabilities,
    TTSProvider,
    TTSRequest,
    TTSResult,
    UnsupportedRequest,
)
from vidpipe.providers._media import (
    Y4M_FPS,
    color_from,
    png_size,
    stable_int,
    write_png,
    write_wav,
    write_y4m,
)
from vidpipe.registry import register

LANGUAGES = frozenset({"en", "am"})


# ------------------------------------------------------------------------------------------ text

CANNED_SCRIPT = [
    "High in the Ethiopian highlands, a young goat herder watched his flock.",
    "One evening the goats ate bright red berries, and began to dance.",
    "He carried the berries home, and the first cup of coffee was born.",
]

CANNED_SHOTS = [
    ("A goat herder on a misty highland ridge at dawn", MotionType.PAN),
    ("Goats leaping among a shrub of red coffee berries", MotionType.AMBIENT),
    ("A steaming clay cup of coffee on a wooden table", MotionType.PUSH_IN),
]


def _instance_for(schema: dict[str, Any], defs: dict[str, Any] | None = None) -> Any:
    """Smallest value that satisfies a JSON schema (enough for conformance-style schemas)."""
    resolved: dict[str, Any] = defs if defs is not None else schema.get("$defs", {})
    if "$ref" in schema:
        return _instance_for(resolved[str(schema["$ref"]).rsplit("/", 1)[-1]], resolved)
    if "enum" in schema:
        return schema["enum"][0]
    if "anyOf" in schema:
        return _instance_for(schema["anyOf"][0], resolved)
    kind = schema.get("type")
    if kind == "object":
        return {k: _instance_for(v, resolved) for k, v in schema.get("properties", {}).items()}
    if kind == "array":
        return [_instance_for(schema.get("items", {}), resolved)]
    if kind == "string":
        return "text"
    if kind == "integer":
        return 1
    if kind == "number":
        return 1.0
    if kind == "boolean":
        return True
    return None


@register
class FakeText(TextProvider):
    name = "fake-text"
    fake = True
    capabilities = TextCapabilities(structured_output=True)

    def complete(self, request: TextRequest) -> TextResponse:
        title = request.json_schema.get("title")
        if title == "ScriptDraft":
            return TextResponse(data={"lines": CANNED_SCRIPT})
        if title == "StoryboardDraft":
            shots = [
                {"line_id": i, "visual": visual, "motion_type": motion.value}
                for i, (visual, motion) in enumerate(CANNED_SHOTS, start=1)
            ]
            return TextResponse(data={"shots": shots})
        return TextResponse(data=_instance_for(request.json_schema))


# ------------------------------------------------------------------------------------ translation


class _FakeTranslation(TranslationProvider):
    fake = True
    capabilities = TranslationCapabilities(source_languages=LANGUAGES, target_languages=LANGUAGES)

    def render(self, text: str, target: str) -> str:
        raise NotImplementedError

    def translate(self, request: TranslationRequest) -> TranslationResponse:
        caps = self.capabilities
        if request.source_language not in caps.source_languages:
            raise UnsupportedRequest(f"source language {request.source_language!r}")
        if request.target_language not in caps.target_languages:
            raise UnsupportedRequest(f"target language {request.target_language!r}")
        return TranslationResponse(
            texts=[self.render(t, request.target_language) for t in request.texts]
        )


@register
class FakeTranslation(_FakeTranslation):
    name = "fake-translation"

    def render(self, text: str, target: str) -> str:
        return f"[{target}] {text}"


@register
class FakeTranslationUpper(_FakeTranslation):
    name = "fake-translation-upper"

    def render(self, text: str, target: str) -> str:
        return f"[{target}] {text.upper()}"


# ------------------------------------------------------------------------------------------ tts


class _FakeTTS(TTSProvider):
    """Speaks at ``seconds_per_char`` (clamped to 1 s..``max_seconds``). Both are configurable, so
    tests can make narration as long as real speech (edge-tts runs about 0.08 s per character)."""

    fake = True
    languages: frozenset[str] = LANGUAGES

    def __init__(
        self, *, seconds_per_char: float = 0.05, max_seconds: float = 4.0, **options: Any
    ) -> None:
        super().__init__(**options)
        self.seconds_per_char = seconds_per_char
        self.max_seconds = max_seconds
        self.capabilities = TTSCapabilities(
            languages=self.languages, seconds_per_char=seconds_per_char
        )

    def synthesize(self, request: TTSRequest) -> TTSResult:
        if request.language not in self.capabilities.languages:
            raise UnsupportedRequest(f"language {request.language!r}")
        duration = min(
            self.max_seconds, max(1.0, round(len(request.text) * self.seconds_per_char, 2))
        )
        path = request.output_path.with_suffix(".wav")
        write_wav(path, duration, 180 + stable_int(request.language, request.voice) % 120)
        return TTSResult(path=path, duration_s=duration)


@register
class FakeTTS(_FakeTTS):
    name = "fake-tts"


@register
class FakeTTSEnglishOnly(_FakeTTS):
    name = "fake-tts-en-only"
    languages = frozenset({"en"})


# -------------------------------------------------------------------------------------- keyframer


@register
class FakeKeyframer(KeyframerProvider):
    name = "fake-keyframer"
    fake = True
    uses_gpu = True  # stands in for a GPU-backed provider
    capabilities = KeyframerCapabilities(reference_images=True, max_width=512, max_height=512)
    cost = CostModel(unit=CostUnit.CALL, gpu_minutes=0.4)  # per image

    def generate(self, request: KeyframeRequest) -> KeyframeResult:
        caps = self.capabilities
        if request.width > caps.max_width or request.height > caps.max_height:
            raise UnsupportedRequest(f"size {request.width}x{request.height}")
        if request.reference_images and not caps.reference_images:
            raise UnsupportedRequest("reference images")
        path = request.output_path.with_suffix(".png")
        write_png(path, request.width, request.height, color_from(request.prompt, request.seed))
        return KeyframeResult(path=path, width=request.width, height=request.height)


# ------------------------------------------------------------------------------- image-to-video


@register
class FakeImageToVideo(ImageToVideoProvider):
    name = "fake-i2v"
    fake = True
    uses_gpu = True  # stands in for a GPU-backed provider
    capabilities = ImageToVideoCapabilities(min_seconds=1.0, max_seconds=5.0)
    cost = CostModel(unit=CostUnit.OUTPUT_SECOND, gpu_minutes=0.5)  # per second of video

    def animate(self, request: ImageToVideoRequest) -> ImageToVideoResult:
        caps = self.capabilities
        if not caps.min_seconds <= request.duration_s <= caps.max_seconds:
            raise UnsupportedRequest(f"duration {request.duration_s}s")
        if request.motion_type not in caps.motion_types:
            raise UnsupportedRequest(f"motion type {request.motion_type.value!r}")
        width, height = png_size(request.image)
        frames = round(request.duration_s * Y4M_FPS)
        path = request.output_path.with_suffix(".y4m")
        write_y4m(path, width, height, frames, color_from(request.image.name, request.seed))
        return ImageToVideoResult(path=path, duration_s=frames / Y4M_FPS)


@register
class FakeImageToVideoHosted(FakeImageToVideo):
    """A hosted video provider: priced in dollars, no local GPU time."""

    name = "fake-i2v-hosted"
    uses_gpu = False
    cost = CostModel(unit=CostUnit.OUTPUT_SECOND, dollars=0.05)  # per second of video


# ---------------------------------------------------------------------------------- music / song


@register
class FakeMusic(MusicProvider):
    name = "fake-music"
    fake = True
    uses_gpu = True  # stands in for a GPU-backed provider
    capabilities = MusicCapabilities(max_seconds=120.0)
    cost = CostModel(unit=CostUnit.OUTPUT_SECOND, gpu_minutes=0.05)  # per second of music

    def compose(self, request: MusicRequest) -> MusicResult:
        if request.duration_s > self.capabilities.max_seconds:
            raise UnsupportedRequest(f"duration {request.duration_s}s")
        path = request.output_path.with_suffix(".wav")
        write_wav(path, request.duration_s, 110 + stable_int(request.prompt, request.seed) % 60)
        return MusicResult(path=path, duration_s=request.duration_s)


@register
class FakeSong(SongProvider):
    name = "fake-song"
    fake = True
    capabilities = SongCapabilities(max_seconds=120.0, vocal_languages=frozenset({"en"}))

    def sing(self, request: SongRequest) -> SongResult:
        caps = self.capabilities
        if request.duration_s > caps.max_seconds:
            raise UnsupportedRequest(f"duration {request.duration_s}s")
        if request.language not in caps.vocal_languages:
            raise UnsupportedRequest(f"vocal language {request.language!r}")
        path = request.output_path.with_suffix(".wav")
        write_wav(path, request.duration_s, 330 + stable_int(request.lyrics) % 60)
        return SongResult(path=path, duration_s=request.duration_s)
