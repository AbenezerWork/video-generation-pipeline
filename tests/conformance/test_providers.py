"""Run the conformance suite for every registered provider.

Fakes run by default. Any non-fake provider (real ComfyUI, CLI, edge-tts, ...) registered in the
default registry is collected too, but carries the ``integration`` marker, so it only runs with
``pytest -m integration``. To cover a new provider, just register it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.conformance import suites
from vidpipe.contracts import Provider, ProviderKind
from vidpipe.providers._media import write_png
from vidpipe.registry import default_registry


def _params() -> list[pytest.ParameterSet]:
    items: list[pytest.ParameterSet] = []
    for cls in default_registry().classes():
        marks = [] if cls.fake else [pytest.mark.integration]
        if cls.name == "comfyui-i2v":
            marks.append(pytest.mark.needs_ffmpeg)
        items.append(pytest.param(cls, id=f"{cls.kind.value}:{cls.name}", marks=marks))
    return items


@pytest.mark.parametrize("provider_class", _params())
def test_provider_passes_its_contract_suite(
    provider_class: type[Provider[Any]], tmp_path: Path
) -> None:
    provider = provider_class()
    suites.declares_identity_and_capabilities(provider)
    suites.has_a_stable_fingerprint(provider)
    check = suites.CHECKS[provider.kind.value]
    try:
        if provider.kind is ProviderKind.IMAGE_TO_VIDEO:
            image = tmp_path / "keyframe.png"
            write_png(image, 64, 36, (10, 20, 30))
            check(provider, tmp_path, image)
        else:
            check(provider, tmp_path)
    finally:
        provider.release()  # a real GPU provider gives its memory back


def test_every_contract_has_a_fake_provider() -> None:
    registry = default_registry()
    for kind in ProviderKind:
        assert any(c.fake for c in registry.classes(kind)), kind
