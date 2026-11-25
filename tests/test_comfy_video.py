"""Exercise the video stage's artifact and failure handling with a fake ComfyUI."""

from __future__ import annotations

import subprocess

import pytest

from tests.conftest import MakeProject, ffprobe
from tests.fake_comfyui import WRITERS, FakeComfyUI, Job
from tests.test_keyframes_bible import ledger
from vidpipe.cli import main


def _save_video(job: Job, uploads: dict[str, bytes]) -> tuple[str, str, bytes]:
    width, height = job.size()
    fps = job.input("video", "fps")
    frames = job.input("trim", "length")
    colour = job.identity(uploads)[:3].hex()
    mp4 = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x{colour}:s={width}x{height}:r={fps}",
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
