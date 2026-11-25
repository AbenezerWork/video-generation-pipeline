"""Seam 1: the pipeline run, driven through the CLI entry point on a project directory."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vidpipe.cli import main
from tests.conftest import MakeProject


def run_cli(*args: str) -> int:
    return main(list(args))


def test_run_through_script_writes_a_script_artifact(make_project: MakeProject) -> None:
    project = make_project()

    code = run_cli("run", str(project), "--until", "script")

    assert code == 0
    script = json.loads((project / "build" / "script.json").read_text(encoding="utf-8"))
    assert script["title"] == "The Coffee Highlands"
    assert [line["id"] for line in script["lines"]] == [1, 2, 3]
    assert all(line["text"] for line in script["lines"])
