"""Stop and stop now, seen from outside the run: ``vidpipe stop``, run state, ledger, ComfyUI.

The run is a real ``vidpipe run`` (in a thread here, or in another process through the fake CLI's
``hang``), drawing keyframes on the fake ComfyUI server; the stop request comes from ``vidpipe
stop``, which does not take the project lock the run holds.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.background_run import Writer
from tests.cli_text_fixtures import FakeClis
from tests.conftest import MakeProject
from tests.fake_comfyui import FakeComfyUI
from tests.test_keyframes_bible import comfy_project, ledger
from tests.test_one_writer import SCRIPT
from tests.test_run_state import read_state, stages
from vidpipe.cli import main
from vidpipe.runstate import read_run_state

EXIT_STOPPED = 4
KEYFRAMES = ["keyframes/shot_01", "keyframes/shot_02", "keyframes/shot_03"]


def wait_for(condition: Callable[[], bool], what: str, timeout_s: float = 30) -> None:
    deadline = time.monotonic() + timeout_s
    while not condition():
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        time.sleep(0.02)


class BackgroundRun:
    """``vidpipe run <project> --until keyframes`` in a thread; ``code`` is its exit code."""

    def __init__(self, project: Path) -> None:
        self.code: int | None = None
        self.thread = threading.Thread(target=self._run, args=(project,), daemon=True)
        self.thread.start()

    def _run(self, project: Path) -> None:
        self.code = main(["run", str(project), "--until", "keyframes"])

    def join(self) -> int | None:
        self.thread.join(timeout=60)
        assert not self.thread.is_alive(), "the run did not end"
        return self.code


def stopping(project: Path) -> bool:
    # Polled while the run rewrites the file: the public reader rides out a rename on Windows.
    state = read_run_state(project)
    return state is not None and state.status == "stopping"


def keyframe_records(project: Path) -> list[str]:
    return sorted(key for key in ledger(project) if key.startswith("keyframes/"))


def drawing_shot_2(comfy: FakeComfyUI) -> bool:
    return len(comfy.jobs) == 2 and comfy.jobs[1].polls > 0


def test_a_stop_ends_the_run_after_the_keyframe_in_progress(
    make_project: MakeProject, comfy: FakeComfyUI
) -> None:
    comfy.script("success", "hold")  # shot 2's job runs until released
    project = comfy_project(make_project, comfy)
    run = BackgroundRun(project)
    wait_for(lambda: drawing_shot_2(comfy), "shot 2 to be drawing")

    assert main(["stop", str(project)]) == 0

    wait_for(lambda: stopping(project), "the run to see the stop")
    assert comfy.running == [comfy.jobs[1]]  # shot 2 is still being drawn
    comfy.release()
    assert run.join() == EXIT_STOPPED

    state = read_state(project)
    assert (state["status"], state["current_stage"], state["error"]) == ("stopped", None, None)
    keyframes = stages(state)["keyframes"]
    assert (keyframes["status"], keyframes["done"], keyframes["total"]) == ("stopped", 2, 3)
    assert keyframe_records(project) == KEYFRAMES[:2]  # shot 2 finished and was kept
    assert len(comfy.jobs) == 2  # shot 3 was never started
    assert comfy.interrupted == []


def test_a_resumed_run_reuses_everything_finished_before_the_stop(
    make_project: MakeProject, comfy: FakeComfyUI
) -> None:
    comfy.script("success", "hold")
    project = comfy_project(make_project, comfy)
    run = BackgroundRun(project)
    wait_for(lambda: drawing_shot_2(comfy), "shot 2 to be drawing")
    assert main(["stop", str(project)]) == 0
    wait_for(lambda: stopping(project), "the run to see the stop")
    comfy.release()
    assert run.join() == EXIT_STOPPED
    records = ledger(project)

    assert main(["run", str(project), "--until", "keyframes"]) == 0

    state = read_state(project)
    assert state["status"] == "finished"
    by_stage = stages(state)
    assert all(s["status"] == "reused" for name, s in by_stage.items() if name != "keyframes")
    keyframes = by_stage["keyframes"]
    assert (keyframes["generated"], keyframes["reused"]) == (1, 2)
    assert len(comfy.jobs) == 3  # only shot 3 was drawn
    after = ledger(project)
    assert {key: after[key] for key in records} == records  # finished work untouched


def test_stop_now_cancels_the_comfyui_job_and_discards_only_that_keyframe(
    make_project: MakeProject, comfy: FakeComfyUI
) -> None:
    comfy.script("success", "hang")  # shot 2's job would never finish on its own
    project = comfy_project(make_project, comfy)
    run = BackgroundRun(project)
    wait_for(lambda: drawing_shot_2(comfy), "shot 2 to be drawing")

    assert main(["stop", str(project), "--now"]) == 0

    assert run.join() == EXIT_STOPPED
    shot_2 = comfy.jobs[1].prompt_id
    assert comfy.interrupted == [shot_2]  # that job, nothing else
    assert comfy.running == []
    state = read_state(project)
    assert (state["status"], state["error"]) == ("stopped", None)
    keyframes = stages(state)["keyframes"]
    assert (keyframes["status"], keyframes["done"]) == ("stopped", 1)
    assert keyframe_records(project) == KEYFRAMES[:1]
    assert not list((project / "build" / "keyframes").glob("shot_02*"))
    # Stopping is not failing: the cancelled job is not retried with a new seed.
    assert len(comfy.jobs) == 2

    assert main(["run", str(project), "--until", "keyframes"]) == 0
    keyframes = stages(read_state(project))["keyframes"]
    assert (keyframes["generated"], keyframes["reused"]) == (2, 1)


def test_stop_now_after_a_stop_cancels_the_job_the_stop_was_waiting_for(
    make_project: MakeProject, comfy: FakeComfyUI
) -> None:
    comfy.script("success", "hang")
    project = comfy_project(make_project, comfy)
    run = BackgroundRun(project)
    wait_for(lambda: drawing_shot_2(comfy), "shot 2 to be drawing")
    assert main(["stop", str(project)]) == 0
    wait_for(lambda: stopping(project), "the run to see the stop")

    assert main(["stop", str(project), "--now"]) == 0

    assert run.join() == EXIT_STOPPED
    assert comfy.interrupted == [comfy.jobs[1].prompt_id]
    assert keyframe_records(project) == KEYFRAMES[:1]


def test_a_stop_reaches_a_run_in_another_process_holding_the_lock(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    project = make_project(providers={"script": "gemini-cli"})
    # `vidpipe run --until script`, blocked in the script stage's CLI until released.
    writer = Writer(project, fake_clis, then=SCRIPT)
    try:
        assert main(["stop", str(project)]) == 0
        wait_for(lambda: stopping(project), "the run to see the stop")
    finally:
        writer.finish()

    assert writer.process.returncode == EXIT_STOPPED
    state = read_state(project)
    assert state["status"] == "stopped"
    assert stages(state)["script"]["done"] == 1  # the script in progress was finished and kept
    assert "script" in ledger(project)


def test_stop_without_a_run_in_progress_is_refused(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project()
    assert main(["run", str(project), "--until", "script"]) == 0
    capsys.readouterr()

    assert main(["stop", str(project)]) == 1

    assert "no run in progress" in capsys.readouterr().err
    assert read_state(project)["status"] == "finished"
    # A later run is not stopped by a request nobody could act on.
    assert main(["run", str(project), "--until", "script"]) == 0
