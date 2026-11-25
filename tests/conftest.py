from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.cli_text_fixtures import fake_clis as fake_clis
from tests.fake_comfyui import FakeComfyUI
from vidpipe.assembly import FFMPEG_DIR_ENV, find_tool

SAMPLE = Path(__file__).resolve().parent.parent / "examples" / "sample"

HAVE_FFMPEG = find_tool("ffmpeg") is not None and find_tool("ffprobe") is not None


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip `needs_ffmpeg` tests cleanly when ffmpeg/ffprobe are absent."""
    if HAVE_FFMPEG:
        return
    skip = pytest.mark.skip(reason=f"ffmpeg/ffprobe not found via {FFMPEG_DIR_ENV} or PATH")
    for item in items:
        if "needs_ffmpeg" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def comfy() -> Iterator[FakeComfyUI]:
    """A fake ComfyUI server (``comfy.url``) for the length of a test."""
    server = FakeComfyUI().start()
    yield server
    server.stop()


MakeProject = Callable[..., Path]


@pytest.fixture
def make_project(tmp_path: Path) -> MakeProject:
    """Create a project directory from the sample project, with config overrides."""

    def make(**config_overrides: Any) -> Path:
        root = tmp_path / "project"
        shutil.copytree(SAMPLE, root)
        config = yaml.safe_load((root / "vidpipe.yaml").read_text(encoding="utf-8"))
        providers = config_overrides.pop("providers", {})
        config["providers"].update(providers)
        # Gates would pause most tests mid-run: they are off unless a test asks (`gates=None` keeps
        # the default gate set).
        gates = config_overrides.pop("gates", [])
        if gates is not None:
            config["gates"] = gates
        config.update(config_overrides)
        text: str = yaml.safe_dump(config)  # pyright: ignore[reportUnknownMemberType]
        (root / "vidpipe.yaml").write_text(text, encoding="utf-8")
        return root

    return make


def ffprobe(path: Path) -> dict[str, Any]:
    import json

    tool = find_tool("ffprobe")
    assert tool is not None
    out = subprocess.run(
        [
            tool,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(out)
