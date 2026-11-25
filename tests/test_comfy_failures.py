"""Seam 1 (failure handling): pipeline runs whose ComfyUI jobs fail on the fake server.

Retries with new seeds, the one out-of-memory step-down, what stops a run at once, and what is kept
for the next run. Observed through exit codes and messages, ``build/ledger.json`` and the HTTP
traffic the fake server received.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from tests.conftest import MakeProject
from tests.fake_comfyui import FakeComfyUI, Job
from tests.test_keyframes_bible import comfy_project, ledger, png_size, run_keyframes, write_bible
from vidpipe import pipeline
from vidpipe.cli import main


def seeds(comfy: FakeComfyUI) -> list[int]:
    return [job.input("noise", "noise_seed") for job in comfy.jobs]


def test_a_failed_job_is_retried_with_a_new_seed_and_the_record_says_so(
    make_project: MakeProject, comfy: FakeComfyUI
) -> None:
    comfy.script("error", "error", "success")
    project = comfy_project(make_project, comfy)

    assert run_keyframes(project) == 0

    first, second, third = seeds(comfy)[:3]
    assert first == 1 and len({first, second, third}) == 3
    record = ledger(project)["keyframes/shot_01"]
    assert record["seed"] == 1  # what the shot asked for
    assert record["data"]["seed"] == third  # what drew the picture
    assert [(a["seed"], a["outcome"]) for a in record["data"]["attempts"]] == [
        (first, "error"),
        (second, "error"),
        (third, "ok"),
    ]
    assert f"retry with new seed {second} after error" in record["fallback"]
    assert f"retry with new seed {third} after error" in record["fallback"]
    assert "something went wrong in the sampler" in record["fallback"]
    assert record["gpu_seconds"] == 3 * 2.5  # failed attempts used the GPU too
    # Retries change the seed and nothing else.
    assert record["data"]["settings"]["reference_megapixels"] == 0.5
    others = [ledger(project)[f"keyframes/shot_0{n}"]["fallback"] for n in (2, 3)]
    assert others == [None, None]


def test_after_two_retries_the_stage_fails_and_a_later_run_keeps_the_finished_shots(
    make_project: MakeProject, comfy: FakeComfyUI, capsys: pytest.CaptureFixture[str]
) -> None:
    comfy.script("success", "error", "error", "error")
    project = comfy_project(make_project, comfy)

    assert run_keyframes(project) == 1

    err = capsys.readouterr().err
    assert "shot 2" in err and "3 attempts" in err and "sampler" in err
    assert len(comfy.jobs) == 4  # shot 2 got exactly three attempts; shot 3 was not started
    assert [k for k in ledger(project) if k.startswith("keyframes/")] == ["keyframes/shot_01"]
    assert comfy.freed  # the GPU is released after a failure too

    assert run_keyframes(project) == 0

    assert [job.input("noise", "noise_seed") for job in comfy.jobs[4:]] == [2, 3]


def test_the_number_of_retries_is_configurable(
    make_project: MakeProject, comfy: FakeComfyUI
) -> None:
    comfy.script("error")
    project = comfy_project(make_project, comfy, options={"retries": 0})

    assert run_keyframes(project) == 1

    assert len(comfy.jobs) == 1


def test_out_of_memory_applies_one_recorded_step_down(
    make_project: MakeProject, comfy: FakeComfyUI
) -> None:
    comfy.script("oom", "success")
    project = comfy_project(make_project, comfy)

    assert run_keyframes(project) == 0

    failed, stepped = comfy.jobs[:2]
    assert failed.input("ref1_scale", "megapixels") == 0.5
    assert stepped.input("ref1_scale", "megapixels") == 0.25
    assert stepped.size() == failed.size() == (832, 480)  # one step only
    record = ledger(project)["keyframes/shot_01"]
    assert "out-of-memory step-down (reference_megapixels 0.5 -> 0.25)" in record["fallback"]
    assert record["data"]["settings"]["reference_megapixels"] == 0.25
    assert [a["outcome"] for a in record["data"]["attempts"]] == ["out_of_memory", "ok"]
    # Memory is freed before the second try (and once more when the stage ends).
    prompts = [i for i, call in enumerate(comfy.requests) if call == "POST /prompt"]
    assert "POST /free" in comfy.requests[prompts[0] : prompts[1]]
    # The step-down was for that job: the next shot starts at full quality again.
    assert comfy.jobs[2].input("ref1_scale", "megapixels") == 0.5
    assert ledger(project)["keyframes/shot_02"]["fallback"] is None


def test_running_out_of_memory_again_after_the_step_down_fails_the_stage(
    make_project: MakeProject, comfy: FakeComfyUI, capsys: pytest.CaptureFixture[str]
) -> None:
    comfy.script("success", "oom", "oom")
    project = comfy_project(make_project, comfy)

    assert run_keyframes(project) == 1

    err = capsys.readouterr().err
    assert "shot 2" in err and "out of memory again" in err
    assert "reference_megapixels 0.5 -> 0.25" in err
    assert len(comfy.jobs) == 3  # no third try, however many retries are left
    assert "keyframes/shot_01" in ledger(project)
    assert "keyframes/shot_02" not in ledger(project)


def test_without_references_the_step_down_is_the_next_smaller_size(
    make_project: MakeProject, comfy: FakeComfyUI
) -> None:
    comfy.script("oom")
    project = comfy_project(make_project, comfy)
    (project / "bible.yaml").unlink()

    assert run_keyframes(project) == 0

    assert [job.size() for job in comfy.jobs[:2]] == [(832, 480), (640, 352)]
    assert comfy.jobs[0].images == []
    record = ledger(project)["keyframes/shot_01"]
    assert "size 832x480 -> 640x352" in record["fallback"]
    assert png_size(project / "build" / "keyframes" / "shot_01.png") == (640, 352)
    assert png_size(project / "build" / "keyframes" / "shot_02.png") == (832, 480)


def test_a_step_down_that_would_change_nothing_is_passed_over(
    make_project: MakeProject, comfy: FakeComfyUI
) -> None:
    comfy.script("oom")
    project = comfy_project(
        make_project, comfy, options={"settings": {"reference_megapixels": 0.25}}
    )
    write_bible(project)

    assert run_keyframes(project) == 0

    assert [job.size() for job in comfy.jobs[:2]] == [(832, 480), (640, 352)]
    assert comfy.jobs[1].input("ref1_scale", "megapixels") == 0.25


def test_out_of_memory_with_nothing_left_to_lower_fails_at_once(
    make_project: MakeProject, comfy: FakeComfyUI, capsys: pytest.CaptureFixture[str]
) -> None:
    comfy.script("oom")
    project = comfy_project(make_project, comfy, width=640, height=352)
    (project / "bible.yaml").unlink()

    assert run_keyframes(project) == 1

    assert "no step-down left" in capsys.readouterr().err
    assert len(comfy.jobs) == 1


@pytest.mark.parametrize("failure", ["lost", "no_output"])
def test_a_lost_job_or_a_missing_output_is_retried(
    make_project: MakeProject, comfy: FakeComfyUI, failure: str
) -> None:
    comfy.script(failure)
    project = comfy_project(make_project, comfy)

    assert run_keyframes(project) == 0

    assert len(comfy.jobs) == 4
    assert "retry with new seed" in ledger(project)["keyframes/shot_01"]["fallback"]


def test_a_job_that_hangs_is_cancelled_in_comfyui_and_retried(
    make_project: MakeProject, comfy: FakeComfyUI
) -> None:
    comfy.script("hang")
    project = comfy_project(make_project, comfy, options={"timeout_s": 0.3})

    assert run_keyframes(project) == 0

    hung = comfy.jobs[0].prompt_id
    assert comfy.interrupted == [hung] and comfy.deleted == [hung]  # that job, nothing else
    assert comfy.running == []
    assert "timeout" in ledger(project)["keyframes/shot_01"]["fallback"]


def test_interrupting_a_run_takes_its_job_out_of_comfyuis_queue(
    make_project: MakeProject, comfy: FakeComfyUI, monkeypatch: pytest.MonkeyPatch
) -> None:
    comfy.script("success", "hang")
    project = comfy_project(make_project, comfy)

    def ctrl_c_while_waiting_for_shot_2(seconds: float) -> None:
        if len(comfy.jobs) == 2 and comfy.jobs[1].polls:
            raise KeyboardInterrupt

    monkeypatch.setattr(time, "sleep", ctrl_c_while_waiting_for_shot_2)

    with pytest.raises(KeyboardInterrupt):
        pipeline.run(project, until="keyframes")

    assert comfy.interrupted == [comfy.jobs[1].prompt_id]
    assert comfy.running == []
    assert comfy.freed
    assert "keyframes/shot_01" in ledger(project)


@pytest.mark.parametrize(
    ("outcome", "complaint"),
    [("reject", "rejected the workflow"), ("interrupted", "interrupted in ComfyUI")],
)
def test_what_a_new_seed_cannot_fix_fails_at_once(
    make_project: MakeProject,
    comfy: FakeComfyUI,
    capsys: pytest.CaptureFixture[str],
    outcome: str,
    complaint: str,
) -> None:
    comfy.script(outcome)
    project = comfy_project(make_project, comfy)

    assert run_keyframes(project) == 1

    assert complaint in capsys.readouterr().err
    assert comfy.requests.count("POST /prompt") == 1


def test_an_unreachable_comfyui_is_reported_with_its_address(
    make_project: MakeProject, comfy: FakeComfyUI, capsys: pytest.CaptureFixture[str]
) -> None:
    project = comfy_project(make_project, comfy, comfyui={"url": "http://127.0.0.1:1"})

    assert run_keyframes(project) == 1

    err = capsys.readouterr().err
    assert "cannot reach ComfyUI at http://127.0.0.1:1" in err and "comfyui.url" in err


def test_every_shot_can_fail_its_first_try_without_stopping_the_run(
    make_project: MakeProject, comfy: FakeComfyUI
) -> None:
    def first_try_fails(job: Job) -> str | None:
        return "error" if job.input("noise", "noise_seed") in (1, 2, 3) else None

    comfy.decide = first_try_fails
    project = comfy_project(make_project, comfy)

    assert main(["run", str(project), "--until", "keyframes"]) == 0

    assert len(comfy.jobs) == 6
    for shot in (1, 2, 3):
        assert ledger(project)[f"keyframes/shot_0{shot}"]["data"]["seed"] != shot


def test_a_retried_keyframe_is_not_drawn_again_by_the_next_run(
    make_project: MakeProject, comfy: FakeComfyUI
) -> None:
    comfy.script("error")
    project: Path = comfy_project(make_project, comfy)
    assert run_keyframes(project) == 0
    jobs = len(comfy.jobs)

    assert run_keyframes(project) == 0

    assert len(comfy.jobs) == jobs
