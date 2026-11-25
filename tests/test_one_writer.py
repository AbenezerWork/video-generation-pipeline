"""Seam 1 for the one-writer lock: the CLI on a project while another process's run is in progress.

The run in progress is a real ``vidpipe run`` in a separate process, held mid-script by a fake CLI
that blocks (``FakeClis.hang``). Observed only through exit codes, what the CLI prints and the
artifacts on disk.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.cli_text_fixtures import FakeClis
from tests.conftest import MakeProject
from vidpipe.cli import main

SCRIPT = json.dumps({"lines": ["Goats danced on the misty ridge.", "The first cup was born."]})


class Writer:
    """A ``vidpipe run`` in its own process, blocked inside the script stage's CLI."""

    def __init__(self, project: Path, fake_clis: FakeClis) -> None:
        self.fake_clis = fake_clis
        fake_clis.hang("gemini")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "vidpipe", "run", str(project), "--until", "script"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 30
        while not fake_clis.hanging:
            assert self.process.poll() is None, "the writer exited before reaching the script"
            assert time.monotonic() < deadline, "the writer never reached the script stage"
            time.sleep(0.05)

    def kill(self) -> None:
        self.process.kill()
        self.process.wait()

    def finish(self) -> None:
        self.fake_clis.release()
        if self.process.poll() is None:
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.kill()


@pytest.fixture
def project(make_project: MakeProject) -> Path:
    return make_project(providers={"script": "gemini-cli"})


@pytest.fixture
def writer(project: Path, fake_clis: FakeClis) -> Iterator[Writer]:
    running = Writer(project, fake_clis)
    yield running
    running.finish()


def test_a_second_run_is_refused_while_a_run_is_in_progress(
    project: Path, writer: Writer, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()

    assert main(["run", str(project), "--until", "script"]) != 0

    assert "a run is in progress" in capsys.readouterr().err
    assert len(writer.fake_clis.calls("gemini")) == 1  # the second run asked the CLI nothing
    assert not (project / "build" / "script.json").exists()
