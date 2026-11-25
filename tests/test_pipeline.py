"""Seam 1: the pipeline run, driven through the CLI entry point on a project directory."""

from __future__ import annotations

import json
import shutil
import wave
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import MakeProject, ffprobe
from vidpipe.cli import main


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


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_run_through_music_produces_every_stage_artifact(make_project: MakeProject) -> None:
    project = make_project()

    assert run_cli("run", str(project), "--until", "music") == 0

    build = project / "build"
    storyboard = read_json(build / "storyboard.json")
    shot_ids = [s["id"] for s in storyboard["shots"]]
    assert shot_ids == [1, 2, 3]
    assert {s["motion_type"] for s in storyboard["shots"]} <= {"push_in", "pan", "ambient"}

    # Translation: the primary language is the script, every other language is translated.
    am = read_json(build / "translation" / "am.json")
    assert am["language"] == "am"
    assert len(am["lines"]) == 3

    # Narration: one real audio file per shot per language, durations match the files.
    narration = read_json(build / "narration.json")["clips"]
    assert len(narration) == len(shot_ids) * 2
    for clip in narration:
        with wave.open(str(build / clip["path"])) as wav:
            assert wav.getnframes() / wav.getframerate() == pytest.approx(clip["duration_s"])

    # Fit planning: shared visuals are sized to the longer narration per shot.
    for shot in read_json(build / "fit_plan.json")["shots"]:
        longest = max(c["duration_s"] for c in narration if c["shot_id"] == shot["shot_id"])
        assert shot["clip_seconds"] >= longest

    # Keyframes and video clips exist per shot; the music covers the whole timeline.
    for item in read_json(build / "keyframes.json")["items"]:
        assert (build / item["path"]).read_bytes().startswith(b"\x89PNG")
    assert len(read_json(build / "video.json")["items"]) == 3
    music = read_json(build / "music.json")["items"][0]["path"]
    total = sum(s["clip_seconds"] for s in read_json(build / "fit_plan.json")["shots"])
    with wave.open(str(build / music)) as wav:
        assert wav.getnframes() / wav.getframerate() == pytest.approx(total)

    # The manifest records the provider that ran each stage.
    manifest = {s["stage"]: s["provider"] for s in read_json(build / "manifest.json")["stages"]}
    assert manifest["narration"] == "fake-tts"
    assert not (project / "out").exists()  # assembly was not requested


def test_swapping_a_provider_in_yaml_changes_which_provider_runs(
    make_project: MakeProject,
) -> None:
    default = make_project()
    assert run_cli("run", str(default), "--until", "translation") == 0
    plain = read_json(default / "build" / "translation" / "am.json")["lines"][0]["text"]
    shutil.rmtree(default.parent / "project")

    swapped = make_project(providers={"translation": "fake-translation-upper"})
    assert run_cli("run", str(swapped), "--until", "translation") == 0
    shouted = read_json(swapped / "build" / "translation" / "am.json")["lines"][0]["text"]

    assert shouted == plain.upper().replace("[AM]", "[am]")
    assert shouted != plain
    manifest = read_json(swapped / "build" / "manifest.json")["stages"]
    assert {s["stage"]: s["provider"] for s in manifest}["translation"] == "fake-translation-upper"


def test_unsupported_request_is_rejected_at_plan_time_before_any_generation(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(providers={"narration": "fake-tts-en-only"})

    assert run_cli("run", str(project), "--until", "music") == 1

    assert "narration" in capsys.readouterr().err
    assert not (project / "build").exists()


def test_plan_reports_the_same_problem_without_generating(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(providers={"narration": "fake-tts-en-only"})

    assert run_cli("plan", str(project), "--until", "music") == 1

    err = capsys.readouterr().err
    assert "does not support language 'am'" in err
    assert not (project / "build").exists()


def test_unknown_provider_name_is_a_plan_problem(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(providers={"music": "no-such-provider"})

    assert run_cli("plan", str(project)) == 1
    assert "no-such-provider" in capsys.readouterr().err


@pytest.mark.needs_ffmpeg
def test_full_run_renders_a_playable_video_per_language(make_project: MakeProject) -> None:
    project = make_project()

    assert run_cli("run", str(project)) == 0

    expected = sum(
        s["clip_seconds"] for s in read_json(project / "build" / "fit_plan.json")["shots"]
    )
    for lang in ("en", "am"):
        probe = ffprobe(project / "out" / f"demo_{lang}.mp4")
        kinds = sorted(s["codec_type"] for s in probe["streams"])
        assert kinds == ["audio", "video"]
        assert float(probe["format"]["duration"]) == pytest.approx(expected, abs=0.2)
