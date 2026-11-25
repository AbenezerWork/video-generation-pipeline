"""``vidpipe ui``: the Run view's HTTP API, driven over a real socket against fake providers.

Runs are real ``vidpipe run`` processes started from the CLI; the UI only watches them, through
the project summary, the current run state and the one SSE stream.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("starlette", reason="needs the optional ui extra")
pytest.importorskip("uvicorn", reason="needs the optional ui extra")

from tests.background_run import Writer  # noqa: E402
from tests.cli_text_fixtures import FakeClis  # noqa: E402
from tests.conftest import HAVE_FFMPEG, MakeProject  # noqa: E402
from tests.test_run_state import SAMPLE_TOTALS  # noqa: E402
from tests.ui_server import UiProcess, UiServer  # noqa: E402

STAGES = [
    "brief",
    "script",
    "translation",
    "storyboard",
    "narration",
    "fit-planning",
    "keyframes",
    "video",
    "music",
    "assembly",
]


@pytest.fixture
def project(make_project: MakeProject) -> Path:
    return make_project()


@pytest.fixture
def ui(project: Path) -> Iterator[UiServer]:
    server = UiServer(project)
    yield server
    server.stop()


def test_the_summary_lists_every_stage_with_its_provider_before_any_run(ui: UiServer) -> None:
    reply = ui.get("/api/project")

    assert reply.status == 200
    summary = reply.json()
    assert summary["name"] == "project"
    stages = {s["stage"]: s for s in summary["stages"]}
    assert list(stages) == STAGES
    assert {name: s["provider"] for name, s in stages.items()} == {
        "brief": None,
        "script": "fake-text",
        "translation": "fake-translation",
        "storyboard": "fake-text",
        "narration": "fake-tts",
        "fit-planning": None,
        "keyframes": "fake-keyframer",
        "video": "fake-i2v",
        "music": "fake-music",
        "assembly": None,
    }
    assert {name: s["phase"] for name, s in stages.items()} == {
        "brief": "words",
        "script": "words",
        "translation": "words",
        "storyboard": "words",
        "narration": "voice",
        "fit-planning": "voice",
        "keyframes": "picture",
        "video": "picture",
        "music": "sound",
        "assembly": "sound",
    }
    assert summary["run"] is None
    assert ui.get("/api/run").json() is None


def start_cli_run(project: Path, *args: str) -> subprocess.Popen[bytes]:
    """``vidpipe run`` in its own process, as a creator would start it from a terminal."""
    return subprocess.Popen(
        [sys.executable, "-m", "vidpipe", "run", str(project), *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def by_stage(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["stage"]: s for s in state["stages"]}


def test_the_event_stream_follows_a_cli_run_to_the_end(project: Path, ui: UiServer) -> None:
    stream = ui.events()
    assert stream.status == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    first = stream.next()
    assert (first.event, first.data) == ("run", None)  # no run yet

    # Assembly needs real ffmpeg; without it the run stops after the last stage that does not.
    until = [] if HAVE_FFMPEG else ["--until", "music"]
    run = start_cli_run(project, *until)
    events = list(
        stream.until(lambda e: bool(e.data) and e.data["status"] == "finished", timeout=120)
    )
    assert run.wait(timeout=60) == 0
    stream.close()

    states = [e.data for e in events]
    assert all(e.event == "run" for e in events)
    assert len({s["run_id"] for s in states}) == 1
    assert [s["seq"] for s in states] == sorted({s["seq"] for s in states})  # new records only
    assert states[0]["status"] == "running"
    assert states[0]["origin"] == "cli"
    finished = states[-1]
    expected = dict(SAMPLE_TOTALS, **({"assembly": 2} if HAVE_FFMPEG else {}))
    assert {
        name: (s["status"], s["done"], s["total"]) for name, s in by_stage(finished).items()
    } == {name: ("done", n, n) for name, n in expected.items()}
    # The stream showed stages while they ran, with providers, not only the end result.
    seen_running = {
        s["current_stage"] for s in states if s["status"] == "running" and s["current_stage"]
    }
    assert len(seen_running) >= 2
    assert by_stage(finished)["video"]["provider"] == "fake-i2v"
    assert ui.get("/api/run").json() == finished


def test_the_event_stream_shows_the_stage_in_progress_and_its_failure(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    project = make_project(providers={"script": "gemini-cli"})
    ui = UiServer(project)
    writer = Writer(project, fake_clis)  # a CLI run held inside the script stage
    try:
        stream = ui.events()
        running = stream.next().data
        assert (running["status"], running["current_stage"]) == ("running", "script")
        stages = by_stage(running)
        assert (stages["brief"]["status"], stages["script"]["status"]) == ("done", "running")
        assert stages["script"]["provider"] == "gemini-cli"
        assert ui.get("/api/project").json()["run"] == running

        writer.finish()  # the CLI gives up: the run fails in the script stage
        events = list(stream.until(lambda e: e.data["status"] == "failed"))
        failed = events[-1].data
        assert failed["error"]["stage"] == "script"
        assert by_stage(failed)["script"]["status"] == "failed"
        stream.close()
    finally:
        writer.finish()
        ui.stop()


def test_a_run_whose_process_died_shows_as_failed(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    project = make_project(providers={"script": "gemini-cli"})
    ui = UiServer(project)
    writer = Writer(project, fake_clis)
    try:
        stream = ui.events()
        assert stream.next().data["status"] == "running"

        writer.kill()  # the run state file still says running; its process is gone

        failed = stream.next().data
        assert failed["status"] == "failed"
        assert "ended unexpectedly" in failed["error"]["message"]
        stream.close()
    finally:
        writer.finish()
        ui.stop()


# ---------------------------------------------------------------- who may connect


def test_on_this_machine_no_token_is_needed_but_other_host_names_are_refused(
    project: Path,
) -> None:
    ui = UiProcess(project)
    try:
        assert not any("token" in line for line in ui.output)
        assert f"http://127.0.0.1:{ui.port}/" in "\n".join(ui.output)
        assert ui.get("/api/project").status == 200
        assert ui.get("/").status == 200
        # A web page rebinding its own domain name to 127.0.0.1 gets nothing.
        assert ui.get("/api/project", {"Host": f"attacker.example:{ui.port}"}).status == 400
    finally:
        ui.stop()


def test_opened_to_the_network_every_request_needs_the_printed_token(project: Path) -> None:
    ui = UiProcess(project, "--host", "0.0.0.0")
    try:
        links = [m for line in ui.output for m in re.findall(r"http://\S+\?token=\S+", line)]
        assert links, ui.output
        token = links[0].split("?token=")[1]
        assert len(token) >= 32

        for path in ("/", "/api/project", "/api/run", "/static/console.css"):
            assert ui.get(path).status == 401, path
        assert ui.events().status == 401
        assert ui.get("/api/run", {"Cookie": "vidpipe_token=guess"}).status == 401
        assert ui.get("/?token=guess").status == 401

        # Opening the printed link swaps the token in the address for a cookie...
        opened = ui.get(f"/?token={token}")
        assert opened.status == 303
        assert opened.headers["location"] == "/"
        cookie = opened.headers["set-cookie"]
        assert cookie.startswith(f"vidpipe_token={token};")
        assert "httponly" in cookie.lower()
        # ...which the page, its assets, the API and the event stream all accept.
        with_cookie = {"Cookie": f"vidpipe_token={token}"}
        for path in ("/", "/api/project", "/static/console.css"):
            assert ui.get(path, with_cookie).status == 200, path
        stream = ui.events(headers=with_cookie)
        assert (stream.status, stream.next().event) == (200, "run")
        stream.close()
        # Scripts and tools can send it as a bearer token instead.
        assert ui.get("/api/run", {"Authorization": f"Bearer {token}"}).status == 200
    finally:
        ui.stop()
