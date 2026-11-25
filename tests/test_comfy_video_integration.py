"""Run the real Wan 2.2 video stage on ComfyUI using the bundled FLUX keyframes."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.conftest import MakeProject, ffprobe
from tests.test_assembly import gray_frame
from tests.test_fit_plan import project_with_script
from tests.test_keyframes_bible import ledger
from vidpipe.assembly import find_tool
from vidpipe.cli import main
from vidpipe.comfy import ComfyClient
from vidpipe.models import FitPlan, MediaIndex, Storyboard
from vidpipe.project import Project

pytestmark = [pytest.mark.integration, pytest.mark.needs_ffmpeg]


def decoded_hashes(path: Path) -> list[str]:
    ffmpeg = find_tool("ffmpeg")
    assert ffmpeg is not None
    hashes = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-an", "-f", "framemd5", "-"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout.splitlines()
    return [line.rsplit(",", 1)[-1] for line in hashes if not line.startswith("#")]


def test_wan_animates_the_sample_project_and_records_gpu_time(make_project: MakeProject) -> None:
    root = project_with_script(
        make_project,
        [
            "High in the Ethiopian highlands, a young goat herder watched his flock.",
            "Goats danced by the coffee shrub.",
            "He brewed the first coffee.",
        ],
        providers={"keyframes": "comfyui-keyframer", "video": "comfyui-i2v"},
        width=832,
        height=480,
    )
    args = [str(root), "--until", "video", "--auto"]
    assert main(["run", *args]) == 0
    project = Project(root)
    fit = project.read_model("fit_plan.json", FitPlan)
    storyboard = project.read_model("storyboard.json", Storyboard)
    index = project.read_model("video.json", MediaIndex)
    records = ledger(root)

    assert len(fit.shots) == len(index.items) == len(storyboard.shots) == 3
    assert fit.shots[0].visual_sets["shared"].clips[0].seconds == 5
    for shot, timing in zip(storyboard.shots, fit.shots, strict=True):
        path = project.build / index.for_shot(shot.id)
        target = timing.visual_sets["shared"].clips[0].seconds
        record = records[f"video/shot_{shot.id:02d}"]
        stream = ffprobe(path)["streams"][0]
        assert stream["codec_name"] == "h264"
        assert stream["avg_frame_rate"] == "24/1"
        measured = float(stream["duration"])
        assert target - 0.000001 <= measured <= target + 1 / 24
        assert record["data"]["duration_s"] == pytest.approx(measured)
        assert record["data"]["motion_type"] == shot.motion_type.value
        assert record["gpu_seconds"] > 0

        assert len(set(decoded_hashes(path))) > 1

    assert main(["run", *args]) == 0
    assert ledger(root) == records
    assert ComfyClient().queued_ids() == []


def test_wan_continues_from_the_last_frame_and_assembles_the_join(
    make_project: MakeProject,
) -> None:
    root = project_with_script(
        make_project,
        [
            "The young herder watches his goats graze nearby. "
            "The goats move through the tall grass.",
            "The goats dance.",
            "He brews coffee.",
        ],
        providers={"keyframes": "comfyui-keyframer", "video": "comfyui-i2v"},
        languages=["en"],
        width=640,
        height=352,
        fps=24,
        subtitles={"burn_in": False},
    )
    project = Project(root)
    assert main(["run", str(root), "--until", "storyboard", "--auto"]) == 0
    storyboard = project.read_model("storyboard.json", Storyboard)
    project.write_model("storyboard.json", Storyboard(shots=storyboard.shots[:1]))
    args = [str(root), "--auto"]
    assert main(["run", *args]) == 0
    fit = project.read_model("fit_plan.json", FitPlan)
    index = project.read_model("video.json", MediaIndex)
    first, continuation = [project.build / index.for_clip(1, "shared", i) for i in range(2)]
    timing = fit.shots[0].languages["en"]
    assert len(index.items) == len(timing.clips) == 2

    first_stream, next_stream = [ffprobe(path)["streams"][0] for path in (first, continuation)]
    last_time = (int(first_stream["nb_frames"]) - 1) / 24
    last = gray_frame(first, last_time, (640, 352))
    start = gray_frame(continuation, 0, (640, 352))
    assert next_stream["avg_frame_rate"] == "24/1"
    assert sum(abs(a - b) for a, b in zip(last, start, strict=True)) / len(last) < 15

    render = root / "out" / "demo_en.mp4"
    assert float(ffprobe(render)["format"]["duration"]) == pytest.approx(timing.seconds, abs=0.1)
    join_frame = round(timing.clips[0].seconds * 24)
    hashes = decoded_hashes(render)
    for window in (hashes[join_frame - 8 : join_frame], hashes[join_frame : join_frame + 8]):
        assert len(set(window)) > 4
    records = ledger(root)
    assert main(["run", *args]) == 0
    assert ledger(root) == records
