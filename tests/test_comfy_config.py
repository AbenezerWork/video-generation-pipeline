"""Seam 1 (configuring ComfyUI providers): plan checks, options in ``vidpipe.yaml``, what
invalidates a keyframe, and adding a model as a workflow plus a mapping file, without Python."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import MakeProject
from tests.fake_comfyui import FakeComfyUI
from tests.test_keyframes_bible import comfy_project, ledger, read_json, run_keyframes
from vidpipe.cli import main


def edit_config(project: Path, **changes: Any) -> None:
    path = project / "vidpipe.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config.update(changes)
    path.write_text(yaml.safe_dump(config), encoding="utf-8")  # pyright: ignore


def set_keyframer_options(project: Path, **options: Any) -> None:
    config = yaml.safe_load((project / "vidpipe.yaml").read_text(encoding="utf-8"))
    config["providers"]["keyframes"]["options"].update(options)
    edit_config(project, providers=config["providers"])


@pytest.mark.parametrize(
    ("size", "complaint"),
    [
        ((832, 470), "height 470 is not a multiple of 16"),
        ((840, 480), "width 840 is not a multiple of 16"),
        ((160, 96), "width 160 is outside 256-1280"),
        ((1280, 1280), "more than 921600 pixels"),
    ],
)
def test_plan_refuses_a_keyframe_size_the_model_cannot_draw(
    make_project: MakeProject,
    comfy: FakeComfyUI,
    capsys: pytest.CaptureFixture[str],
    size: tuple[int, int],
    complaint: str,
) -> None:
    project = comfy_project(make_project, comfy, width=size[0], height=size[1])

    assert main(["plan", str(project), "--until", "keyframes"]) == 1

    assert complaint in capsys.readouterr().err
    assert run_keyframes(project) == 1
    assert comfy.requests == [] and not (project / "build").exists()


def test_plan_prices_comfyui_keyframes_in_gpu_minutes_without_contacting_comfyui(
    make_project: MakeProject, comfy: FakeComfyUI, capsys: pytest.CaptureFixture[str]
) -> None:
    project = comfy_project(make_project, comfy)
    assert main(["run", str(project), "--until", "storyboard"]) == 0
    capsys.readouterr()

    assert main(["plan", str(project), "--json", "--until", "keyframes"]) == 0

    report = json.loads(capsys.readouterr().out)
    keyframes = next(s for s in report["stages"] if s["stage"] == "keyframes")
    assert keyframes["gpu_minutes"] == pytest.approx(3 * 0.11)
    assert comfy.requests == []


def test_a_providers_own_url_wins_over_the_projects(
    make_project: MakeProject, comfy: FakeComfyUI
) -> None:
    project = comfy_project(
        make_project, comfy, options={"url": comfy.url}, comfyui={"url": "http://127.0.0.1:1"}
    )

    assert run_keyframes(project) == 0

    assert len(comfy.jobs) == 3


def test_moving_comfyui_or_changing_the_waiting_options_redraws_nothing(
    make_project: MakeProject, comfy: FakeComfyUI
) -> None:
    project = comfy_project(make_project, comfy)
    assert run_keyframes(project) == 0

    elsewhere = FakeComfyUI().start()
    try:
        edit_config(project, comfyui={"url": elsewhere.url})
        set_keyframer_options(project, retries=5, timeout_s=100, url=elsewhere.url)
        assert run_keyframes(project) == 0
        assert elsewhere.requests == []
    finally:
        elsewhere.stop()


def test_changing_a_setting_redraws_the_keyframes_with_it(
    make_project: MakeProject, comfy: FakeComfyUI
) -> None:
    project = comfy_project(make_project, comfy)
    assert run_keyframes(project) == 0

    set_keyframer_options(project, settings={"reference_megapixels": 0.25, "steps": 6})
    assert run_keyframes(project) == 0

    redrawn = comfy.jobs[3:]
    assert len(redrawn) == 3
    assert {job.input("ref1_scale", "megapixels") for job in redrawn} == {0.25}
    assert {job.input("sched", "steps") for job in redrawn} == {6}


def test_redo_draws_one_shot_again_with_a_new_seed(
    make_project: MakeProject, comfy: FakeComfyUI
) -> None:
    project = comfy_project(make_project, comfy)
    assert run_keyframes(project) == 0

    assert main(["redo", "shot", "2", str(project), "--until", "keyframes"]) == 0

    assert len(comfy.jobs) == 4
    assert comfy.jobs[3].input("noise", "noise_seed") != 2


# ------------------------------------------------------------- a model added without any Python

#: A made-up single-reference model: different node ids, no scheduler, its own limits and cost.
GRAPH = {
    "words": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
    "dice": {"class_type": "RandomNoise", "inputs": {"noise_seed": 0}},
    "photo": {"class_type": "LoadImage", "inputs": {"image": "x.png"}},
    "canvas": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512}},
    "writer": {
        "class_type": "SaveImage",
        "inputs": {"images": ["canvas", 0], "filename_prefix": "other"},
    },
}
FIELDS: dict[str, list[str]] = {
    "prompt": ["words.inputs.text"],
    "seed": ["dice.inputs.noise_seed"],
    "width": ["canvas.inputs.width"],
    "height": ["canvas.inputs.height"],
    "filename_prefix": ["writer.inputs.filename_prefix"],
}
MAPPING: dict[str, Any] = {
    "name": "my-model",
    "variants": [{"images": 1, "workflow": "my_model.json"}],
    "images": ["photo.inputs.image"],
    "fields": FIELDS,
    "outputs": {"node": "writer"},
    "capabilities": {"max_width": 1024, "width_multiple": 16, "height_multiple": 16},
    "cost": {"gpu_minutes": 2.0},
}


def add_model(project: Path, mapping: dict[str, Any] = MAPPING) -> None:
    folder = project / "models"
    folder.mkdir()
    (folder / "my_model.json").write_text(json.dumps(GRAPH), encoding="utf-8")
    (folder / "my_model.yaml").write_text(json.dumps(mapping), encoding="utf-8")


def test_a_workflow_and_mapping_in_the_project_add_a_model(
    make_project: MakeProject, comfy: FakeComfyUI, capsys: pytest.CaptureFixture[str]
) -> None:
    project = comfy_project(make_project, comfy, options={"workflow": "models/my_model.yaml"})
    add_model(project)

    assert run_keyframes(project) == 0

    assert [job.input("dice", "noise_seed") for job in comfy.jobs] == [1, 2, 3]
    assert all(len(job.images) == 1 for job in comfy.jobs)
    assert ledger(project)["keyframes/shot_01"]["data"]["workflow"] == "my_model.json"
    capsys.readouterr()
    assert main(["plan", str(project), "--json", "--until", "keyframes"]) == 0
    stages = json.loads(capsys.readouterr().out)["stages"]
    assert next(s for s in stages if s["stage"] == "keyframes")["gpu_minutes"] == 6.0

    # Editing the workflow redraws what it made.
    path = project / "models" / "my_model.json"
    graph = read_json(path)
    graph["canvas"]["inputs"]["batch_size"] = 1
    path.write_text(json.dumps(graph), encoding="utf-8")
    assert run_keyframes(project) == 0
    assert len(comfy.jobs) == 6


#: Changes that break the mapping, and what the report must name.
BROKEN: list[tuple[dict[str, Any], str]] = [
    ({"fields": {**FIELDS, "seed": ["dice.inputs.nope"]}}, "dice.inputs.nope"),
    ({"fields": {k: v for k, v in FIELDS.items() if k != "seed"}}, "'seed'"),
    ({"outputs": {"node": "nowhere"}}, "output node 'nowhere'"),
    ({"settings": {"strength": 1}}, "unmapped fields: ['strength']"),
    ({"variants": [{"images": 1, "workflow": "gone.json"}]}, "gone.json"),
    ({"variants": [{"images": 1, "workflow": "my_model.json"}] * 2}, "same number of images"),
]


@pytest.mark.parametrize(("change", "complaint"), BROKEN)
def test_a_mapping_that_does_not_match_its_workflow_is_a_plan_problem(
    make_project: MakeProject,
    comfy: FakeComfyUI,
    capsys: pytest.CaptureFixture[str],
    change: dict[str, Any],
    complaint: str,
) -> None:
    project = comfy_project(make_project, comfy, options={"workflow": "models/my_model.yaml"})
    add_model(project, {**MAPPING, **change})

    assert main(["plan", str(project), "--until", "keyframes"]) == 1

    assert complaint in capsys.readouterr().err


@pytest.mark.parametrize(
    ("options", "complaint"),
    [
        ({"workflow": "no_such_model"}, "keyframe_flux2_klein_4b"),
        ({"settings": {"megapixels": 1}}, "megapixels"),
        ({"url": "localhost:8188"}, "http://"),
        ({"retrys": 1}, "retrys"),
    ],
)
def test_a_wrong_option_is_a_plan_problem(
    make_project: MakeProject,
    comfy: FakeComfyUI,
    capsys: pytest.CaptureFixture[str],
    options: dict[str, Any],
    complaint: str,
) -> None:
    project = comfy_project(make_project, comfy, options=options)

    assert main(["plan", str(project), "--until", "keyframes"]) == 1

    assert complaint in capsys.readouterr().err
