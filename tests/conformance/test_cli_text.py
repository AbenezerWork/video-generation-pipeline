"""Seam 2 for the CLI text adapters: each runs the text conformance suite against a fake
executable on PATH (the real CLIs run the same suite under the ``integration`` marker through
``test_providers.py``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.cli_text_fixtures import FakeClis
from tests.conformance import suites
from vidpipe.contracts import ProviderKind, TextProvider
from vidpipe.registry import default_registry

ADAPTERS = {"gemini-cli": "gemini", "claude-cli": "claude", "codex-cli": "codex"}


def make(name: str) -> TextProvider:
    provider = default_registry().create(ProviderKind.TEXT, name)
    assert isinstance(provider, TextProvider)
    return provider


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_cli_adapter_passes_the_text_conformance_suite(
    adapter: str, fake_clis: FakeClis, tmp_path: Path
) -> None:
    fake_clis.reply(ADAPTERS[adapter], '{"word": "hello", "count": 2}')

    suites.check_text(make(adapter), tmp_path)
