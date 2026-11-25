"""Seam 2: every provider declares what its work costs, and tells the planner how long speech runs.

``vidpipe plan`` estimates GPU time (local providers) and dollars (hosted ones) from these
declarations before anything is generated, so they are part of the provider contract. The checks
read only the public declaration, so they run unchanged against real providers (``integration``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from vidpipe.contracts import (
    CostModel,
    CostUnit,
    Provider,
    ProviderKind,
    TTSProvider,
    TTSRequest,
)
from vidpipe.registry import default_registry


def _params(kind: ProviderKind | None = None) -> list[pytest.ParameterSet]:
    return [
        pytest.param(
            cls,
            id=f"{cls.kind.value}:{cls.name}",
            marks=[] if cls.fake else [pytest.mark.integration],
        )
        for cls in default_registry().classes(kind)
    ]


@pytest.mark.parametrize("provider_class", _params())
def test_provider_declares_a_consistent_cost_model(provider_class: type[Provider[Any]]) -> None:
    provider = provider_class()
    cost = provider.cost

    assert isinstance(cost, CostModel)
    assert cost.unit in set(CostUnit)
    # GPU minutes are for local providers, dollars for hosted ones; never both, never negative.
    assert cost.gpu_minutes >= 0
    assert cost.dollars >= 0
    assert not (cost.gpu_minutes > 0 and cost.dollars > 0)
    # A provider that runs on the local GPU must say how much GPU time that takes.
    assert provider.uses_gpu == (cost.gpu_minutes > 0)


def test_the_planner_can_price_gpu_and_hosted_work_from_declared_costs() -> None:
    registry = default_registry()
    gpu = registry.create(ProviderKind.IMAGE_TO_VIDEO, "fake-i2v")
    hosted = registry.create(ProviderKind.IMAGE_TO_VIDEO, "fake-i2v-hosted")

    local_cost = gpu.cost.estimate(calls=2, output_seconds=10.0)
    hosted_cost = hosted.cost.estimate(calls=2, output_seconds=10.0)

    # fake-i2v declares 0.5 GPU minutes per output second; fake-i2v-hosted $0.05 per second.
    assert local_cost.gpu_minutes == pytest.approx(5.0)
    assert local_cost.dollars == 0
    assert hosted_cost.dollars == pytest.approx(0.5)
    assert hosted_cost.gpu_minutes == 0


def test_a_per_call_cost_ignores_output_length() -> None:
    keyframer = default_registry().create(ProviderKind.KEYFRAMER, "fake-keyframer")

    cost = keyframer.cost.estimate(calls=3, output_seconds=0.0)

    # fake-keyframer declares 0.4 GPU minutes per image.
    assert cost.gpu_minutes == pytest.approx(1.2)


@pytest.mark.parametrize("provider_class", _params(ProviderKind.TTS))
def test_tts_declared_speech_rate_matches_what_it_actually_speaks(
    provider_class: type[Provider[Any]], tmp_path: Path
) -> None:
    """Dry-run narration estimates come from the declared rate, so it must be about right."""
    provider = provider_class()
    assert isinstance(provider, TTSProvider)
    text = "High in the Ethiopian highlands, a young goat herder watched his flock of goats."
    result = provider.synthesize(TTSRequest(text=text, language="en", output_path=tmp_path / "t"))

    estimate = provider.capabilities.seconds_per_char * len(text)

    assert estimate / 2 <= result.duration_s <= estimate * 2
