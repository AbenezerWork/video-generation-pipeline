"""Seam 2: ``comfyui-keyframer`` passes the keyframer suite against the fake ComfyUI server.

The same suite runs against a real ComfyUI under the ``integration`` marker (see
``test_providers.py``, which collects every registered non-fake provider).
"""

from __future__ import annotations

from pathlib import Path

from tests.conformance import suites
from tests.fake_comfyui import FakeComfyUI
from vidpipe.contracts import KeyframeRequest
from vidpipe.providers.comfy_keyframer import ComfyKeyframer


def keyframer(comfy: FakeComfyUI) -> ComfyKeyframer:
    return ComfyKeyframer(url=comfy.url, poll_s=0.01)


def test_comfyui_keyframer_passes_the_keyframer_suite(comfy: FakeComfyUI, tmp_path: Path) -> None:
    provider = keyframer(comfy)

    suites.declares_identity_and_capabilities(provider)
    suites.has_a_stable_fingerprint(provider)
    suites.check_keyframer(provider, tmp_path)

    assert comfy.running == []  # nothing is left in ComfyUI's queue


def test_comfyui_keyframer_declares_the_spikes_capabilities_and_cost() -> None:
    provider = ComfyKeyframer()

    caps = provider.capabilities
    assert caps.max_reference_images == 2
    assert (caps.width_multiple, caps.height_multiple) == (16, 16)
    assert caps.max_pixels == 1280 * 720
    # ADR 0001: about 6.5 s of GPU time per 832x480 keyframe with one reference.
    assert provider.uses_gpu
    assert provider.cost.estimate(calls=10).gpu_minutes == 10 * 0.11


def test_whitespace_around_a_prompt_does_not_change_the_image(
    comfy: FakeComfyUI, tmp_path: Path
) -> None:
    """ComfyUI draws a different image for trailing spaces, so prompts are stripped (ADR 0001)."""
    provider = keyframer(comfy)

    def draw(prompt: str, name: str) -> bytes:
        result = provider.generate(
            KeyframeRequest(
                prompt=prompt, width=640, height=352, seed=3, output_path=tmp_path / name
            )
        )
        data = result.path.read_bytes()
        return data[data.index(b"IDAT") :]  # the pixels, without the metadata

    assert draw("a ridge at dawn", "a") == draw("  a ridge at dawn \n", "b")
    assert draw("a ridge at dawn", "a") != draw("a ridge at dusk", "c")
