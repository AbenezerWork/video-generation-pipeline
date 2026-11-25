"""Seam 2 for translation by text providers: a ``TextTranslator`` over each CLI adapter runs the
shared translation conformance suite (fake executables in CI; the real CLIs, when installed and
logged in, under the ``integration`` marker)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.cli_text_fixtures import FakeClis
from tests.conformance import suites
from vidpipe.contracts import ProviderKind, TextProvider
from vidpipe.registry import default_registry
from vidpipe.translate import TextTranslator

ADAPTERS = {"gemini-cli": "gemini", "claude-cli": "claude", "codex-cli": "codex"}

#: What a CLI answers when asked to translate suites.check_translation's two lines into Amharic.
AMHARIC_REPLY = json.dumps(
    {"lines": [{"id": 1, "text": "ሰላም ለእናንተ።"}, {"id": 2, "text": "እንደምን አደራችሁ።"}]},
    ensure_ascii=False,
)


def translator(*names: str) -> TextTranslator:
    providers = [default_registry().create(ProviderKind.TEXT, name) for name in names]
    return TextTranslator([p for p in providers if isinstance(p, TextProvider)])


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_a_translator_over_each_cli_adapter_passes_the_translation_suite(
    adapter: str, fake_clis: FakeClis, tmp_path: Path
) -> None:
    fake_clis.reply(ADAPTERS[adapter], AMHARIC_REPLY)

    suites.check_translation(translator(adapter), tmp_path)

    # The unsupported-language half of the suite is rejected before any CLI is run.
    assert len(fake_clis.calls(ADAPTERS[adapter])) == 1


def test_a_translator_over_a_chain_passes_the_translation_suite_after_a_fallback(
    fake_clis: FakeClis, tmp_path: Path
) -> None:
    fake_clis.fail("gemini", "429 RESOURCE_EXHAUSTED: quota exceeded")
    fake_clis.reply("claude", AMHARIC_REPLY)

    suites.check_translation(translator("gemini-cli", "claude-cli"), tmp_path)


@pytest.mark.integration
@pytest.mark.parametrize("adapter", ADAPTERS)
def test_real_cli_translator_passes_the_translation_suite(adapter: str, tmp_path: Path) -> None:
    if shutil.which(ADAPTERS[adapter]) is None:
        pytest.skip(f"{ADAPTERS[adapter]} is not installed")

    suites.check_translation(translator(adapter), tmp_path)
