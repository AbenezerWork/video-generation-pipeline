"""The instrumental soundtrack through the provider contract and the project CLI."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.conformance import suites
from tests.conftest import MakeProject, ffprobe
from tests.fake_comfyui import WRITERS, FakeComfyUI
from tests.test_keyframes_bible import ledger
from vidpipe.cli import main
from vidpipe.comfy.workflow import bundled_workflows_dir
from vidpipe.contracts import GenerationError, MusicRequest
from vidpipe.models import FitPlan, MediaIndex
from vidpipe.project import Project
from vidpipe.providers.comfy_music import ComfyMusic


@pytest.mark.needs_ffmpeg
def test_comfyui_music_passes_conformance_with_a_fake_server(
    comfy: FakeComfyUI, tmp_path: Path
) -> None:
    provider = ComfyMusic(url=comfy.url, poll_s=0.01)
    try:
        suites.declares_identity_and_capabilities(provider)
        suites.has_a_stable_fingerprint(provider)
        suites.check_music(provider, tmp_path)
        result = provider.compose(
            MusicRequest(prompt="warm acoustic", duration_s=2.01, output_path=tmp_path / "fraction")
        )
        assert 2.01 <= result.duration_s <= 2.05
    finally:
        provider.release()


@pytest.mark.needs_ffmpeg
def test_short_audio_cannot_replace_a_valid_score(
    comfy: FakeComfyUI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ComfyMusic(url=comfy.url, poll_s=0.01)
    request = MusicRequest(prompt="warm acoustic", duration_s=2, output_path=tmp_path / "score")
    try:
        score = provider.compose(request)
        original = score.path.read_bytes()
        monkeypatch.setitem(
            WRITERS, "SaveAudioAdvanced", lambda _job, _uploads: ("audio", ".flac", original)
        )
        with pytest.raises(GenerationError, match="shorter than the requested 3 s"):
            provider.compose(request.model_copy(update={"duration_s": 3}))
        assert score.path.read_bytes() == original
    finally:
        provider.release()


def assert_soundtrack_covers_project(path: Path) -> None:
    project = Project(path)
    fit = project.read_model("fit_plan.json", FitPlan)
    index = project.read_model("music.json", MediaIndex)
    (item,) = index.items
    music = ffprobe(project.build / item.path)
    assert music["streams"][0]["codec_name"] == "flac"
    assert float(music["format"]["duration"]) >= fit.total_seconds


@pytest.mark.needs_ffmpeg
def test_switching_music_in_yaml_reuses_other_stages_and_renders_the_score(
    make_project: MakeProject, comfy: FakeComfyUI
) -> None:
    project = make_project(comfyui={"url": comfy.url}, subtitles={"burn_in": False})
    args = [str(project), "--until", "music"]
    assert main(["run", *args]) == 0
    original = ledger(project)
    config = project / "vidpipe.yaml"
    text = config.read_text(encoding="utf-8").replace(
        "music: fake-music", "music: {name: comfyui-music, options: {poll_s: 0.01}}"
    )
    config.write_text(text, encoding="utf-8")
    assert main(["plan", *args]) == 0
    assert comfy.jobs == []

    # The retry reduces decode tile size while keeping the length of the score.
    comfy.script("oom", "success")
    assert main(["run", str(project)]) == 0
    assert_soundtrack_covers_project(project)
    records = ledger(project)
    assert all(records[key] == value for key, value in original.items() if key != "music")
    soundtrack = records["music"]
    assert soundtrack["provider"] == "comfyui-music"
    assert soundtrack["gpu_seconds"] == 2 * comfy.job_seconds
    assert soundtrack["data"]["duration_s"] == soundtrack["parameters"]["duration_s"]
    assert "decode_tile_size 512 -> 256" in soundtrack["fallback"]
    assert soundtrack["data"]["seed"] != soundtrack["seed"]
    assert len(comfy.freed) == 2
    assert comfy.running == []
    assert (project / "out" / "demo_en.mp4").is_file()
    assert (project / "out" / "demo_am.mp4").is_file()

    comfy.requests.clear()
    assert main(["run", *args]) == 0
    assert comfy.requests == []


def test_plan_rejects_a_score_beyond_the_configured_workflows_limit(
    make_project: MakeProject, comfy: FakeComfyUI, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(
        comfyui={"url": comfy.url},
        providers={"music": {"name": "comfyui-music", "options": {"workflow": "music.yaml"}}},
    )
    package = bundled_workflows_dir()
    shutil.copyfile(package / "music_ace_step.json", project / "music_ace_step.json")
    mapping = (package / "music_ace_step.mapping.yaml").read_text(encoding="utf-8")
    (project / "music.yaml").write_text(
        mapping.replace("max_seconds: 120", "max_seconds: 2"), encoding="utf-8"
    )
    assert main(["run", str(project), "--until", "storyboard"]) == 0
    capsys.readouterr()
    assert main(["plan", str(project), "--until", "music"]) == 1
    assert "at most 2 s" in capsys.readouterr().err
    assert comfy.requests == []


@pytest.mark.integration
@pytest.mark.needs_ffmpeg
def test_comfyui_music_covers_a_project_on_a_real_server(make_project: MakeProject) -> None:
    project = make_project(providers={"music": "comfyui-music"})
    assert main(["run", str(project), "--until", "music"]) == 0
    assert_soundtrack_covers_project(project)
    assert ledger(project)["music"]["gpu_seconds"] > 0


@pytest.mark.integration
@pytest.mark.needs_ffmpeg
def test_comfyui_music_covers_the_full_demo_limit_on_a_real_server(tmp_path: Path) -> None:
    provider = ComfyMusic()
    request = MusicRequest(
        prompt="warm acoustic, plucked strings, light percussion",
        duration_s=90,
        output_path=tmp_path / "score.flac",
    )
    try:
        score = provider.compose(request)
        assert float(ffprobe(score.path)["format"]["duration"]) >= 90
    finally:
        provider.release()
