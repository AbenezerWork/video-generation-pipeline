"""Seam 1 for translation: the English -> Amharic stage and its back-translation check, run through
the CLI on a project whose translation chain is the real CLI adapters talking to fake executables.

Call order in a ``[gemini-cli, claude-cli]`` chain: gemini translates; claude (a different model)
back-translates the Amharic blind and then compares that with the English source.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.cli_text_fixtures import FakeClis
from tests.conftest import MakeProject
from vidpipe.cli import main
from vidpipe.gates import EXIT_PAUSED
from vidpipe.providers.fakes import CANNED_SCRIPT

AMHARIC = [
    "ከፍ ባለው የኢትዮጵያ ደጋማ ቦታ አንድ ወጣት የፍየል እረኛ መንጋውን ይጠብቅ ነበር።",
    "አንድ ምሽት ፍየሎቹ ደማቅ ቀይ ፍሬዎችን በልተው መደነስ ጀመሩ።",
    "ፍሬዎቹን ወደ ቤት ወሰዳቸው፤ የመጀመሪያውም ቡና ተፈጠረ።",
]
BACK = [
    "In the high Ethiopian highlands a young goat herder was watching his flock.",
    "One evening the goats ate bright red berries and began to dance.",
    "He took the berries home, and the first coffee was created.",
]


def lines(texts: list[str]) -> str:
    return json.dumps({"lines": [{"id": i, "text": t} for i, t in enumerate(texts, start=1)]})


def verdicts(*drifted: tuple[int, str]) -> str:
    reasons = dict(drifted)
    return json.dumps(
        {
            "lines": [
                {
                    "id": i,
                    "status": "drift" if i in reasons else "ok",
                    "reason": reasons.get(i, ""),
                }
                for i in (1, 2, 3)
            ]
        }
    )


TRANSLATED = lines(AMHARIC)
BACK_TRANSLATED = lines(BACK)
ALL_OK = verdicts()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def translate_project(make_project: MakeProject, chain: Any = ("gemini-cli", "claude-cli")) -> Path:
    return make_project(providers={"translation": list(chain) if chain else chain})


def run_translation(project: Path) -> int:
    return main(["run", str(project), "--until", "translation"])


def queue_happy_path(fake_clis: FakeClis, verdict: str = ALL_OK) -> None:
    fake_clis.reply("gemini", TRANSLATED)
    fake_clis.reply("claude", BACK_TRANSLATED, verdict)


def test_the_script_is_translated_into_amharic_keeping_line_ids(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    queue_happy_path(fake_clis)
    project = translate_project(make_project)

    assert run_translation(project) == 0

    script = read_json(project / "build" / "script.json")
    am = read_json(project / "build" / "translation" / "am.json")
    assert am["language"] == "am"
    assert [line["id"] for line in am["lines"]] == [line["id"] for line in script["lines"]]
    assert [line["text"] for line in am["lines"]] == AMHARIC
    # The English lines went to the translator, numbered by line id.
    prompt = fake_clis.calls("gemini")[0].stdin
    assert all(text in prompt for text in CANNED_SCRIPT)


def test_amharic_is_written_as_utf_8_and_reaches_the_checker_intact(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    queue_happy_path(fake_clis)
    project = translate_project(make_project)

    assert run_translation(project) == 0

    raw = (project / "build" / "translation" / "am.json").read_bytes()
    assert AMHARIC[0].encode("utf-8") in raw  # real Ge'ez, not \u12xx escapes or mojibake
    assert AMHARIC[0] in fake_clis.calls("claude")[0].stdin


def test_the_back_translation_is_done_by_a_different_provider(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    queue_happy_path(fake_clis)
    project = translate_project(make_project)

    assert run_translation(project) == 0

    assert len(fake_clis.calls("gemini")) == 1  # the translator only translated
    claude = fake_clis.calls("claude")
    assert len(claude) == 2  # back-translation, then comparison
    # The back-translation is blind: it never sees the English source.
    assert CANNED_SCRIPT[0] not in claude[0].stdin
    assert CANNED_SCRIPT[0] in claude[1].stdin
    review = read_json(project / "build" / "translation" / "am.review.json")
    assert (review["translator"], review["checker"]) == ("gemini-cli", "claude-cli")
    assert review["same_model"] is False
    assert [(c["id"], c["status"]) for c in review["lines"]] == [(1, "ok"), (2, "ok"), (3, "ok")]
    assert review["lines"][0]["back_translation"] == BACK[0]


def test_a_drifted_line_is_flagged_in_the_artifact_and_reported(
    make_project: MakeProject, fake_clis: FakeClis, capsys: pytest.CaptureFixture[str]
) -> None:
    reason = "the translation says one evening, the source says the berries were eaten at noon"
    queue_happy_path(fake_clis, verdicts((2, reason)))
    project = translate_project(make_project)

    assert run_translation(project) == 0  # drift is for a human to review; it does not fail the run

    review = read_json(project / "build" / "translation" / "am.review.json")
    statuses = {c["id"]: c["status"] for c in review["lines"]}
    assert statuses == {1: "ok", 2: "drift", 3: "ok"}
    drifted = review["lines"][1]
    assert drifted["reason"] == reason
    assert drifted["source"] == CANNED_SCRIPT[1]
    assert drifted["translation"] == AMHARIC[1]
    # The same flags are in the ledger, so a gate can find them without opening the file.
    data = read_json(project / "build" / "ledger.json")["artifacts"]["translation/am/review"][
        "data"
    ]
    assert data["drifted"] == [2]
    err = capsys.readouterr().err
    assert "line 2" in err
    assert reason in err
    assert AMHARIC[1] in err


def test_a_clean_check_reports_nothing(
    make_project: MakeProject, fake_clis: FakeClis, capsys: pytest.CaptureFixture[str]
) -> None:
    queue_happy_path(fake_clis)
    project = translate_project(make_project)

    assert run_translation(project) == 0

    assert "drift" not in capsys.readouterr().err
    data = read_json(project / "build" / "ledger.json")["artifacts"]["translation/am/review"][
        "data"
    ]
    assert data["drifted"] == []


def test_a_single_provider_checks_its_own_translation_and_says_so(
    make_project: MakeProject, fake_clis: FakeClis, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_clis.reply("gemini", TRANSLATED, BACK_TRANSLATED, ALL_OK)
    project = translate_project(make_project, ["gemini-cli"])

    assert run_translation(project) == 0

    assert len(fake_clis.calls("gemini")) == 3
    review = read_json(project / "build" / "translation" / "am.review.json")
    assert (review["translator"], review["checker"]) == ("gemini-cli", "gemini-cli")
    assert review["same_model"] is True
    assert "same model" in capsys.readouterr().err


def test_when_the_chain_fell_back_the_checker_is_the_provider_that_did_not_translate(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    fake_clis.fail("gemini", "429 RESOURCE_EXHAUSTED: quota exceeded")
    fake_clis.reply("claude", TRANSLATED)
    fake_clis.reply("gemini", BACK_TRANSLATED, ALL_OK)  # gemini recovered for the check
    project = translate_project(make_project)

    assert run_translation(project) == 0

    ledger = read_json(project / "build" / "ledger.json")["artifacts"]
    assert "quota exceeded" in ledger["translation/am"]["fallback"]
    review = read_json(project / "build" / "translation" / "am.review.json")
    assert (review["translator"], review["checker"]) == ("claude-cli", "gemini-cli")
    assert review["same_model"] is False


def test_the_checker_is_never_the_translator_when_another_provider_exists(
    make_project: MakeProject, fake_clis: FakeClis, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_clis.reply("gemini", TRANSLATED)
    fake_clis.fail("claude", "429 rate limit")  # the only different provider is unavailable
    project = translate_project(make_project)

    assert run_translation(project) == 1

    assert "claude-cli" in capsys.readouterr().err
    assert len(fake_clis.calls("gemini")) == 1  # gemini was not asked to mark its own homework
    assert (project / "build" / "translation" / "am.json").is_file()

    # The translation is kept: once the checker is back, only the check runs.
    fake_clis.reply("claude", BACK_TRANSLATED, ALL_OK)
    assert run_translation(project) == 0
    assert len(fake_clis.calls("gemini")) == 1
    assert read_json(project / "build" / "translation" / "am.review.json")["same_model"] is False


def test_a_translation_that_loses_or_renumbers_lines_is_re_prompted(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    short = json.dumps({"lines": [{"id": 1, "text": AMHARIC[0]}, {"id": 2, "text": AMHARIC[1]}]})
    renumbered = json.dumps(
        {"lines": [{"id": i, "text": t} for i, t in zip((1, 2, 7), AMHARIC, strict=True)]}
    )
    fake_clis.reply("gemini", short, renumbered, TRANSLATED)
    fake_clis.reply("claude", BACK_TRANSLATED, ALL_OK)
    project = translate_project(make_project)

    assert run_translation(project) == 0

    assert len(fake_clis.calls("gemini")) == 3
    am = read_json(project / "build" / "translation" / "am.json")
    assert [line["id"] for line in am["lines"]] == [1, 2, 3]


def test_a_line_left_in_english_is_re_prompted(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    untranslated = lines([AMHARIC[0], CANNED_SCRIPT[1], AMHARIC[2]])
    fake_clis.reply("gemini", untranslated, TRANSLATED)
    fake_clis.reply("claude", BACK_TRANSLATED, ALL_OK)
    project = translate_project(make_project)

    assert run_translation(project) == 0

    assert len(fake_clis.calls("gemini")) == 2
    am = read_json(project / "build" / "translation" / "am.json")
    assert am["lines"][1]["text"] == AMHARIC[1]


def test_a_drift_verdict_without_a_reason_is_re_prompted(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    fake_clis.reply("gemini", TRANSLATED)
    fake_clis.reply("claude", BACK_TRANSLATED, verdicts((2, "")), verdicts((2, "wrong time")))
    project = translate_project(make_project)

    assert run_translation(project) == 0

    review = read_json(project / "build" / "translation" / "am.review.json")
    assert review["lines"][1]["reason"] == "wrong time"


def test_a_second_run_does_nothing_and_a_hand_edit_re_runs_only_the_check(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    queue_happy_path(fake_clis)
    project = translate_project(make_project)
    assert run_translation(project) == 0
    assert run_translation(project) == 0
    assert (len(fake_clis.calls("gemini")), len(fake_clis.calls("claude"))) == (1, 2)

    # A human fixes the flagged line by hand: the Amharic is kept and only re-checked.
    am_path = project / "build" / "translation" / "am.json"
    am = read_json(am_path)
    am["lines"][1]["text"] = "አንድ ምሽት ፍየሎቹ ቀይ ፍሬዎችን በልተው ጨፈሩ።"
    am_path.write_text(json.dumps(am, ensure_ascii=False), encoding="utf-8")
    fake_clis.reply("claude", BACK_TRANSLATED, ALL_OK)
    assert run_translation(project) == 0

    assert len(fake_clis.calls("gemini")) == 1
    assert len(fake_clis.calls("claude")) == 4
    assert read_json(am_path)["lines"][1]["text"].endswith("ጨፈሩ።")


def test_translation_defaults_to_gemini_then_claude(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project()
    config = yaml.safe_load((project / "vidpipe.yaml").read_text(encoding="utf-8"))
    del config["providers"]["translation"]
    text: str = yaml.safe_dump(config)  # pyright: ignore[reportUnknownMemberType]
    (project / "vidpipe.yaml").write_text(text, encoding="utf-8")

    assert main(["plan", str(project), "--until", "translation"]) == 0

    lines_out = capsys.readouterr().out.splitlines()
    assert any(
        row.startswith("translation") and "gemini-cli > claude-cli" in row for row in lines_out
    )


def test_a_non_text_translation_provider_still_works_and_is_not_back_checked(
    make_project: MakeProject,
) -> None:
    project = make_project()  # sample: fake-translation

    assert run_translation(project) == 0

    assert (project / "build" / "translation" / "am.json").is_file()
    assert not (project / "build" / "translation" / "am.review.json").exists()


def test_a_chain_naming_an_unknown_provider_is_a_plan_problem(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = translate_project(make_project, ["gemini-cli", "no-such-cli"])

    assert main(["plan", str(project), "--until", "translation"]) == 1

    assert "no-such-cli" in capsys.readouterr().err


def test_the_cli_prints_ge_ez_on_a_redirected_windows_style_console(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    """Piped stdout/stderr default to the locale code page on Windows (cp1252 cannot hold Ge'ez):
    the command line must still print the flagged Amharic line, as UTF-8."""
    queue_happy_path(fake_clis, verdicts((2, "wrong time")))
    project = translate_project(make_project)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    env["PYTHONIOENCODING"] = "cp1252:strict"  # what a Windows pipe gives a console script

    done = subprocess.run(
        [sys.executable, "-m", "vidpipe", "run", str(project), "--until", "translation"],
        capture_output=True,
        env=env,
        check=False,
    )

    assert done.returncode == 0, done.stderr.decode("utf-8", errors="replace")
    assert AMHARIC[1] in done.stderr.decode("utf-8")


def test_a_drifted_translation_is_shown_when_the_run_pauses_at_a_gate(
    make_project: MakeProject, fake_clis: FakeClis, capsys: pytest.CaptureFixture[str]
) -> None:
    queue_happy_path(fake_clis, verdicts((3, "the first cup is missing")))
    project = make_project(
        providers={"translation": ["gemini-cli", "claude-cli"]}, gates=["translation"]
    )

    assert main(["run", str(project), "--until", "storyboard"]) == EXIT_PAUSED

    captured = capsys.readouterr()
    assert "paused" in captured.out
    assert "the first cup is missing" in captured.err
    assert AMHARIC[2] in captured.err
