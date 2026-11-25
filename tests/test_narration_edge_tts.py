"""Seam 1 for the edge-tts narration provider: the pipeline run, driven through the CLI.

Plan-time behaviour runs offline. Anything that reaches the real Edge service carries the
``integration`` marker (the provider also runs the shared conformance suite in
``tests/conformance``).
"""

from __future__ import annotations

import json

import pytest

from tests.conftest import MakeProject, nothing_generated
from vidpipe.cli import main

EDGE = {"narration": "edge-tts"}


def test_plan_accepts_edge_tts_for_english_and_amharic(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(providers=EDGE)

    assert main(["plan", str(project), "--until", "narration"]) == 0

    assert "edge-tts" in capsys.readouterr().out
    assert nothing_generated(project)


def test_plan_rejects_a_language_edge_tts_is_not_configured_for(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(providers=EDGE, languages=["en", "fr"])

    assert main(["plan", str(project), "--until", "narration"]) == 1

    assert "does not support language 'fr'" in capsys.readouterr().err


def test_plan_rejects_a_malformed_fallback_declaration(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(providers={"narration": {"name": "edge-tts", "fallback": 5}})

    assert main(["plan", str(project), "--until", "narration"]) == 1

    assert "fallback" in capsys.readouterr().err


def test_plan_accepts_the_offline_mms_tts_fallback_declared_in_config(
    make_project: MakeProject,
) -> None:
    narration = {"name": "edge-tts", "options": {"voices": {"am": "am-ET-MekdesNeural"}}}
    project = make_project(providers={"narration": {**narration, "fallback": ["mms-tts"]}})

    assert main(["plan", str(project), "--until", "narration"]) == 0


# edge-tts returns 48 kbit/s constant-bitrate MP3, so file size is an independent length check.
_BYTES_PER_SECOND = 48_000 / 8


@pytest.mark.integration
def test_run_narrates_both_languages_with_real_durations(make_project: MakeProject) -> None:
    narration = {"name": "edge-tts", "options": {"voices": {"am": "am-ET-MekdesNeural"}}}
    project = make_project(providers={"narration": narration})

    assert main(["run", str(project), "--until", "narration"]) == 0

    build = project / "build"
    clips = json.loads((build / "narration.json").read_text(encoding="utf-8"))["clips"]
    assert {c["language"] for c in clips} == {"en", "am"}
    assert len(clips) == 6
    for clip in clips:
        audio = build / clip["path"]
        assert audio.suffix == ".mp3"
        assert clip["duration_s"] > 1
        assert clip["duration_s"] == pytest.approx(
            audio.stat().st_size / _BYTES_PER_SECOND, abs=0.1
        )
