"""Seam 1 (``vidpipe plan``): the dry run, driven through the CLI and the library entry point.

``plan`` reports, from what is on disk, the segments, speed factors and continuation clips each shot
would get and the estimated GPU time (and dollars) per stage and overall, without a single provider
generation call. It uses real narration durations where narration has been generated and estimates
from the script text (at the TTS provider's declared speaking rate) everywhere else.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import MakeProject
from tests.recording import Recorder, RecordingRegistry
from tests.test_fit_plan import (
    SLOW_SPEECH,
    project_with_script,
    read_json,
    with_shots,
    words,
)
from vidpipe import pipeline
from vidpipe.cli import main


def plan_json(
    capsys: pytest.CaptureFixture[str], project: Path, *args: str, code: int = 0
) -> dict[str, Any]:
    """Run ``vidpipe plan --json`` (up to music, so the result does not depend on ffmpeg)."""
    capsys.readouterr()
    assert main(["plan", str(project), "--json", *(args or ("--until", "music"))]) == code
    return json.loads(capsys.readouterr().out)


def storyboarded(make_project: MakeProject, lines: list[str] | None = None, **config: Any) -> Path:
    """A project with a script and storyboard but nothing generated after them."""
    project = project_with_script(make_project, lines, **config)
    assert main(["run", str(project), "--until", "storyboard"]) == 0
    return project


def stage(report: dict[str, Any], name: str) -> dict[str, Any]:
    return next(s for s in report["stages"] if s["stage"] == name)


#: Two 70-character sentences: about 5.6 s of English each, so one clip each, slowed to fit.
LONG_SENTENCE = words(14)
LONG_FIRST_LINE = [f"{LONG_SENTENCE} {LONG_SENTENCE}", words(8), words(8)]


def test_plan_lists_segments_speeds_and_continuation_clips_per_shot(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = storyboarded(make_project, LONG_FIRST_LINE)

    report = plan_json(capsys, project)  # no narration yet: durations come from the script text

    shots = report["fit"]["shots"]
    first, second = shots[0], shots[1]
    clips = first["visual_sets"]["shared"]["clips"]
    assert [(c["index"], c["continues"]) for c in clips] == [(0, None), (1, 0)]  # one continuation
    en = first["languages"]["en"]
    assert en["estimated"] is True
    assert [s["text"] for s in en["segments"]] == [LONG_SENTENCE, LONG_SENTENCE]
    # 11.28 s of English over two 5 s clips: both played at 10 / 11.28 of normal speed.
    assert [c["speed"] for c in en["clips"]] == pytest.approx([0.89, 0.89], abs=0.01)
    assert len(second["visual_sets"]["shared"]["clips"]) == 1
    assert second["languages"]["en"]["clips"][0]["speed"] == pytest.approx(
        1.172, abs=0.001
    )  # 3.75 / 3.2
    assert report["fit"]["render_seconds"]["en"] == pytest.approx(11.28 + 3.2 + 3.2)
    assert report["ok"] is True  # continuation clips are planned, not an error, in a dry run


def test_plan_prints_the_fit_plan_for_a_person_to_read(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = storyboarded(make_project, LONG_FIRST_LINE)
    capsys.readouterr()

    assert main(["plan", str(project), "--until", "music"]) == 0

    out = capsys.readouterr().out
    assert "shot 1" in out and "2 clips" in out and "continuation" in out
    assert "speed 0.89x" in out
    assert "estimated" in out  # says the durations are not real narration yet
    assert "gpu-min" in out
    assert LONG_SENTENCE in out


def test_plan_uses_real_narration_durations_where_they_exist(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = storyboarded(make_project)
    assert main(["run", str(project), "--until", "narration"]) == 0
    clips = read_json(project / "build" / "narration.json")["clips"]

    report = plan_json(capsys, project)

    for shot in report["fit"]["shots"]:
        for language in shot["languages"].values():
            real = next(
                c["duration_s"]
                for c in clips
                if c["shot_id"] == shot["shot_id"] and c["language"] == language["language"]
            )
            assert language["narration_s"] == pytest.approx(real)
            assert language["estimated"] is False


def test_plan_estimates_only_the_narration_that_changed_since_it_was_generated(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = storyboarded(make_project)
    assert main(["run", str(project), "--until", "narration"]) == 0
    script_path = project / "build" / "script.json"
    script = read_json(script_path)
    script["lines"][1]["text"] = "A much longer replacement line for the second shot, hand edited."
    script_path.write_text(json.dumps(script), encoding="utf-8")

    report = plan_json(capsys, project)

    estimated = {
        (s["shot_id"], lang["language"]): lang["estimated"]
        for s in report["fit"]["shots"]
        for lang in s["languages"].values()
    }
    assert estimated[1, "en"] is False and estimated[3, "en"] is False
    assert estimated[2, "en"] is True  # the generated narration is for the old text


def test_plan_makes_no_provider_generation_calls_and_writes_nothing(
    make_project: MakeProject,
) -> None:
    project = storyboarded(make_project, LONG_FIRST_LINE)
    before = sorted(p.relative_to(project).as_posix() for p in project.rglob("*") if p.is_file())
    ledger_before = (project / "build" / "ledger.json").read_bytes()
    recorder = Recorder()

    the_plan = pipeline.plan(
        project, until="music", registry=RecordingRegistry(recorder), estimate=True
    )

    assert the_plan.ok
    assert recorder.calls == []
    assert (
        sorted(p.relative_to(project).as_posix() for p in project.rglob("*") if p.is_file())
        == before
    )
    assert (project / "build" / "ledger.json").read_bytes() == ledger_before


def test_plan_estimates_gpu_time_per_stage_and_overall_from_declared_costs(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    # The canned script, narrated by the fake narrator's default 0.05 s per character.
    project = storyboarded(make_project, providers={"narration": "fake-tts"})

    report = plan_json(capsys, project)

    # Shared clips are sized to the Amharic narration (3.80, 3.50 and 3.55 s, rounded up to 0.25 s):
    # 4.00 + 3.50 + 3.75 = 11.25 s of video. The longest render is Amharic at 10.85 s, so music
    # is made for 11 s. Declared costs: keyframes 0.4 GPU min per image, video 0.5 per second,
    # music 0.05 per second.
    assert stage(report, "keyframes")["gpu_minutes"] == pytest.approx(3 * 0.4)
    assert stage(report, "video")["gpu_minutes"] == pytest.approx(11.25 * 0.5)
    assert stage(report, "video")["output_seconds"] == pytest.approx(11.25)
    assert stage(report, "music")["gpu_minutes"] == pytest.approx(11 * 0.05)
    assert report["gpu_minutes"] == pytest.approx(1.2 + 5.625 + 0.55)
    assert report["dollars"] == 0
    assert report["complete"] is True
    # Text and narration cost no GPU time.
    for free in ("script", "translation", "storyboard", "narration", "fit-planning"):
        assert stage(report, free)["gpu_minutes"] in (0, None)


def test_plan_prices_a_hosted_provider_in_dollars_not_gpu_time(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = storyboarded(
        make_project, providers={"narration": "fake-tts", "video": "fake-i2v-hosted"}
    )

    report = plan_json(capsys, project)

    assert stage(report, "video")["dollars"] == pytest.approx(11.25 * 0.05)
    assert stage(report, "video")["gpu_minutes"] == 0
    assert report["dollars"] == pytest.approx(11.25 * 0.05)
    assert report["gpu_minutes"] == pytest.approx(1.2 + 0.55)  # keyframes and music still local


def test_plan_before_the_storyboard_exists_says_what_it_cannot_know_yet(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project()

    report = plan_json(capsys, project)

    assert report["fit"] is None
    assert report["complete"] is False
    assert stage(report, "keyframes")["gpu_minutes"] is None  # needs the shot count
    assert any("storyboard" in note for note in report["notes"])
    assert not (project / "build").exists()


def test_plan_stops_at_the_requested_stage(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = storyboarded(make_project)

    report = plan_json(capsys, project, "--until", "keyframes")

    assert [s["stage"] for s in report["stages"]][-1] == "keyframes"
    assert report["fit"] is not None
    assert report["gpu_minutes"] == pytest.approx(1.2)


def test_plan_reports_a_render_over_90_seconds_before_anything_is_narrated(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = project_with_script(make_project)
    with_shots(project, 15)

    report = plan_json(capsys, project, code=1)

    assert any("am render would last 91.2s, over the 90s limit" in p for p in report["problems"])
    assert report["ok"] is False


def test_plan_reports_a_language_that_cannot_fit_primary_only_clips(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = storyboarded(
        make_project,
        ["x" * 10, "y" * 10, "z" * 10],
        visuals="primary_only",
        providers={"narration": SLOW_SPEECH},
    )

    report = plan_json(capsys, project, code=1)

    assert any("am narration is 6.00s" in p for p in report["problems"])
