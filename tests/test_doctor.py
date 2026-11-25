"""Exercise the dependency report through the CLI without provider calls or a GPU."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from tests.conftest import MakeProject
from tests.fake_comfyui import FakeComfyUI
from vidpipe.assembly import FFMPEG_DIR_ENV
from vidpipe.cli import main

WORKFLOWS = Path(__file__).resolve().parents[1] / "workflows"
MODELS = {
    "diffusion_models": ["flux-2-klein-4b-fp8.safetensors"],
    "text_encoders": ["qwen_3_4b.safetensors"],
    "vae": ["flux2-vae.safetensors"],
}


def _portable_ffmpeg(directory: Path, *, libass: bool) -> None:
    filters = [" ... sidechaincompress AA->A Compress audio"]
    if libass:
        filters.append(" ... subtitles V->V Render subtitles")
    directory.mkdir()
    for name in ("ffmpeg", "ffprobe"):
        if os.name == "nt":
            (directory / f"{name}.cmd").write_text(
                "@echo off\n" + "\n".join(f"echo {line}" for line in filters).replace(">", "^>"),
                encoding="utf-8",
            )
        else:
            path = directory / name
            path.write_text(
                "#!/bin/sh\n" + "\n".join(f"echo '{line}'" for line in filters), encoding="utf-8"
            )
            path.chmod(0o755)


def _keyframe_nodes(root: Path) -> set[str]:
    return {
        node["class_type"]
        for path in root.glob("keyframe_*.json")
        for node in json.loads(path.read_text(encoding="utf-8")).values()
    }


def test_doctor_passes_with_portable_tools_and_selected_workflow(
    make_project: MakeProject,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    comfy: FakeComfyUI,
) -> None:
    portable = tmp_path / "portable bin"
    _portable_ffmpeg(portable, libass=True)
    monkeypatch.setenv(FFMPEG_DIR_ENV, str(portable))
    project = make_project(
        comfyui={"url": f"{comfy.url}/wrong"},
        providers={
            "translation": [
                {"name": "gemini-cli", "options": {"command": sys.executable}},
                {"name": "codex-cli", "options": {"command": sys.executable}},
            ],
            "narration": "edge-tts",
            "keyframes": {
                "name": "comfyui-keyframer",
                "options": {"workflow": "custom/keyframes.yaml", "url": comfy.url},
            },
        },
    )
    custom = project / "custom"
    shutil.copytree(WORKFLOWS, custom)
    mapping = custom / "keyframe_flux2_klein_4b.mapping.yaml"
    mapping.rename(custom / "keyframes.yaml")
    with (custom / "keyframes.yaml").open("a", encoding="utf-8") as file:
        file.write("    - unet/Wan2.2-TI2V-5B-Q5_K_M.gguf\n")
    comfy.node_types = _keyframe_nodes(custom)
    comfy.models = {**MODELS, "unet_gguf": ["Wan2.2-TI2V-5B-Q5_K_M.gguf"]}

    monkeypatch.chdir(project)
    assert main(["doctor"]) == 0

    report = capsys.readouterr().out
    for dependency in (
        "portable bin",
        "libass",
        "ffprobe",
        "fonts",
        "gemini-cli",
        "codex-cli",
        "edge-tts",
        "0.46.3",
        "Wan2.2-TI2V-5B-Q5_K_M.gguf",
        "Doctor passed",
    ):
        assert dependency in report
    assert "FAIL" not in report
    assert all(request.startswith("GET ") for request in comfy.requests)
    assert not (project / "build").exists()


def test_doctor_collects_independent_failures_and_fixes(
    make_project: MakeProject,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    comfy: FakeComfyUI,
) -> None:
    portable = tmp_path / "no-libass"
    _portable_ffmpeg(portable, libass=False)
    (portable / ("ffprobe.cmd" if os.name == "nt" else "ffprobe")).unlink()
    monkeypatch.setenv(FFMPEG_DIR_ENV, str(portable))
    project = make_project(
        comfyui={"url": comfy.url},
        subtitles={"fonts_dir": "missing-fonts"},
        providers={
            "script": {"name": "claude-cli", "options": {"command": str(tmp_path / "no-claude")}},
            "keyframes": "comfyui-keyframer",
        },
    )
    comfy.version = "0.46.2"
    comfy.node_types = _keyframe_nodes(WORKFLOWS) - {"ReferenceLatent"}
    comfy.models = {**MODELS, "vae": []}

    assert main(["doctor", str(project)]) == 1
    lines = capsys.readouterr().out.splitlines()
    for dependency, fix in [
        ("ffprobe not found", FFMPEG_DIR_ENV),
        ("'subtitles' filter", "libass"),
        ("missing-fonts", "subtitles.fonts_dir"),
        ("no-claude", "options.command"),
        ("0.46.2", "Use ComfyUI 0.46.3"),
        ("ReferenceLatent", "node packages"),
        ("flux2-vae.safetensors missing", "models/vae/flux2-vae.safetensors"),
    ]:
        assert any(line.startswith("FAIL") and dependency in line and fix in line for line in lines)
    assert "Doctor found 7 problem(s)." in lines


def test_doctor_reports_comfyui_url_and_missing_ffmpeg(
    make_project: MakeProject,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    comfy: FakeComfyUI,
) -> None:
    monkeypatch.setenv(FFMPEG_DIR_ENV, str(tmp_path / "missing"))
    url = f"{comfy.url}/wrong"
    project = make_project(comfyui={"url": url}, providers={"keyframes": "comfyui-keyframer"})

    assert main(["doctor", str(project)]) == 1
    report = capsys.readouterr().out
    assert f"ffmpeg not found in {tmp_path / 'missing'}" in report
    assert url in report and "Start ComfyUI or correct `comfyui.url`" in report
    assert "/models/" not in report
