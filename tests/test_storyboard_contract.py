from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import MakeProject
from tests.test_resume import read_json
from vidpipe.cli import main


def test_committed_schemas_match_the_cli_output(tmp_path: Path) -> None:
    assert main(["schema", "--out", str(tmp_path)]) == 0
    committed = Path(__file__).resolve().parents[1] / "schema"
    names = {"storyboard.schema.json", "vidpipe.schema.json"}
    assert {path.name for path in tmp_path.iterdir()} == names
    for name in names:
        assert read_json(tmp_path / name) == read_json(committed / name)


def test_storyboard_is_validated_even_before_the_brief_stage(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project()
    (project / "storyboard.json").write_text('{"title":"Incomplete"}', encoding="utf-8")
    assert main(["run", str(project), "--until", "brief"]) == 1
    assert "invalid storyboard contract" in capsys.readouterr().err
    assert not (project / "build/brief.json").exists()
    assert not (project / "runs.jsonl").exists()
    state = read_json(project / "build/run_state.json")
    assert state["status"] == "failed"


@pytest.mark.needs_ffmpeg
def test_exported_storyboard_controls_text_and_regenerates_only_the_edited_shots(
    make_project: MakeProject,
) -> None:
    project = make_project()

    def run(until: str) -> None:
        assert main(["run", str(project), "--auto", "--until", until]) == 0

    def calls() -> list[str]:
        return [
            json.loads(line)["artifact"]
            for line in (project / "runs.jsonl").read_text(encoding="utf-8").splitlines()
        ]

    run("video")
    assert main(["export-storyboard", str(project)]) == 0
    path = project / "storyboard.json"
    contract = read_json(path)
    assert contract["shots"][0]["reason"] == "Illustrates the narration."
    assert set(contract["shots"][0]["narration"]) == {"en", "am"}
    before = calls()
    run("video")
    assert calls() == before

    contract["shots"][0]["narration"]["am"] = "Changed line."
    path.write_text(json.dumps(contract), encoding="utf-8")
    run("video")
    assert calls()[len(before)] == "narration/am/shot_01"
    assert all(key.startswith("video/shot_01") for key in calls()[len(before) + 1 :])
    assert read_json(project / "build/translation/am.json")["lines"][0]["text"] == "Changed line."

    contract["shots"][1]["visual"] = "Portrait of the protagonist at sunrise."
    path.write_text(json.dumps(contract), encoding="utf-8")
    before = calls()
    run("video")
    edited = calls()[len(before) :]
    assert edited[0] == "keyframes/shot_02"
    assert edited[1:] and all(key.startswith("video/shot_02") for key in edited[1:])
    stages = read_json(project / "build/manifest.json")["stages"]
    assert next(stage for stage in stages if stage["stage"] == "fit-planning")["generated"] == 0

    (project / "build/script.json").write_text("{}", encoding="utf-8")
    before = calls()
    run("video")
    assert calls() == before
    assert (
        read_json(project / "build/script.json")["lines"][0]["text"]
        == (contract["shots"][0]["narration"]["en"])
    )


def test_export_keeps_the_shot_fields_that_shape_keyframe_and_motion_prompts(
    make_project: MakeProject,
) -> None:
    project = make_project()
    assert main(["run", str(project), "--auto", "--until", "storyboard"]) == 0
    board_path = project / "build/storyboard.json"
    board = read_json(board_path)
    board["shots"][0].update(people=1, movement="Mist drifts slowly.", others=None)
    board_path.write_text(json.dumps(board), encoding="utf-8")

    assert main(["export-storyboard", str(project)]) == 0
    shot = read_json(project / "storyboard.json")["shots"][0]
    assert (shot["people"], shot["movement"]) == (1, "Mist drifts slowly.")

    assert main(["run", str(project), "--auto", "--until", "storyboard"]) == 0
    rebuilt = read_json(board_path)["shots"][0]
    assert (rebuilt["people"], rebuilt["movement"]) == (1, "Mist drifts slowly.")
