"""The run state, seen from outside the run: ``build/run_state.json`` and the lock refusal.

A run in progress is a real ``vidpipe run`` in another process, held in the script stage by the fake
CLI's ``hang`` reply; paused, failed and finished runs are read after they end.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from tests.background_run import Writer
from tests.cli_text_fixtures import FakeClis
from tests.conftest import MakeProject, nothing_generated
from vidpipe.cli import main
from vidpipe.gates import EXIT_PAUSED
from vidpipe.runstate import ORIGIN_ENV, config_hash, read_run_state

STATE = Path("build") / "run_state.json"


def read_state(project: Path) -> dict[str, Any]:
    return json.loads((project / STATE).read_text(encoding="utf-8"))


def stages(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["stage"]: s for s in state["stages"]}


@pytest.fixture
def project(make_project: MakeProject) -> Path:
    return make_project(providers={"script": "gemini-cli"})


@pytest.fixture
def writer(project: Path, fake_clis: FakeClis) -> Iterator[Writer]:
    running = Writer(project, fake_clis)
    yield running
    running.finish()


def test_a_run_in_progress_publishes_where_it_is(project: Path, writer: Writer) -> None:
    state = read_state(project)

    assert state["status"] == "running"
    assert state["origin"] == "cli"
    # The run's own process (on Windows the venv's python.exe launches it as a child).
    assert state["pid"] != os.getpid()
    assert writer.process.poll() is None
    assert state["run_id"]
    assert datetime.fromisoformat(state["started_at"]).tzinfo is not None
    assert state["current_stage"] == "script"
    assert state["error"] is None
    by_stage = stages(state)
    assert list(by_stage) == ["brief", "script"]  # the stages this run covers (--until script)
    assert by_stage["brief"] | {"started_at": None, "finished_at": None} == {
        "stage": "brief",
        "provider": None,
        "status": "done",
        "done": 1,
        "total": 1,
        "generated": 1,
        "reused": 0,
        "started_at": None,
        "finished_at": None,
    }
    script = by_stage["script"]
    assert (script["status"], script["provider"]) == ("running", "gemini-cli")
    assert (script["done"], script["total"], script["generated"], script["reused"]) == (0, 1, 0, 0)


# The sample project: 3 shots, English and Amharic, shared visuals with one clip per shot.
SAMPLE_TOTALS = {
    "brief": 1,
    "script": 1,
    "translation": 1,  # am (the fake translator has no back-translation review)
    "storyboard": 1,
    "narration": 6,  # 3 shots x 2 languages
    "fit-planning": 1,
    "keyframes": 3,
    "video": 3,
    "music": 1,
}


def test_a_finished_run_records_every_stage_and_its_counts(make_project: MakeProject) -> None:
    project = make_project()

    assert main(["run", str(project), "--until", "music"]) == 0

    state = read_state(project)
    assert (state["status"], state["current_stage"], state["error"]) == ("finished", None, None)
    assert state["until"] == "music"
    assert state["finished_at"] is not None
    counts = {
        name: (s["status"], s["done"], s["total"], s["generated"], s["reused"])
        for name, s in stages(state).items()
    }
    assert counts == {name: ("done", n, n, n, 0) for name, n in SAMPLE_TOTALS.items()}


def test_a_run_that_reuses_everything_says_so_per_stage(make_project: MakeProject) -> None:
    project = make_project()
    assert main(["run", str(project), "--until", "music"]) == 0
    first = read_state(project)["run_id"]

    assert main(["run", str(project), "--until", "music"]) == 0

    state = read_state(project)
    assert state["run_id"] != first
    counts = {
        name: (s["status"], s["done"], s["total"], s["generated"], s["reused"])
        for name, s in stages(state).items()
    }
    assert counts == {name: ("reused", n, n, 0, n) for name, n in SAMPLE_TOTALS.items()}


def test_a_run_paused_at_a_gate_says_which_and_what_is_left(make_project: MakeProject) -> None:
    project = make_project(gates=["storyboard"])

    assert main(["run", str(project), "--until", "music"]) == EXIT_PAUSED

    state = read_state(project)
    assert (state["status"], state["paused_at"], state["current_stage"]) == (
        "paused",
        "storyboard",
        None,
    )
    by_stage = stages(state)
    assert by_stage["storyboard"]["status"] == "paused"
    assert [by_stage[s]["status"] for s in ("brief", "script", "translation")] == ["done"] * 3
    later = ["narration", "fit-planning", "keyframes", "video", "music"]
    assert {by_stage[s]["status"] for s in later} == {"waiting"}
    # What the storyboard settled is already counted: 3 shots in 2 languages, 3 keyframes.
    assert by_stage["narration"]["total"] == 6
    assert by_stage["keyframes"]["total"] == 3
    assert by_stage["video"]["total"] is None  # needs the fit plan, not made yet


def test_a_run_that_fails_in_a_stage_names_the_stage_and_the_error(
    project: Path, fake_clis: FakeClis
) -> None:
    fake_clis.fail("gemini", "quota exhausted for today")

    assert main(["run", str(project), "--until", "storyboard"]) == 1

    state = read_state(project)
    assert (state["status"], state["current_stage"]) == ("failed", None)
    assert state["error"]["stage"] == "script"
    assert "quota exhausted for today" in state["error"]["message"]
    by_stage = stages(state)
    assert [by_stage[s]["status"] for s in by_stage] == ["done", "failed", "waiting", "waiting"]


def test_a_run_refused_at_plan_time_fails_before_any_stage(make_project: MakeProject) -> None:
    project = make_project(providers={"narration": "fake-tts-en-only"})

    assert main(["run", str(project), "--until", "music"]) == 1

    state = read_state(project)
    assert state["status"] == "failed"
    assert state["error"]["stage"] is None
    assert "does not support language 'am'" in state["error"]["message"]
    assert {s["status"] for s in state["stages"]} == {"waiting"}
    assert nothing_generated(project)  # the run state is not an artifact


def test_the_run_state_keeps_the_config_hash_the_run_started_with(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    project = make_project(providers={"script": "gemini-cli"})
    started_with = config_hash(project)
    config = project / "vidpipe.yaml"
    commented = "# a comment is not a change\n" + config.read_text(encoding="utf-8")
    config.write_text(commented, encoding="utf-8")
    assert config_hash(project) == started_with
    writer = Writer(project, fake_clis)
    try:
        assert read_state(project)["config_hash"] == started_with

        # A pending change (ADR 0002): saved during the run, which keeps its own config.
        config.write_text(commented.replace("output_name: demo", "output_name: other"), "utf-8")

        assert config_hash(project) != started_with
        assert read_state(project)["config_hash"] == started_with
    finally:
        writer.finish()
    assert read_state(project)["config_hash"] == started_with


@pytest.mark.parametrize(("env", "named"), [({}, "the CLI"), ({ORIGIN_ENV: "ui"}, "the UI")])
def test_the_lock_refusal_names_who_started_the_run_and_when(
    project: Path,
    fake_clis: FakeClis,
    env: dict[str, str],
    named: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    writer = Writer(project, fake_clis, env=env)
    try:
        state = read_state(project)
        assert state["origin"] == ("ui" if env else "cli")
        started = datetime.fromisoformat(state["started_at"])
        capsys.readouterr()

        assert main(["run", str(project), "--until", "script"]) != 0

        err = capsys.readouterr().err
        assert "a run is in progress" in err
        assert f"started from {named} at {started:%Y-%m-%d %H:%M}" in err
    finally:
        writer.finish()


def test_a_killed_run_reads_as_failed(project: Path, writer: Writer) -> None:
    writer.kill()
    assert read_state(project)["status"] == "running"  # nobody was left to say otherwise

    state = read_run_state(project)

    assert state is not None
    assert state.status == "failed"
    assert state.error is not None
    assert state.error.stage == "script"
    assert "ended unexpectedly" in state.error.message


def test_an_unknown_run_origin_is_refused_before_the_run(
    make_project: MakeProject, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project()
    monkeypatch.setenv(ORIGIN_ENV, "cron")

    assert main(["run", str(project), "--until", "script"]) == 1

    assert f"{ORIGIN_ENV}: unknown run origin 'cron'" in capsys.readouterr().err
    assert not (project / "build").exists()
