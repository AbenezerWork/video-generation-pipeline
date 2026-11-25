"""Seam 1 (the project bible and the keyframe stage): pipeline runs on a project directory.

Observed through what a run leaves behind (keyframes, ``build/ledger.json``), what the fake ComfyUI
server received over HTTP, and what ``vidpipe`` reports.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from tests.cli_text_fixtures import FakeClis
from tests.conftest import SAMPLE, MakeProject
from tests.fake_comfyui import FakeComfyUI
from vidpipe.cli import main

PROTAGONIST = SAMPLE / "bible" / "protagonist.jpg"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ledger(project: Path) -> dict[str, Any]:
    return read_json(project / "build" / "ledger.json")["artifacts"]


def comfy_project(
    make_project: MakeProject,
    comfy: FakeComfyUI,
    options: dict[str, Any] | None = None,
    **config: Any,
) -> Path:
    """The sample project with its keyframes drawn on the (fake) ComfyUI at 832x480."""
    selection = {"name": "comfyui-keyframer", "options": {"poll_s": 0.01, **(options or {})}}
    values: dict[str, Any] = {"comfyui": {"url": comfy.url}, "width": 832, "height": 480}
    return make_project(providers={"keyframes": selection}, **{**values, **config})


def run_keyframes(project: Path) -> int:
    return main(["run", str(project), "--until", "keyframes"])


def png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    assert header.startswith(b"\x89PNG")
    return int.from_bytes(header[16:20]), int.from_bytes(header[20:24])


def test_every_shot_gets_a_keyframe_drawn_with_the_bibles_character_reference(
    make_project: MakeProject, comfy: FakeComfyUI
) -> None:
    project = comfy_project(make_project, comfy)

    assert run_keyframes(project) == 0

    items = read_json(project / "build" / "keyframes.json")["items"]
    assert [i["shot_id"] for i in items] == [1, 2, 3]
    assert {png_size(project / "build" / i["path"]) for i in items} == {(832, 480)}
    # One job per shot, each with the protagonist's picture uploaded as "image 1".
    assert len(comfy.jobs) == 3
    for job in comfy.jobs:
        (image,) = job.images
        assert comfy.uploads[image] == PROTAGONIST.read_bytes()
        assert job.input("ref1_scale", "megapixels") == 0.5
        assert "image 1" in job.input("text", "text")
    sha = hashlib.sha256(PROTAGONIST.read_bytes()).hexdigest()
    for shot in (1, 2, 3):
        record = ledger(project)[f"keyframes/shot_{shot:02d}"]
        assert record["provider"] == "comfyui-keyframer"
        assert record["seed"] == record["data"]["seed"] == shot
        assert record["fallback"] is None
        assert record["gpu_seconds"] == 2.5  # what ComfyUI's timestamps say
        assert record["data"]["references"] == [
            {"id": "protagonist", "path": "bible/protagonist.jpg", "sha256": sha}
        ]
        assert record["data"]["settings"]["reference_megapixels"] == 0.5
        assert (record["data"]["settings"]["width"], record["data"]["settings"]["height"]) == (
            832,
            480,
        )
    # ComfyUI is told to free the GPU once the stage is done, and nothing stays queued.
    assert comfy.freed == [{"unload_models": True, "free_memory": True}]
    assert comfy.running == []


def test_a_second_run_leaves_comfyui_alone(make_project: MakeProject, comfy: FakeComfyUI) -> None:
    project = comfy_project(make_project, comfy)
    assert run_keyframes(project) == 0
    comfy.requests.clear()

    assert run_keyframes(project) == 0

    assert comfy.requests == []


# ---------------------------------------------------------------------------------- the bible

#: Two characters, a location with a picture, one without, and a style picture.
CAST = {
    "style": {"description": "Flat gouache poster art", "reference": "bible/style.png"},
    "characters": [
        {"id": "aster", "name": "Aster", "description": "A girl in an indigo dress",
         "reference": "bible/aster.png"},
        {"id": "dawit", "name": "Dawit", "description": "An old man with a white beard"},
    ],
    "locations": [
        {"id": "market", "name": "the market", "description": "Stalls under striped awnings",
         "reference": "bible/market.png"},
        {"id": "ridge", "name": "the ridge", "description": "A bare ridge above the clouds"},
    ],
}  # fmt: skip


def write_bible(project: Path, bible: dict[str, Any] = CAST) -> None:
    """Write ``bible`` and a distinct small picture for each reference it names."""
    entries = [bible.get("style", {}), *bible.get("characters", []), *bible.get("locations", [])]
    for entry in entries:
        if reference := entry.get("reference"):
            picture = project / reference
            picture.parent.mkdir(parents=True, exist_ok=True)
            picture.write_bytes(b"\x89PNG\r\n\x1a\n picture of " + reference.encode())
    (project / "bible.yaml").write_text(json.dumps(bible), encoding="utf-8")  # JSON is YAML


def cast_shots(project: Path, *casting: dict[str, str | None]) -> None:
    """Hand-edit the storyboard (after it was generated): who and where each shot shows."""
    path = project / "build" / "storyboard.json"
    storyboard = read_json(path)
    for shot, changes in zip(storyboard["shots"], casting, strict=True):
        shot.update(changes)
    path.write_text(json.dumps(storyboard), encoding="utf-8")


def drawn_with(comfy: FakeComfyUI) -> list[list[str]]:
    """For each job, the reference pictures it was given, in order."""
    return [
        [comfy.uploads[name].split(b"picture of ")[1].decode() for name in job.images]
        for job in comfy.jobs
    ]


def test_shots_get_their_characters_and_locations_pictures_up_to_the_models_two(
    make_project: MakeProject, comfy: FakeComfyUI
) -> None:
    project = comfy_project(make_project, comfy)
    write_bible(project)
    assert main(["run", str(project), "--until", "storyboard"]) == 0
    cast_shots(
        project,
        {"location": "market"},  # no character named: the protagonist
        {"character": "dawit", "location": "ridge"},  # neither has a picture
        {"character": "none"},  # nobody
    )

    assert run_keyframes(project) == 0

    assert drawn_with(comfy) == [
        ["bible/aster.png", "bible/market.png"],  # character first; no room for the style picture
        ["bible/style.png"],
        ["bible/style.png"],
    ]
    prompts = [job.input("text", "text") for job in comfy.jobs]
    assert "Aster, shown in image 1" in prompts[0] and "market" in prompts[0]
    assert "image 2" in prompts[0]
    # Without a picture the bible's words stand in.
    assert "An old man with a white beard" in prompts[1]
    assert "A bare ridge above the clouds" in prompts[1]
    assert "Aster" not in prompts[2]
    assert all("Flat gouache poster art" in p for p in prompts)
    recorded = ledger(project)["keyframes/shot_01"]["data"]
    assert [r["id"] for r in recorded["references"]] == ["aster", "market"]
    assert recorded["prompt"] == prompts[0]


def test_a_provider_that_takes_no_pictures_gets_the_bibles_descriptions(
    make_project: MakeProject,
) -> None:
    project = make_project(providers={"keyframes": "fake-keyframer-text-only"})

    assert run_keyframes(project) == 0

    record = ledger(project)["keyframes/shot_01"]["data"]
    assert record["references"] == []
    assert "A ten-year-old girl from a highland village" in record["prompt"]
    assert "image 1" not in record["prompt"]


def test_a_new_reference_picture_redraws_the_keyframes_and_nothing_before_them(
    make_project: MakeProject,
) -> None:
    project = make_project()
    assert main(["run", str(project), "--until", "music"]) == 0
    before = ledger(project)
    frame = (project / "build" / "keyframes" / "shot_01.png").read_bytes()
    picture = project / "bible" / "protagonist.jpg"
    picture.write_bytes(picture.read_bytes() + b"\x00")

    assert main(["run", str(project), "--until", "music"]) == 0

    after = ledger(project)
    changed = {k for k in after if after[k] != before[k]}
    assert changed == {f"{stage}/shot_0{n}" for stage in ("keyframes", "video") for n in (1, 2, 3)}
    assert (project / "build" / "keyframes" / "shot_01.png").read_bytes() != frame


def test_a_project_without_a_bible_draws_the_storyboards_description_alone(
    make_project: MakeProject,
) -> None:
    project = make_project()
    (project / "bible.yaml").unlink()

    assert run_keyframes(project) == 0

    shots = read_json(project / "build" / "storyboard.json")["shots"]
    record = ledger(project)["keyframes/shot_02"]["data"]
    assert (record["prompt"], record["references"]) == (shots[1]["visual"], [])


@pytest.mark.parametrize(
    ("bible", "complaint"),
    [
        ({"characters": [{"id": "aster", "reference": "bible/gone.png"}]}, "bible/gone.png"),
        ({"characters": [{"id": "aster"}]}, "a description, a reference image, or both"),
        ({"heroes": []}, "invalid bible"),
    ],
)
def test_a_bible_that_cannot_be_used_is_a_plan_problem(
    make_project: MakeProject,
    capsys: pytest.CaptureFixture[str],
    bible: dict[str, Any],
    complaint: str,
) -> None:
    project = make_project()
    (project / "bible.yaml").write_text(json.dumps(bible), encoding="utf-8")

    assert main(["plan", str(project), "--until", "keyframes"]) == 1
    assert complaint in capsys.readouterr().err
    assert run_keyframes(project) == 1
    assert not (project / "build").exists()


def test_a_shot_cast_with_someone_the_bible_does_not_know_stops_before_any_drawing(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project()
    assert main(["run", str(project), "--until", "storyboard"]) == 0
    cast_shots(project, {}, {"character": "nobody-here"}, {})
    capsys.readouterr()

    assert run_keyframes(project) == 1

    err = capsys.readouterr().err
    assert "shot 2" in err and "nobody-here" in err and "protagonist" in err
    assert not (project / "build" / "keyframes").exists()  # not even shot 1


def test_removing_a_place_from_the_bible_re_casts_the_storyboard(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    def storyboard(location: str | None) -> str:
        shots = [
            {"line_id": i, "visual": f"shot {i}", "motion_type": "pan", "location": location}
            for i in (1, 2, 3)
        ]
        return json.dumps({"shots": shots})

    fake_clis.reply("claude", storyboard("highlands"), storyboard(None))
    project = make_project(providers={"storyboard": "claude-cli"})
    assert run_keyframes(project) == 0
    bible = project / "bible.yaml"
    text = bible.read_text(encoding="utf-8")
    bible.write_text(text[: text.index("locations:")], encoding="utf-8")

    # The old storyboard names a place that is gone, but it is about to be written again.
    assert run_keyframes(project) == 0

    shots = read_json(project / "build" / "storyboard.json")["shots"]
    assert [s["location"] for s in shots] == [None, None, None]


def test_a_broken_bible_is_reported_before_the_script_is_written(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project()
    (project / "bible.yaml").write_text("characters: 3", encoding="utf-8")

    assert main(["run", str(project), "--until", "storyboard"]) == 1

    assert "invalid bible" in capsys.readouterr().err
    assert not (project / "build").exists()


def test_the_storyboarding_model_casts_the_shots_from_the_bible(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    def storyboard(location: str) -> str:
        shots = [
            {"line_id": 1, "visual": "a path", "motion_type": "pan", "location": location},
            {"line_id": 2, "visual": "goats", "motion_type": "ambient", "character": "none"},
            {"line_id": 3, "visual": "a cup", "motion_type": "push_in"},
        ]
        return json.dumps({"shots": shots})

    # The first answer names a place the bible does not have: it is asked again.
    fake_clis.reply("claude", storyboard("the-moon"), storyboard("highlands"))
    project = make_project(providers={"storyboard": "claude-cli"})

    assert run_keyframes(project) == 0

    shots = read_json(project / "build" / "storyboard.json")["shots"]
    assert [(s["character"], s["location"]) for s in shots] == [
        (None, "highlands"),
        ("none", None),
        (None, None),
    ]
    first, retry = fake_clis.calls("claude")
    assert "highlands" in first.stdin and "protagonist" in first.stdin
    assert "the-moon" in retry.stdin
    assert [r["id"] for r in ledger(project)["keyframes/shot_02"]["data"]["references"]] == []
