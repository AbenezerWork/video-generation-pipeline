"""Seam 1 (fit planning): the pipeline run through the CLI, on a project directory.

Narration runs at real-speech length (the fake TTS speaks 0.08 s per character, like edge-tts), the
fake video provider makes 1-5 s clips, and the assertions read ``build/fit_plan.json``: how many
clips each shot needs, what speed each is played at, where narration is cut, and what each render
adds up to.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import MakeProject
from vidpipe.cli import main

#: Speaks like a real voice: 0.08 s per character, no 4 s cap.
REAL_SPEECH: dict[str, Any] = {
    "name": "fake-tts",
    "options": {"seconds_per_char": 0.08, "max_seconds": 120.0},
}
MAX_SPEED = 1.3


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def project_with_script(
    make_project: MakeProject, lines: list[str] | None = None, **config: Any
) -> Path:
    """A project whose script is ``lines`` (the canned three lines when omitted)."""
    providers = {"narration": REAL_SPEECH, **config.pop("providers", {})}
    project = make_project(providers=providers, **config)
    if lines is not None:
        assert main(["run", str(project), "--until", "script"]) == 0
        path = project / "build" / "script.json"
        script = read_json(path)
        script["lines"] = [{"id": i, "text": t} for i, t in enumerate(lines, start=1)]
        path.write_text(json.dumps(script), encoding="utf-8")
    return project


def fit_plan(project: Path) -> dict[str, Any]:
    assert main(["run", str(project), "--until", "fit-planning"]) == 0
    return read_json(project / "build" / "fit_plan.json")


def narration_s(project: Path, language: str, shot_id: int) -> float:
    clips = read_json(project / "build" / "narration.json")["clips"]
    return next(
        c["duration_s"] for c in clips if c["language"] == language and c["shot_id"] == shot_id
    )


def test_narration_longer_than_the_clip_cap_is_fit_by_a_speed_change_not_an_error(
    make_project: MakeProject,
) -> None:
    project = project_with_script(make_project)

    plan = fit_plan(project)

    # The sample script's first English line is 5.68 s of speech against a 5 s clip cap.
    shot = plan["shots"][0]
    assert narration_s(project, "en", 1) == pytest.approx(5.68)
    assert len(shot["visual_sets"]["shared"]["clips"]) == 1
    assert shot["visual_sets"]["shared"]["clips"][0]["seconds"] == 5.0
    en = shot["languages"]["en"]
    assert en["seconds"] == pytest.approx(5.68)  # the shot lasts exactly as long as the narration
    assert en["clips"][0]["speed"] == pytest.approx(5.0 / 5.68, abs=0.001)  # slowed to fit
    assert 1 / MAX_SPEED <= en["clips"][0]["speed"] <= MAX_SPEED
    assert plan["problems"] == []


def test_shared_visuals_are_sized_to_the_longer_language_and_the_shorter_one_speeds_up(
    make_project: MakeProject,
) -> None:
    # 40 characters: English speaks 3.2 s; the fake translation adds "[am] ", so Amharic is 3.6 s.
    project = project_with_script(make_project, ["x" * 40, "y" * 40, "z" * 40])

    plan = fit_plan(project)

    shot = plan["shots"][0]
    clips = shot["visual_sets"]["shared"]["clips"]
    assert shot["visual_sets"]["shared"]["driver"] == "am"
    assert [c["seconds"] for c in clips] == [3.75]  # the longer narration, rounded up to 0.25 s
    en, am = shot["languages"]["en"], shot["languages"]["am"]
    assert am["seconds"] == pytest.approx(3.6)
    assert en["seconds"] == pytest.approx(3.2)
    # The shorter language plays the same clip slightly faster instead of freezing or padding.
    assert en["clips"][0]["speed"] == pytest.approx(3.75 / 3.2, abs=0.001)
    assert am["clips"][0]["speed"] == pytest.approx(1.0)
    assert plan["render_seconds"]["en"] == pytest.approx(3 * 3.2)
    assert plan["render_seconds"]["am"] == pytest.approx(3 * 3.6)


def words(count: int, stop: str = ".") -> str:
    """``count`` four-letter words: ``count * 5 - 1`` characters, ending in ``stop``."""
    return " ".join(["word"] * count) + stop


def narrate_and_plan(
    make_project: MakeProject, first_line: str, expect_exit: int = 1, **config: Any
) -> tuple[Path, dict[str, Any]]:
    """Plan a script whose first shot says ``first_line`` (the other two are short)."""
    project = project_with_script(make_project, [first_line, words(8), words(8)], **config)
    code = main(["run", str(project), "--until", "fit-planning"])
    assert code == expect_exit
    return project, read_json(project / "build" / "fit_plan.json")


def english_segments(plan: dict[str, Any], shot: int = 0) -> list[str]:
    return [s["text"] for s in plan["shots"][shot]["languages"]["en"]["segments"]]


# (what the line looks like, the line, where it is cut). At 0.08 s per character one clip plays at
# most 5 s x 1.3 = 6.5 s, so each of these is too long for one clip.
SENTENCE_A = words(12)  # 60 characters, 4.8 s
SENTENCE_B = words(12)
CLAUSE = words(12, ",")
NATURAL_CUTS = [
    pytest.param(
        f"{SENTENCE_A} {SENTENCE_B}",
        [SENTENCE_A, SENTENCE_B],
        id="at the sentence boundary",
    ),
    pytest.param(
        f"{CLAUSE} {SENTENCE_B}",
        [CLAUSE, SENTENCE_B],
        id="at the clause boundary when the sentence is too long for one clip",
    ),
    pytest.param(
        # Cutting at the comma would also make two clips (2.8 s + 6.1 s), but the sentence boundary
        # (5.7 s + 3.2 s) is the more natural place, so it wins.
        f"{words(7, ',')} {words(7)} {words(8)}",
        [f"{words(7, ',')} {words(7)}", words(8)],
        id="sentence boundary preferred over a clause boundary that makes as many clips",
    ),
    pytest.param(
        # No punctuation at all, 12.7 s: the only natural pause is between words.
        words(32),
        None,
        id="at a pause between words when there is no punctuation",
    ),
    pytest.param(
        # Ethiopic full stop and comma: sentence and clause boundaries, not word gaps.
        "አንድ ቀን በኢትዮጵያ ተራሮች ላይ አንድ ወጣት እረኛ በጎቹን ይጠብቅ ነበር፣ ከዚያም ቀይ ፍሬዎችን አየ። "
        "ፍየሎቹ ፍሬውን በልተው መደነስ ጀመሩ፣ እረኛውም ተገረመ።",
        None,
        id="with Ethiopic punctuation",
    ),
]


@pytest.mark.parametrize(("line", "expected"), NATURAL_CUTS)
def test_narration_too_long_for_one_clip_is_cut_at_natural_boundaries(
    make_project: MakeProject, line: str, expected: list[str] | None
) -> None:
    _, plan = narrate_and_plan(make_project, line)

    segments = english_segments(plan)
    assert len(segments) > 1
    # Nothing is lost or reordered, and each piece fits one clip played at up to 1.3x.
    assert " ".join(segments) == line
    for segment in plan["shots"][0]["languages"]["en"]["segments"]:
        assert segment["end_s"] - segment["start_s"] <= 5.0 * MAX_SPEED + 1e-6
    if expected is not None:
        assert segments == expected
    else:
        # Cut at a sentence/clause mark if the text has one that fits, otherwise at a word gap:
        # never inside a word.
        for text in segments:
            assert text == text.strip()
            assert all(w in line.split() for w in text.split())


def test_every_extra_segment_becomes_a_continuation_clip_started_from_the_previous_clip(
    make_project: MakeProject,
) -> None:
    _, plan = narrate_and_plan(make_project, f"{SENTENCE_A} {SENTENCE_B}")

    visual_set = plan["shots"][0]["visual_sets"]["shared"]
    clips = visual_set["clips"]
    # About 5 s of Amharic speech per sentence: each sentence is one clip within the provider's
    # 1-5 s range (slowed a little where it is longer than the clip).
    assert [(c["index"], c["continues"]) for c in clips] == [(0, None), (1, 0)]
    assert all(4.5 <= c["seconds"] <= 5.0 for c in clips)
    # The clips carry the narration they cover, for the continuation prompt.
    assert clips[0]["text"].endswith(SENTENCE_A) and clips[1]["text"].endswith(SENTENCE_B)
    en = plan["shots"][0]["languages"]["en"]
    assert [c["clip"] for c in en["clips"]] == [0, 1]
    assert sum(c["seconds"] for c in en["clips"]) == pytest.approx(en["seconds"])
    assert [s["clip"] for s in en["segments"]] == [0, 1]
    assert en["segments"][0]["start_s"] == 0
    assert en["segments"][-1]["end_s"] == pytest.approx(en["seconds"])
    # The other shots still need a single clip.
    assert [len(s["visual_sets"]["shared"]["clips"]) for s in plan["shots"]] == [2, 1, 1]


def test_a_run_that_needs_continuation_clips_stops_before_generating_anything_else(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = project_with_script(make_project, [f"{SENTENCE_A} {SENTENCE_B}", words(8), words(8)])

    assert main(["run", str(project), "--until", "music"]) == 1

    assert "continuation" in capsys.readouterr().err
    assert (project / "build" / "fit_plan.json").is_file()  # the plan is kept, for `vidpipe plan`
    assert not (project / "build" / "keyframes.json").exists()
