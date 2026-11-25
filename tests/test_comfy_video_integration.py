"""Run the real Wan 2.2 video stage on ComfyUI using the bundled FLUX keyframes."""

from __future__ import annotations

import subprocess

import pytest

from tests.conftest import MakeProject, ffprobe
from tests.test_fit_plan import project_with_script
from tests.test_keyframes_bible import ledger
from vidpipe.cli import main
from vidpipe.comfy import ComfyClient
from vidpipe.models import FitPlan, MediaIndex, Storyboard
from vidpipe.project import Project

pytestmark = [pytest.mark.integration, pytest.mark.needs_ffmpeg]


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

        hashes = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-f", "framemd5", "-"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout.splitlines()
        assert len({line.rsplit(",", 1)[-1] for line in hashes if not line.startswith("#")}) > 1

    assert main(["run", *args]) == 0
    assert ledger(root) == records
    assert ComfyClient().queued_ids() == []
