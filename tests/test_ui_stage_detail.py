"""``vidpipe ui``: each stage's detail (outputs, timing, media, diagnostics) over the HTTP API.

A project is run once on fake providers through the CLI; the UI then serves what that run left in
``build/`` and ``out/``, over a real socket as a browser would fetch it.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

pytest.importorskip("starlette", reason="needs the optional ui extra")
pytest.importorskip("uvicorn", reason="needs the optional ui extra")

from tests.conftest import HAVE_FFMPEG, SAMPLE, MakeProject  # noqa: E402
from tests.ui_server import UiServer  # noqa: E402
from vidpipe.cli import main  # noqa: E402

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def run_project(project: Path, *args: str) -> None:
    assert main(["run", str(project), *args]) == 0


@pytest.fixture(scope="module")
def ran(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The sample project after a full fake run (up to music without ffmpeg)."""
    root = tmp_path_factory.mktemp("ran") / "project"
    shutil.copytree(SAMPLE, root)
    config = yaml.safe_load((root / "vidpipe.yaml").read_text(encoding="utf-8"))
    config["gates"] = []
    (root / "vidpipe.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    run_project(root, *([] if HAVE_FFMPEG else ["--until", "music"]))
    return root


@pytest.fixture(scope="module")
def ui(ran: Path) -> Iterator[UiServer]:
    server = UiServer(ran)
    yield server
    server.stop()


def outputs(ui: UiServer, stage: str) -> dict[str, Any]:
    reply = ui.get(f"/api/stages/{stage}/outputs")
    assert reply.status == 200, reply.body
    return reply.json()


def test_keyframes_are_listed_per_shot_and_served_as_png(ui: UiServer) -> None:
    detail = outputs(ui, "keyframes")

    images = detail["media"]
    assert [m["shot_id"] for m in images] == [1, 2, 3]
    assert {m["kind"] for m in images} == {"image"}
    for item in images:
        reply = ui.get(item["url"])
        assert reply.status == 200
        assert reply.headers["content-type"] == "image/png"
        assert reply.body.startswith(PNG_SIGNATURE)


def test_narration_audio_supports_byte_ranges_for_seeking(ui: UiServer) -> None:
    clip = next(m for m in outputs(ui, "narration")["media"] if m["kind"] == "audio")
    whole = ui.get(clip["url"])
    assert whole.status == 200
    assert whole.headers["content-type"] == "audio/wav"
    assert whole.headers["accept-ranges"] == "bytes"

    part = ui.get(clip["url"], {"Range": "bytes=100-199"})

    assert part.status == 206
    assert part.headers["content-range"] == f"bytes 100-199/{len(whole.body)}"
    assert part.body == whole.body[100:200]


@pytest.mark.parametrize(
    "path",
    [
        "/media/brief.md",  # the project's own files are not media
        "/media/vidpipe.yaml",
        "/media/build/ledger.json",  # only media types, even inside build/
        "/media/build/run_state.json",
        "/media/build/../brief.md",
        "/media/build/%2e%2e/vidpipe.yaml",
        "/media/build/..%2fvidpipe.yaml",
        "/media/build/..%5cvidpipe.yaml",
        "/media/build%5c..%5cvidpipe.yaml",
        "/media/out/../../outside.png",
        "/media/C:/Windows/win.ini",
        "/media//etc/passwd",
        "/media/build/keyframes/shot_01.png::$DATA",
        "/media/build/keyframes/missing.png",
        "/media/bible/protagonist.jpg",  # media type, but outside build/ and out/
    ],
)
def test_only_media_inside_build_and_out_are_served(ui: UiServer, ran: Path, path: str) -> None:
    (ran.parent / "outside.png").write_bytes(PNG_SIGNATURE)

    reply = ui.get(path)

    assert reply.status == 404, path
    assert not reply.body.startswith(PNG_SIGNATURE)
