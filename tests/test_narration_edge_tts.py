"""Seam 1 for the edge-tts narration provider: the pipeline run, driven through the CLI.

Plan-time behaviour runs offline. Anything that reaches the real Edge service carries the
``integration`` marker (the provider also runs the shared conformance suite in
``tests/conformance``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import MakeProject
from vidpipe.cli import main

EDGE = {"narration": "edge-tts"}


def test_plan_accepts_edge_tts_for_english_and_amharic(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(providers=EDGE)

    assert main(["plan", str(project), "--until", "narration"]) == 0

    assert "edge-tts" in capsys.readouterr().out
    assert not (project / "build").exists()


def test_plan_rejects_a_language_edge_tts_is_not_configured_for(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(providers=EDGE, languages=["en", "fr"])

    assert main(["plan", str(project), "--until", "narration"]) == 1

    assert "does not support language 'fr'" in capsys.readouterr().err
