"""Exercise the video stage's artifact and failure handling with a fake ComfyUI."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.cli_text_fixtures import FakeClis
from tests.conftest import MakeProject, ffprobe
from tests.fake_comfyui import WRITERS, FakeComfyUI, Job
from tests.test_fit_plan import project_with_script
from tests.test_keyframes_bible import ledger
from vidpipe.assembly import find_tool
from vidpipe.cli import main
from vidpipe.models import MediaIndex
from vidpipe.project import Project


def _save_video(job: Job, uploads: dict[str, bytes]) -> tuple[str, str, bytes]:
    width, height = job.size()
    fps = job.input("video", "fps")
    frames = job.input("trim", "length")
    colour = job.identity(uploads)[:3].hex()
    ffmpeg = find_tool("ffmpeg")
    assert ffmpeg is not None
    mp4 = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x{colour}:s={width}x{height}:r={fps}",
            "-vf",
            "drawbox=x=0:y=0:w=64:h=64:color=white:t=fill:enable='gt(n,0)'",
            "-frames:v",
            str(frames),
            "-c:v",
            "libx264",
            "-movflags",
            "frag_keyframe+empty_moov",
            "-f",
            "mp4",
            "-",
        ],
        capture_output=True,
        check=True,
        timeout=15,
    ).stdout
    return "images", ".mp4", mp4


def rgb_frame(path: Path, number: int) -> bytes:
    ffmpeg = find_tool("ffmpeg")
    assert ffmpeg is not None
    result = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            f"select='eq(n,{number})'",
            "-frames:v",
            "1",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=True,
        timeout=15,
    )
    assert result.stdout
    return result.stdout


@pytest.mark.needs_ffmpeg
def test_video_oom_reduces_resolution_and_resume_keeps_the_completed_clip(
    make_project: MakeProject,
    comfy: FakeComfyUI,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setitem(WRITERS, "SaveVideo", _save_video)
    root = make_project(
        providers={"video": {"name": "comfyui-i2v", "options": {"retries": 0, "poll_s": 0.01}}},
        comfyui={"url": comfy.url},
    )
    args = [str(root), "--until", "video", "--auto"]
    comfy.script("oom", "success", "error")
    assert main(["run", *args]) == 1
    assert "video for shot 2" in capsys.readouterr().err

    first = ledger(root)["video/shot_01"]
    assert first["fallback"].startswith("out-of-memory step-down (size 640x352 -> 512x288)")
    assert first["data"]["seed"] != first["seed"]
    assert first["gpu_seconds"] == pytest.approx(2 * comfy.job_seconds)
    assert "video/shot_02" not in ledger(root)
    clip = ffprobe(root / "build" / "video" / "shot_01.mp4")["streams"][0]
    assert (clip["width"], clip["height"]) == (512, 288)
    assert float(clip["duration"]) == pytest.approx(first["parameters"]["duration_s"])
    assert comfy.freed and not comfy.running

    assert main(["run", *args]) == 0
    assert len(comfy.jobs) == 5
    assert ledger(root)["video/shot_01"] == first
    assert ledger(root)["video/shot_02"]["fallback"] is None


@pytest.mark.needs_ffmpeg
def test_continuation_resumes_from_the_last_frame_after_two_ooms(
    make_project: MakeProject,
    comfy: FakeComfyUI,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setitem(WRITERS, "SaveVideo", _save_video)
    root = project_with_script(
        make_project,
        [
            "The herder watches his goats.",
            "The goats step over the rocks and graze. The goats wander through the long grass.",
            "He brews the first coffee.",
        ],
        providers={"video": {"name": "comfyui-i2v", "options": {"poll_s": 0.01}}},
        comfyui={"url": comfy.url},
    )
    args = [str(root), "--until", "video", "--auto"]
    key = "video/shot_02_clip_01"
    comfy.script("success", "success", "oom", "oom")
    assert main(["run", *args]) == 1
    error = capsys.readouterr().err
    assert "shot 2 continuation 1" in error
    assert "out of memory again after the step-down (size 640x352 -> 512x288)" in error
    assert len(comfy.jobs) == 4 and not comfy.running
    first_records = ledger(root)
    assert key not in first_records

    comfy.script("oom", "success")
    assert main(["run", *args]) == 0
    assert len(comfy.jobs) == 7
    project = Project(root)
    index = project.read_model("video.json", MediaIndex)
    first = project.build / index.for_clip(2, "shared", 0)
    next_clip = project.build / index.for_clip(2, "shared", 1)
    uploaded = tmp_path / "condition.png"
    uploaded.write_bytes(comfy.uploads[comfy.jobs[5].images[0]])
    last = round(float(ffprobe(first)["streams"][0]["duration"]) * 24) - 1
    assert rgb_frame(uploaded, 0) == rgb_frame(first, last)
    assert rgb_frame(uploaded, 0) != rgb_frame(first, 0)

    records = ledger(root)
    for completed in ("video/shot_01", "video/shot_02"):
        assert records[completed] == first_records[completed]
    record = records[key]
    dependency = f"file:build/{index.for_clip(2, 'shared', 0)}"
    assert record["inputs"][dependency] == records["video/shot_02"]["outputs"][0]["sha256"]
    assert record["fallback"].count("step-down") == 1
    assert [a["outcome"] for a in record["data"]["attempts"]] == ["out_of_memory", "ok"]
    assert record["data"]["seed"] != record["seed"]
    normal = comfy.jobs[4].graph
    reduced = comfy.jobs[5].graph
    changed = {
        f"{node}.{field}"
        for node, spec in normal.items()
        for field, value in spec["inputs"].items()
        if reduced[node]["inputs"][field] != value
    }
    assert changed == {"latent.width", "latent.height", "sample.seed", "save.filename_prefix"}
    stream = ffprobe(next_clip)["streams"][0]
    assert (stream["width"], stream["height"], stream["avg_frame_rate"]) == (512, 288, "24/1")
    assert float(stream["duration"]) == pytest.approx(record["parameters"]["duration_s"])


@pytest.mark.needs_ffmpeg
def test_a_portrait_video_steps_down_to_a_smaller_portrait_size(
    make_project: MakeProject, comfy: FakeComfyUI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(WRITERS, "SaveVideo", _save_video)
    settings = {"width": 352, "height": 640}
    root = make_project(
        providers={
            "video": {
                "name": "comfyui-i2v",
                "options": {"retries": 0, "poll_s": 0.01, "settings": settings},
            }
        },
        comfyui={"url": comfy.url},
    )
    comfy.script("oom")

    assert main(["run", str(root), "--until", "video", "--auto"]) == 0

    first = ledger(root)["video/shot_01"]
    assert first["fallback"].startswith("out-of-memory step-down (size 352x640 -> 288x512)")
    clip = ffprobe(root / "build" / "video" / "shot_01.mp4")["streams"][0]
    assert (clip["width"], clip["height"]) == (288, 512)


@pytest.mark.parametrize(
    ("settings", "accepted"),
    [
        ({"width": 352, "height": 640}, True),  # portrait, same pixels as 640x352
        ({"width": 480, "height": 832}, True),
        ({"width": 832, "height": 832}, False),  # each side fits, the pixels do not
    ],
)
def test_the_video_size_budget_allows_either_orientation(
    make_project: MakeProject,
    capsys: pytest.CaptureFixture[str],
    settings: dict[str, int],
    accepted: bool,
) -> None:
    root = make_project(
        providers={"video": {"name": "comfyui-i2v", "options": {"settings": settings}}}
    )

    main(["plan", str(root)])

    err = capsys.readouterr().err
    assert ("video size" not in err and "multiple of 32" not in err) is accepted


@pytest.mark.needs_ffmpeg
def test_the_video_model_is_told_what_moves_and_how_the_camera_moves_not_the_picture(
    make_project: MakeProject,
    comfy: FakeComfyUI,
    fake_clis: FakeClis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(WRITERS, "SaveVideo", _save_video)
    shots = [
        {"line_id": 1, "visual": "Wide shot of a herder on a misty ridge", "motion_type": "pan",
         "movement": "The man walks slowly to the right; mist drifts"},
        {"line_id": 2, "visual": "Close-up of a goat grazing", "motion_type": "ambient",
         "movement": "The goat chews slowly and flicks an ear."},
        {"line_id": 3, "visual": "A steaming cup of coffee", "motion_type": "push_in"},
    ]  # fmt: skip
    fake_clis.reply("claude", json.dumps({"shots": shots}))
    root = make_project(
        providers={
            "storyboard": "claude-cli",
            "video": {"name": "comfyui-i2v", "options": {"poll_s": 0.01}},
        },
        comfyui={"url": comfy.url},
    )

    assert main(["run", str(root), "--until", "video", "--auto"]) == 0

    positive = [job.input("positive", "text") for job in comfy.jobs]
    negative = [job.input("negative", "text") for job in comfy.jobs]
    assert positive[0].startswith("The man walks slowly to the right; mist drifts. The camera pans")
    assert "misty ridge" not in positive[0]  # the keyframe already shows the picture
    assert "fixed focal length" in positive[0] and "keep their shape" in positive[0]
    assert positive[1].startswith("The goat chews slowly and flicks an ear. Fixed camera")
    # An older storyboard with no movement falls back to its visual.
    assert positive[2].startswith("A steaming cup of coffee. The camera pushes in")
    assert all("背景人很多" in n for n in negative)  # Wan's own: "many people in the background"
    assert negative[0].endswith("zoom in, zoom out, dolly in, push in")
    assert negative[1].endswith("camera movement, zoom, pan, camera shake")
    assert negative[2].endswith("pan, sideways camera movement, fast zoom")
