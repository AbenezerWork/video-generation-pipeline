"""Gate decisions and shot redo through the UI's HTTP API on fake providers."""

from __future__ import annotations

import pytest

pytest.importorskip("starlette", reason="needs the optional ui extra")
pytest.importorskip("uvicorn", reason="needs the optional ui extra")

from tests.conftest import MakeProject  # noqa: E402
from tests.test_gates import ledger, read_json  # noqa: E402
from tests.test_ui_run_controls import by_stage, end_run, wait_for_status  # noqa: E402
from tests.ui_server import UiServer  # noqa: E402
from vidpipe.cli import main  # noqa: E402


def test_approving_reviewed_outputs_resumes_the_paused_run_with_its_stage_limit(
    make_project: MakeProject,
) -> None:
    project = make_project(gates=["script"])
    ui = UiServer(project)
    try:
        assert ui.post("/api/run/start", {"until": "storyboard"}).status == 202
        paused = wait_for_status(ui, "paused")
        assert paused["paused_at"] == "script"
        assert ui.get("/api/stages/script/outputs").json()["script"]["lines"]
        assert not (project / "build" / "storyboard.json").exists()

        assert ui.post("/api/gates/storyboard/approve", {"run_id": paused["run_id"]}).status == 409
        approval = ui.post("/api/gates/script/approve", {"run_id": paused["run_id"]})
        assert approval.status == 202
        finished = wait_for_status(ui, "finished")
        assert finished["run_id"] == approval.json()["run_id"]
        assert finished["until"] == "storyboard"
        assert by_stage(finished)["script"]["status"] == "reused"
        assert (project / "build" / "storyboard.json").is_file()
        assert not (project / "build" / "narration.json").exists()
    finally:
        ui.stop()
        end_run(project)


def test_rejecting_a_gate_leaves_it_paused_and_returns_next_steps(
    make_project: MakeProject,
) -> None:
    project = make_project(gates=["script"])
    ui = UiServer(project)
    try:
        assert ui.post("/api/run/start", {"until": "storyboard"}).status == 202
        paused = wait_for_status(ui, "paused")
        action = "/api/gates/script/reject"
        assert ui.post(action, {"run_id": "an-earlier-run"}).status == 409
        body = {"run_id": paused["run_id"]}
        assert ui.post(action, body, headers={"Origin": "https://example.org"}).status == 403

        rejection = ui.post(action, body)
        assert rejection.status == 200
        steps = " ".join(rejection.json()["next_steps"]).lower()
        assert all(word in steps for word in ("config", "redo", "files"))
        assert ui.get("/api/run").json() == paused
        assert not (project / "build" / "approvals.json").exists()
        assert not (project / "build" / "storyboard.json").exists()

        # The CLI can approve the gate without resuming. Reject must still hold a later run.
        assert main(["approve", str(project), "script"]) == 0
        assert ui.post(action, body).status == 200
        assert "script" not in read_json(project / "build" / "approvals.json")["gates"]
        assert ui.get("/api/run").json() == paused
    finally:
        ui.stop()
        end_run(project)


@pytest.mark.needs_ffmpeg
def test_redo_replaces_only_one_shot_and_its_assemblies_after_a_fresh_gate_review(
    make_project: MakeProject,
) -> None:
    project = make_project(gates=["keyframes"])
    ui = UiServer(project)
    gate = "/api/gates/keyframes/approve"
    try:
        assert ui.post("/api/run/start").status == 202
        paused = wait_for_status(ui, "paused")
        assert ui.post(gate, {"run_id": paused["run_id"]}).status == 202
        wait_for_status(ui, "finished")
        before = ledger(project)
        keyframe = project / "build" / "keyframes" / "shot_02.png"
        original_keyframe = keyframe.read_bytes()

        redo = ui.post("/api/shots/2/redo")
        assert redo.status == 202
        review = wait_for_status(ui, "paused")
        assert review["run_id"] == redo.json()["run_id"]
        assert (review["command"], review["shot"], review["paused_at"]) == ("redo", 2, "keyframes")
        at_gate = ledger(project)
        assert {key for key in at_gate if at_gate[key] != before[key]} == {"keyframes/shot_02"}
        assert keyframe.read_bytes() != original_keyframe
        assert ui.post(gate, {"run_id": paused["run_id"]}).status == 409

        assert ui.post(gate, {"run_id": review["run_id"]}).status == 202
        done = wait_for_status(ui, "finished")
        assert by_stage(done)["video"]["generated"] == 1
        assert by_stage(done)["assembly"]["generated"] == 2
        after = ledger(project)
        assert after.keys() == before.keys()
        assert {key for key in after if after[key] != before[key]} == {
            "keyframes/shot_02",
            "video/shot_02",
            "assembly/en",
            "assembly/am",
        }
    finally:
        ui.stop()
        end_run(project)
