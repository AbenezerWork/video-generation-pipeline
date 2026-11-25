"""Seam 1 (gates, --auto and per-shot re-roll): the pipeline run through the CLI entry point.

A pause is observed as an exit code and message from ``vidpipe run``; an approval is given with
``vidpipe approve`` or ``--approve`` (or an interactive answer when a terminal is attached).
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import MakeProject
from tests.recording import Recorder, RecordingRegistry
from vidpipe import pipeline
from vidpipe.cli import main
from vidpipe.contracts import ProviderKind

PAUSED = 3


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def stages_reported(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return [
        line.split()[0]
        for line in capsys.readouterr().out.splitlines()
        if line.split() and line.split()[0] in pipeline.STAGE_NAMES
    ]


def test_run_pauses_after_script_by_default_and_resumes_once_approved(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(gates=None)

    assert main(["run", str(project), "--until", "music"]) == PAUSED

    out = capsys.readouterr().out
    assert "script" in out and "approve" in out
    assert (project / "build" / "script.json").is_file()
    assert not (project / "build" / "storyboard.json").exists()

    assert main(["approve", str(project), "script"]) == 0
    assert main(["run", str(project), "--until", "music"]) == PAUSED  # now stops after storyboard
    assert (project / "build" / "storyboard.json").is_file()
    assert not (project / "build" / "keyframes.json").exists()
