"""Seam 2: one shared conformance suite per provider contract.

Every provider, fake or real, must pass the suite for its contract. Each ``check_*`` function
exercises only the public contract (request in, result out, capabilities declared) so it can run
unchanged against a real ComfyUI, CLI or edge-tts provider under the ``integration`` marker.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from vidpipe.contracts import (
    ImageToVideoProvider,
    ImageToVideoRequest,
    KeyframeRequest,
    KeyframerProvider,
    MotionType,
    MusicProvider,
    MusicRequest,
    Provider,
    SongProvider,
    SongRequest,
    TextProvider,
    TextRequest,
    TranslationProvider,
    TranslationRequest,
    TTSProvider,
    TTSRequest,
    UnsupportedRequest,
)
from vidpipe.providers._audio import audio_duration_s
from vidpipe.providers._media import png_size, write_png

UNSUPPORTED_LANGUAGE = "zz-unsupported"


class Echo(BaseModel):
    word: str
    count: int


def _same_place(requested: Path, actual: Path) -> None:
    """Providers may pick the file suffix, but must write where they were asked to."""
    assert actual.parent == requested.parent
    assert actual.stem == requested.stem
    assert actual.is_file()
    assert actual.stat().st_size > 0


def check_text(provider: TextProvider, tmp_path: Path) -> None:
    response = provider.complete(
        TextRequest(
            prompt="Return a word and a count.",
            json_schema=Echo.model_json_schema(),
            extras={"unknown_option": True},  # extras never break a provider
        )
    )
    Echo.model_validate(response.data)


def check_translation(provider: TranslationProvider, tmp_path: Path) -> None:
    caps = provider.capabilities
    source = "en" if "en" in caps.source_languages else sorted(caps.source_languages)[0]
    target = next(
        (lang for lang in sorted(caps.target_languages) if lang != source),
        sorted(caps.target_languages)[0],
    )
    texts = ["Hello there.", "Good morning."]
    response = provider.translate(
        TranslationRequest(texts=texts, source_language=source, target_language=target)
    )
    assert len(response.texts) == len(texts)
    assert all(t.strip() for t in response.texts)
    with pytest.raises(UnsupportedRequest):
        provider.translate(
            TranslationRequest(
                texts=texts, source_language=source, target_language=UNSUPPORTED_LANGUAGE
            )
        )


def check_tts(provider: TTSProvider, tmp_path: Path) -> None:
    for language in sorted(provider.capabilities.languages):
        out = tmp_path / language
        result = provider.synthesize(
            TTSRequest(text="A short line of narration.", language=language, output_path=out)
        )
        _same_place(out, result.path)
        assert result.duration_s > 0
    with pytest.raises(UnsupportedRequest):
        provider.synthesize(
            TTSRequest(text="x", language=UNSUPPORTED_LANGUAGE, output_path=tmp_path / "bad")
        )


def _round_up(value: int, multiple: int) -> int:
    return -(-value // multiple) * multiple


def check_keyframer(provider: KeyframerProvider, tmp_path: Path) -> None:
    caps = provider.capabilities
    # The smallest 16:9-ish size the provider declares it can draw.
    width = _round_up(max(caps.min_width, 64), caps.width_multiple)
    height = _round_up(max(caps.min_height, 36), caps.height_multiple)
    references: list[Path] = []
    for index in range(caps.max_reference_images + 1):
        references.append(tmp_path / f"reference_{index}.png")
        write_png(references[-1], 64, 64, (40 * index, 120, 200))

    def request(name: str, **changes: Any) -> KeyframeRequest:
        values: dict[str, Any] = {"width": width, "height": height, "output_path": tmp_path / name}
        return KeyframeRequest(prompt=" a misty ridge ", seed=7, **{**values, **changes})

    # No references, then every number of references up to the declared maximum.
    for count in range(caps.max_reference_images + 1):
        out = tmp_path / f"frame_{count}"
        result = provider.generate(
            request(
                out.name,
                reference_images=references[:count],
                extras={"unknown_option": True},
            )
        )
        _same_place(out, result.path)
        assert (result.width, result.height) == (width, height)
        if result.path.suffix == ".png":
            assert png_size(result.path) == (width, height)

    # Anything outside the declared capabilities is refused.
    refused: list[dict[str, Any]] = [
        {"reference_images": references},  # one more than declared
        {"width": _round_up(caps.max_width + 1, caps.width_multiple)},
        {"height": _round_up(caps.max_height + 1, caps.height_multiple)},
    ]
    if caps.width_multiple > 1:
        refused.append({"width": width + 1})
    if caps.height_multiple > 1:
        refused.append({"height": height + 1})
    if caps.min_width > caps.width_multiple:
        refused.append({"width": caps.min_width - caps.width_multiple})
    if caps.max_pixels is not None and caps.max_width * caps.max_height > caps.max_pixels:
        refused.append({"width": caps.max_width, "height": caps.max_height})
    for index, changes in enumerate(refused):
        with pytest.raises(UnsupportedRequest):
            provider.generate(request(f"refused_{index}", **changes))


def check_image_to_video(provider: ImageToVideoProvider, tmp_path: Path, image: Path) -> None:
    caps = provider.capabilities
    motion = sorted(caps.motion_types, key=lambda m: m.value)[0]
    out = tmp_path / "clip"
    result = provider.animate(
        ImageToVideoRequest(
            image=image,
            prompt="slow push in",
            motion_type=motion,
            duration_s=caps.min_seconds,
            output_path=out,
        )
    )
    _same_place(out, result.path)
    assert result.duration_s == pytest.approx(caps.min_seconds, abs=0.25)
    with pytest.raises(UnsupportedRequest):
        provider.animate(
            ImageToVideoRequest(
                image=image,
                prompt="too long",
                motion_type=MotionType.AMBIENT,
                duration_s=caps.max_seconds + 1,
                output_path=tmp_path / "long",
            )
        )


def check_music(provider: MusicProvider, tmp_path: Path) -> None:
    out = tmp_path / "music"
    result = provider.compose(MusicRequest(prompt="warm acoustic", duration_s=2.0, output_path=out))
    _same_place(out, result.path)
    assert 2.0 <= result.duration_s <= 2.25
    assert audio_duration_s(result.path) == pytest.approx(result.duration_s, abs=0.001)
    with pytest.raises(UnsupportedRequest):
        provider.compose(
            MusicRequest(
                prompt="too long",
                duration_s=provider.capabilities.max_seconds + 1,
                output_path=tmp_path / "long",
            )
        )


def check_song(provider: SongProvider, tmp_path: Path) -> None:
    language = sorted(provider.capabilities.vocal_languages)[0]
    out = tmp_path / "song"
    result = provider.sing(
        SongRequest(
            prompt="folk ballad",
            lyrics="la la la",
            language=language,
            duration_s=2.0,
            output_path=out,
        )
    )
    _same_place(out, result.path)
    assert result.duration_s == pytest.approx(2.0, abs=0.25)
    assert audio_duration_s(result.path) == pytest.approx(result.duration_s, abs=0.25)
    with pytest.raises(UnsupportedRequest):
        provider.sing(
            SongRequest(
                prompt="x",
                lyrics="x",
                language=UNSUPPORTED_LANGUAGE,
                duration_s=2.0,
                output_path=tmp_path / "bad",
            )
        )
    with pytest.raises(UnsupportedRequest):
        provider.sing(
            SongRequest(
                prompt="folk ballad",
                lyrics="la la la",
                language=language,
                duration_s=provider.capabilities.max_seconds + 1,
                output_path=tmp_path / "long",
            )
        )


#: Contract kind -> its conformance check. Image-to-video additionally receives a keyframe image.
CHECKS: dict[str, Callable[..., None]] = {
    "text": check_text,
    "translation": check_translation,
    "tts": check_tts,
    "keyframer": check_keyframer,
    "image_to_video": check_image_to_video,
    "music": check_music,
    "song": check_song,
}


def declares_identity_and_capabilities(provider: Provider[Any]) -> None:
    assert provider.name
    assert provider.capabilities is not None


def has_a_stable_fingerprint(provider: Provider[Any]) -> None:
    """The fingerprint is hashed into every artifact the provider makes (skip-unchanged, resume),
    so it must be JSON-serialisable, name the provider, and be identical across instances."""
    fingerprint = provider.fingerprint()
    assert json.loads(json.dumps(fingerprint)) == fingerprint
    assert fingerprint["name"] == provider.name
    assert type(provider)(**provider.options).fingerprint() == fingerprint
