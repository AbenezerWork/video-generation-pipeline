"""Seam 1 for the text stages: script and storyboard run through the CLI on a project directory
whose text providers are the real CLI adapters talking to fake executables on PATH."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.cli_text_fixtures import FakeClis
from tests.conftest import MakeProject
from vidpipe.cli import main

LINES = [
    "Goats danced on the misty ridge.",
    "A herder followed the red berries home.",
    "The first cup of coffee was born.",
]
SCRIPT = json.dumps({"lines": LINES})


def storyboard(*motions: str, line_ids: tuple[int, ...] = (1, 2, 3)) -> str:
    return json.dumps(
        {
            "shots": [
                {"line_id": line_id, "visual": f"visual {line_id}", "motion_type": motion}
                for line_id, motion in zip(line_ids, motions, strict=True)
            ]
        }
    )


GOOD_STORYBOARD = storyboard("push_in", "pan", "ambient")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_until_storyboard(project: Path) -> int:
    return main(["run", str(project), "--until", "storyboard"])


def cli_project(make_project: MakeProject, script: Any, storyboard_: Any = "gemini-cli") -> Path:
    return make_project(providers={"script": script, "storyboard": storyboard_})


def test_script_and_storyboard_are_written_by_a_cli_text_provider(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    fake_clis.reply("gemini", f"Here you go:\n```json\n{SCRIPT}\n```", GOOD_STORYBOARD)
    project = cli_project(make_project, "gemini-cli")

    assert run_until_storyboard(project) == 0

    build = project / "build"
    script = read_json(build / "script.json")
    assert [line["text"] for line in script["lines"]] == LINES
    shots = read_json(build / "storyboard.json")["shots"]
    assert [(s["line_id"], s["motion_type"]) for s in shots] == [
        (1, "push_in"),
        (2, "pan"),
        (3, "ambient"),
    ]
    manifest = {s["stage"]: s["provider"] for s in read_json(build / "manifest.json")["stages"]}
    assert manifest["script"] == manifest["storyboard"] == "gemini-cli"


def test_a_motion_type_outside_the_vocabulary_is_re_prompted(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    fake_clis.reply(
        "gemini",
        SCRIPT,
        storyboard("zoom_out", "pan", "orbit"),
        storyboard("push_in", "pan", "pan"),
    )
    project = cli_project(make_project, "gemini-cli")

    assert run_until_storyboard(project) == 0

    shots = read_json(project / "build" / "storyboard.json")["shots"]
    assert {s["motion_type"] for s in shots} <= {"push_in", "pan", "ambient"}
    assert len(fake_clis.calls("gemini")) == 3  # script, then storyboard + one re-prompt


def test_a_storyboard_that_skips_or_invents_script_lines_is_re_prompted(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    fake_clis.reply(
        "gemini",
        SCRIPT,
        storyboard("pan", "pan", line_ids=(1, 2)),  # line 3 has no shot
        storyboard("pan", "pan", "pan", line_ids=(1, 2, 9)),  # line 9 does not exist
        GOOD_STORYBOARD,
    )
    project = cli_project(make_project, "gemini-cli")

    assert run_until_storyboard(project) == 0

    shots = read_json(project / "build" / "storyboard.json")["shots"]
    assert [s["line_id"] for s in shots] == [1, 2, 3]


def test_the_chain_moves_to_the_next_provider_on_a_rate_limit(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    fake_clis.fail("gemini", "429 RESOURCE_EXHAUSTED: quota exceeded for this model")
    fake_clis.fail("gemini", "429 RESOURCE_EXHAUSTED: quota exceeded for this model")
    fake_clis.reply("claude", SCRIPT, GOOD_STORYBOARD)
    project = cli_project(make_project, ["gemini-cli", "claude-cli"], ["gemini-cli", "claude-cli"])

    assert run_until_storyboard(project) == 0

    assert [line["text"] for line in read_json(project / "build" / "script.json")["lines"]] == LINES
    assert len(read_json(project / "build" / "storyboard.json")["shots"]) == 3
    assert len(fake_clis.calls("gemini")) == 2  # tried first for each stage
    assert len(fake_clis.calls("claude")) == 2


def test_the_chain_moves_on_after_a_provider_exhausts_its_re_prompts(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    fake_clis.reply("gemini", "not json", "still not json", "never json")
    fake_clis.reply("claude", SCRIPT)
    project = cli_project(make_project, ["gemini-cli", "claude-cli"])

    assert main(["run", str(project), "--until", "script"]) == 0

    assert len(fake_clis.calls("gemini")) == 3
    assert read_json(project / "build" / "script.json")["lines"][0]["text"] == LINES[0]


def test_the_chain_moves_on_when_a_cli_is_not_installed(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    fake_clis.reply("claude", SCRIPT)
    fake_clis.uninstall("codex")
    project = cli_project(make_project, ["codex-cli", "claude-cli"])

    assert main(["run", str(project), "--until", "script"]) == 0


def test_the_run_fails_clearly_when_every_provider_in_the_chain_fails(
    make_project: MakeProject, fake_clis: FakeClis, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_clis.fail("gemini", "429 rate limit")
    fake_clis.fail("claude", "boom", exit_code=2)
    project = cli_project(make_project, ["gemini-cli", "claude-cli"])

    assert main(["run", str(project), "--until", "script"]) == 1

    err = capsys.readouterr().err
    assert "gemini-cli" in err
    assert "claude-cli" in err
    assert not (project / "build" / "script.json").exists()


def test_script_and_storyboard_default_to_gemini_then_claude(
    make_project: MakeProject, fake_clis: FakeClis, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project()
    config = yaml.safe_load((project / "vidpipe.yaml").read_text(encoding="utf-8"))
    del config["providers"]["script"], config["providers"]["storyboard"]
    text: str = yaml.safe_dump(config)  # pyright: ignore[reportUnknownMemberType]
    (project / "vidpipe.yaml").write_text(text, encoding="utf-8")

    assert main(["plan", str(project), "--until", "storyboard"]) == 0

    out = capsys.readouterr().out
    assert "gemini-cli > claude-cli" in out


def test_an_unknown_provider_in_a_chain_is_a_plan_problem(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = cli_project(make_project, ["gemini-cli", "no-such-cli"])

    assert main(["plan", str(project)]) == 1

    assert "no-such-cli" in capsys.readouterr().err


def test_fake_text_provider_still_drives_the_offline_pipeline(make_project: MakeProject) -> None:
    project = make_project()

    assert run_until_storyboard(project) == 0

    shots = read_json(project / "build" / "storyboard.json")["shots"]
    assert {s["motion_type"] for s in shots} <= {"push_in", "pan", "ambient"}


def test_a_chain_written_as_a_mapping_passes_options_to_each_provider(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    fake_clis.fail("gemini", "quota exceeded")
    fake_clis.reply("claude", SCRIPT)
    script = {
        "name": "gemini-cli",
        "fallback": [{"name": "claude-cli", "options": {"model": "sonnet"}}],
    }
    project = cli_project(make_project, script)

    assert main(["run", str(project), "--until", "script"]) == 0

    argv = fake_clis.calls("claude")[0].argv
    assert argv[argv.index("--model") + 1] == "sonnet"


def test_the_ledger_records_which_provider_answered_and_the_fallback_applied(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    fake_clis.fail("gemini", "429 RESOURCE_EXHAUSTED: quota exceeded")
    fake_clis.reply("claude", SCRIPT)
    project = cli_project(make_project, ["gemini-cli", "claude-cli"])

    assert main(["run", str(project), "--until", "script"]) == 0

    record = read_json(project / "build" / "ledger.json")["artifacts"]["script"]
    assert record["provider"] == "gemini-cli > claude-cli"
    assert "gemini-cli" in record["fallback"]
    assert "claude-cli" in record["fallback"]
    assert "quota exceeded" in record["fallback"]


def test_no_fallback_is_recorded_when_the_first_provider_answers(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    fake_clis.reply("gemini", SCRIPT)
    project = cli_project(make_project, ["gemini-cli", "claude-cli"])

    assert main(["run", str(project), "--until", "script"]) == 0

    assert read_json(project / "build" / "ledger.json")["artifacts"]["script"]["fallback"] is None


def test_reordering_the_chain_regenerates_the_script(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    fake_clis.reply("gemini", SCRIPT)
    fake_clis.reply("claude", json.dumps({"lines": ["Claude wrote this line."]}))
    project = cli_project(make_project, ["gemini-cli", "claude-cli"])
    assert main(["run", str(project), "--until", "script"]) == 0

    config_file = project / "vidpipe.yaml"
    config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    config["providers"]["script"] = ["claude-cli", "gemini-cli"]
    text: str = yaml.safe_dump(config)  # pyright: ignore[reportUnknownMemberType]
    config_file.write_text(text, encoding="utf-8")
    assert main(["run", str(project), "--until", "script"]) == 0

    script = read_json(project / "build" / "script.json")
    assert [line["text"] for line in script["lines"]] == ["Claude wrote this line."]
