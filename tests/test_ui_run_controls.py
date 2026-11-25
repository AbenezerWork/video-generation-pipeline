"""``vidpipe ui``: starting, stopping and resuming runs through the UI's HTTP API.

Runs the UI starts are real ``vidpipe run`` processes, detached from the server; the tests watch
them only as the page does, through the SSE stream, ``/api/run`` and the files they write.
"""

from __future__ import annotations

import contextlib
import os
import signal
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("starlette", reason="needs the optional ui extra")
pytest.importorskip("uvicorn", reason="needs the optional ui extra")

from tests.conftest import HAVE_FFMPEG, MakeProject  # noqa: E402
from tests.fake_comfyui import FakeComfyUI  # noqa: E402
from tests.test_keyframes_bible import comfy_project  # noqa: E402
from tests.test_run_state import SAMPLE_TOTALS  # noqa: E402
from tests.test_stop import BackgroundRun, drawing_shot_2, keyframe_records  # noqa: E402
from tests.ui_server import UiClient, UiProcess, UiServer  # noqa: E402
from vidpipe.runstate import read_run_state  # noqa: E402


def by_stage(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["stage"]: s for s in state["stages"]}


def wait_for(condition: Callable[[], bool], what: str, timeout_s: float = 60) -> None:
    deadline = time.monotonic() + timeout_s
    while not condition():
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        time.sleep(0.05)


def end_run(project: Path) -> None:
    """Make sure no run this test started outlives it (they are detached from the server)."""
    state = read_run_state(project)
    if state is None or state.status not in ("running", "stopping"):
        return
    with contextlib.suppress(OSError):
        os.kill(state.pid, signal.SIGTERM)

    def ended() -> bool:
        current = read_run_state(project)
        return current is None or current.status not in ("running", "stopping")

    wait_for(ended, "the run to end")


@pytest.fixture
def project(make_project: MakeProject) -> Iterator[Path]:
    root = make_project()
    yield root
    end_run(root)


@pytest.fixture
def ui(project: Path) -> Iterator[UiServer]:
    server = UiServer(project)
    yield server
    server.stop()


def finished(event: Any) -> bool:
    return bool(event.data) and event.data["status"] in ("finished", "failed", "stopped")


def test_a_run_started_from_the_ui_runs_to_the_end_like_a_cli_run(
    project: Path, ui: UiServer
) -> None:
    stream = ui.events()
    assert stream.next().data is None

    until = None if HAVE_FFMPEG else "music"
    reply = ui.post("/api/run/start", {"until": until})

    assert reply.status == 202
    started = reply.json()
    events = list(stream.until(finished, timeout=180))
    stream.close()
    states = [e.data for e in events if e.data]
    assert {s["run_id"] for s in states} == {started["run_id"]}
    end = states[-1]
    assert (end["status"], end["origin"], end["error"]) == ("finished", "ui", None)
    expected = dict(SAMPLE_TOTALS, **({"assembly": 2} if HAVE_FFMPEG else {}))
    assert {name: (s["status"], s["done"], s["total"]) for name, s in by_stage(end).items()} == {
        name: ("done", n, n) for name, n in expected.items()
    }
    assert ui.get("/api/run").json() == end
    assert started["pid"] == end["pid"]
    # What the run printed is kept in the build folder.
    log = project / started["log"]
    assert log == project / "build" / "logs" / f"ui-run-{end['run_id']}.log"
    wait_for(
        lambda: any(line.startswith("music ") for line in ui.get("/api/logs").json()["lines"]),
        "the CLI report",
        5,
    )
    assert ui.get("/api/logs").json()["path"] == started["log"]


def wait_for_status(ui: UiClient, status: str) -> dict[str, Any]:
    with contextlib.closing(ui.events()) as stream:
        return list(stream.until(lambda e: bool(e.data) and e.data["status"] == status))[-1].data


def test_start_through_script_stops_there(ui: UiServer) -> None:
    assert ui.post("/api/run/start", {"until": "script"}).status == 202

    end = wait_for_status(ui, "finished")
    assert end["until"] == "script"
    assert list(by_stage(end)) == ["brief", "script"]
    assert by_stage(end)["script"]["status"] == "done"


def test_a_detached_run_pauses_at_a_gate_without_asking_for_input(
    make_project: MakeProject,
) -> None:
    project = make_project(gates=["script"])
    ui = UiServer(project)
    try:
        assert ui.post("/api/run/start", {"until": "storyboard"}).status == 202

        end = wait_for_status(ui, "paused")
        assert end["paused_at"] == "script"
        assert by_stage(end)["translation"]["status"] == "waiting"
    finally:
        ui.stop()
        end_run(project)


def test_a_ui_run_survives_client_and_server_exit_and_can_resume(
    make_project: MakeProject, comfy: FakeComfyUI
) -> None:
    comfy.script("success", "hold")
    project = comfy_project(make_project, comfy)
    ui = UiProcess(project)
    try:
        with contextlib.closing(ui.events()) as stream:
            assert stream.next().data is None
            reply = ui.post("/api/run/start", {"until": "keyframes"})
            assert reply.status == 202
            run_id = reply.json()["run_id"]
            wait_for(lambda: drawing_shot_2(comfy), "shot 2 to be drawing")
        assert ui.get("/api/run").json()["run_id"] == run_id  # a new client sees the same run
    finally:
        ui.stop()

    reopened = UiServer(project)
    try:
        state = reopened.get("/api/run").json()
        assert (state["status"], state["run_id"]) == ("running", run_id)
        refusal = reopened.post("/api/run/start")
        assert refusal.status == 409
        assert "a run is in progress" in refusal.json()["error"]
        assert "started from the UI" in refusal.json()["holder"]
        assert reopened.post("/api/run/stop").status == 202
        wait_for_status(reopened, "stopping")
        assert comfy.running == [comfy.jobs[1]]
        comfy.release()
        stopped = wait_for_status(reopened, "stopped")
        assert by_stage(stopped)["keyframes"]["done"] == 2
        assert comfy.interrupted == []
        assert keyframe_records(project) == ["keyframes/shot_01", "keyframes/shot_02"]

        assert reopened.post("/api/run/start", {"until": stopped["until"]}).status == 202
        finished_run = wait_for_status(reopened, "finished")
        keyframes = by_stage(finished_run)["keyframes"]
        assert (keyframes["generated"], keyframes["reused"]) == (1, 2)
    finally:
        reopened.stop()
        end_run(project)


def test_ui_stop_now_escalates_a_stop_on_a_cli_run(
    make_project: MakeProject, comfy: FakeComfyUI
) -> None:
    comfy.script("success", "hang")
    project = comfy_project(make_project, comfy)
    ui = UiServer(project)
    run = BackgroundRun(project)
    try:
        wait_for(lambda: drawing_shot_2(comfy), "shot 2 to be drawing")
        refusal = ui.post("/api/run/start")
        assert refusal.status == 409
        assert "started from the CLI" in refusal.json()["holder"]

        assert ui.post("/api/run/stop-now", {"run_id": "an-earlier-run"}).status == 409
        run_id = ui.get("/api/run").json()["run_id"]
        assert ui.post("/api/run/stop", {"run_id": run_id}).status == 202
        wait_for_status(ui, "stopping")
        assert ui.post("/api/run/stop-now", {"run_id": run_id}).status == 202
        assert run.join() == 4
        state = ui.get("/api/run").json()
        assert (state["origin"], state["status"], state["error"]) == ("cli", "stopped", None)
        assert comfy.interrupted == [comfy.jobs[1].prompt_id]
        assert keyframe_records(project) == ["keyframes/shot_01"]
    finally:
        ui.post("/api/run/stop-now")
        ui.stop()
        run.join()


def test_foreign_origins_and_invalid_stages_cannot_start_runs(ui: UiServer) -> None:
    assert ui.post("/api/run/start", headers={"Origin": "http://example.com"}).status == 403
    assert ui.post("/api/run/start", headers={"Origin": "http://["}).status == 403
    assert ui.post("/api/run/start", {"until": ["script"]}).status == 400
    assert ui.get("/api/run").json() is None
    assert ui.post("/api/run/stop").status == 409
