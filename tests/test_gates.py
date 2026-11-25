"""Seam 1 (gates, --auto and per-shot re-roll): the pipeline run through the CLI entry point.

A pause is observed as an exit code and message from ``vidpipe run``; an approval is given with
``vidpipe approve`` or ``--approve`` (or an interactive answer when a terminal is attached).
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import MakeProject
from tests.recording import Recorder, RecordingRegistry
from vidpipe import pipeline
from vidpipe.assembly import Assembler, AssemblyJob
from vidpipe.cli import main
from vidpipe.contracts import ProviderKind

PAUSED = 3


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def stages_reported(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return [
        line.split()[0]
        for line in capsys.readouterr().out.splitlines()
        if line.split() and line.split()[0] in pipeline.STAGE_NAMES
    ]


def test_run_pauses_after_script_by_default_and_resumes_once_approved(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(gates=None)

    assert main(["run", str(project), "--until", "music"]) == PAUSED

    out = capsys.readouterr().out
    assert "script" in out and "approve" in out
    assert (project / "build" / "script.json").is_file()
    assert not (project / "build" / "storyboard.json").exists()

    assert main(["approve", str(project), "script"]) == 0
    assert main(["run", str(project), "--until", "music"]) == PAUSED  # now stops after storyboard
    assert (project / "build" / "storyboard.json").is_file()
    assert not (project / "build" / "keyframes.json").exists()


def test_resuming_after_approval_does_not_redo_finished_work(make_project: MakeProject) -> None:
    project = make_project(gates=["script"])
    paused = pipeline.run(project, until="music")
    assert paused.paused_at == "script"

    pipeline.approve(project, ["script"])
    recorder = Recorder()
    done = pipeline.run(project, until="music", registry=RecordingRegistry(recorder))

    assert done.paused_at is None
    assert len(recorder.of(ProviderKind.TEXT)) == 1  # the storyboard; the script is not rewritten
    assert [r.stage for r in done.manifest.stages][0:2] == ["brief", "script"]
    assert done.manifest.stages[1].skipped
    assert len(read_json(project / "build" / "video.json")["items"]) == 3


def test_the_gate_set_is_configurable(make_project: MakeProject) -> None:
    only_keyframes = make_project(gates=["keyframes"])
    result = pipeline.run(only_keyframes, until="music")
    assert result.paused_at == "keyframes"
    assert (only_keyframes / "build" / "keyframes.json").is_file()
    assert not (only_keyframes / "build" / "video.json").exists()


def test_no_gates_means_no_pause(make_project: MakeProject) -> None:
    project = make_project(gates=[])
    assert main(["run", str(project), "--until", "music"]) == 0


def test_unknown_gate_is_a_plan_problem(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(gates=["colour-grade"])

    assert main(["run", str(project), "--until", "music"]) == 1

    assert "colour-grade" in capsys.readouterr().err
    assert not (project / "build").exists()


def test_auto_runs_end_to_end_without_pausing(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(gates=None)

    assert main(["run", str(project), "--until", "music", "--auto"]) == 0

    assert stages_reported(capsys) == [
        "brief", "script", "translation", "storyboard", "narration",
        "fit-planning", "keyframes", "video", "music",
    ]  # fmt: skip
    assert not (project / "build" / "approvals.json").exists()  # nothing was approved


def test_approve_flag_passes_a_gate_in_the_same_run(make_project: MakeProject) -> None:
    project = make_project(gates=None)

    code = main(
        ["run", str(project), "--until", "music"]
        + ["--approve", "script", "--approve", "storyboard", "--approve", "keyframes"]
    )

    assert code == 0
    assert (project / "build" / "music.json").is_file()


def test_the_final_stage_of_a_partial_run_does_not_pause(make_project: MakeProject) -> None:
    project = make_project(gates=None)

    assert main(["run", str(project), "--until", "script"]) == 0


def test_changing_what_a_gate_approved_asks_again(make_project: MakeProject) -> None:
    project = make_project(gates=["script"])
    pipeline.run(project, until="music")
    pipeline.approve(project, ["script"])
    assert pipeline.run(project, until="music").paused_at is None

    script_path = project / "build" / "script.json"
    script = read_json(script_path)
    script["lines"][0]["text"] = "A hand-edited opening line."
    script_path.write_text(json.dumps(script), encoding="utf-8")

    assert pipeline.run(project, until="music").paused_at == "script"


def test_approving_a_stage_that_has_not_run_is_an_error(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project()

    assert main(["approve", str(project), "keyframes"]) == 1
    assert "keyframes" in capsys.readouterr().err


def test_a_terminal_user_is_asked_at_the_gate(
    make_project: MakeProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    project = make_project(gates=["script"])
    monkeypatch.setattr(sys, "stdin", Tty("n\ny\n"))
    monkeypatch.setattr(sys, "stdout", Tty())

    assert main(["run", str(project), "--until", "music"]) == PAUSED  # answered "n"
    assert main(["run", str(project), "--until", "music"]) == 0  # answered "y"


# ------------------------------------------------------------------------------------- redo


class StubAssembler(Assembler):
    """Stands in for ffmpeg so redo's downstream assembly is observable without it."""

    def __init__(self) -> None:
        self.rendered: list[str] = []

    def problems(self) -> list[str]:
        return []

    def assemble(self, job: AssemblyJob) -> list[Path]:
        written: list[Path] = []
        for render in job.renders:
            render.output.parent.mkdir(parents=True, exist_ok=True)
            render.output.write_bytes(f"{render.language}:{len(render.segments)}".encode())
            self.rendered.append(render.language)
            written.append(render.output)
        return written


def ledger(project: Path) -> dict[str, Any]:
    return read_json(project / "build" / "ledger.json")["artifacts"]


def test_redo_regenerates_one_shot_and_its_assembly_and_nothing_else(
    make_project: MakeProject,
) -> None:
    project = make_project()
    assembler = StubAssembler()
    pipeline.run(project, assembler=assembler)
    before = ledger(project)
    shot_2_keyframe = (project / "build" / "keyframes" / "shot_02.png").read_bytes()

    assembler.rendered.clear()
    recorder = Recorder()
    result = pipeline.redo(
        project, shot=2, assembler=assembler, registry=RecordingRegistry(recorder)
    )

    assert result.paused_at is None
    assert [c.output_stem for c in recorder.of(ProviderKind.KEYFRAMER)] == ["shot_02"]
    assert [c.output_stem for c in recorder.of(ProviderKind.IMAGE_TO_VIDEO)] == ["shot_02"]
    for untouched in (ProviderKind.TEXT, ProviderKind.TRANSLATION, ProviderKind.TTS):
        assert recorder.of(untouched) == []
    assert recorder.of(ProviderKind.MUSIC) == []
    assert sorted(assembler.rendered) == ["am", "en"]  # the shot is in both renders

    after = ledger(project)
    changed = {k for k in after if after[k] != before[k]}
    assert changed == {"keyframes/shot_02", "video/shot_02", "assembly/en", "assembly/am"}
    # The re-roll really is a different result with a recorded new seed.
    assert after["keyframes/shot_02"]["seed"] != before["keyframes/shot_02"]["seed"]
    assert after["video/shot_02"]["seed"] != before["video/shot_02"]["seed"]
    assert (project / "build" / "keyframes" / "shot_02.png").read_bytes() != shot_2_keyframe


def test_every_redo_uses_a_new_seed_and_a_plain_run_keeps_it(make_project: MakeProject) -> None:
    project = make_project()
    pipeline.run(project, until="music")
    seeds = [ledger(project)["keyframes/shot_02"]["seed"]]

    for _ in range(2):
        pipeline.redo(project, shot=2, until="music")
        seeds.append(ledger(project)["keyframes/shot_02"]["seed"])
    assert len(set(seeds)) == 3

    recorder = Recorder()
    pipeline.run(project, until="music", registry=RecordingRegistry(recorder))
    assert recorder.calls == []
    assert ledger(project)["keyframes/shot_02"]["seed"] == seeds[-1]


def test_redo_through_the_cli(make_project: MakeProject) -> None:
    project = make_project()
    assert main(["run", str(project), "--until", "music"]) == 0
    before = ledger(project)

    assert main(["redo", "shot", "3", str(project), "--until", "music"]) == 0

    after = ledger(project)
    assert {k for k in after if after[k] != before[k]} == {"keyframes/shot_03", "video/shot_03"}


def test_redo_of_a_missing_shot_is_an_error(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project()
    assert main(["redo", "shot", "1", str(project)]) == 1  # nothing has run yet
    assert "storyboard" in capsys.readouterr().err

    assert main(["run", str(project), "--until", "music"]) == 0
    assert main(["redo", "shot", "9", str(project)]) == 1
    assert "shot 9" in capsys.readouterr().err
    assert read_json(project / "build" / "ledger.json")["rerolls"] == {}  # nothing was re-rolled


def test_a_redone_shot_stops_at_the_keyframes_gate_for_a_fresh_look(
    make_project: MakeProject,
) -> None:
    project = make_project(gates=["keyframes"])
    assert main(["run", str(project), "--until", "music", "--approve", "keyframes"]) == 0
    before = ledger(project)

    assert main(["redo", "shot", "2", str(project), "--until", "music"]) == PAUSED
    assert ledger(project)["video/shot_02"] == before["video/shot_02"]  # not animated yet

    assert main(["approve", str(project), "keyframes"]) == 0
    assert main(["run", str(project), "--until", "music"]) == 0
    after = ledger(project)
    assert after["video/shot_02"] != before["video/shot_02"]
    assert after["video/shot_01"] == before["video/shot_01"]


def test_auto_runs_through_assembly_with_default_gates(make_project: MakeProject) -> None:
    project = make_project(gates=None)
    assembler = StubAssembler()

    result = pipeline.run(project, assembler=assembler, auto=True)

    assert result.paused_at is None
    assert result.manifest.stages[-1].stage == "assembly"
    assert sorted(assembler.rendered) == ["am", "en"]
