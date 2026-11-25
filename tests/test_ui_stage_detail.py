"""``vidpipe ui``: each stage's detail (outputs, timing, media, diagnostics) over the HTTP API.

A project is run once on fake providers through the CLI; the UI then serves what that run left in
``build/`` and ``out/``, over a real socket as a browser would fetch it.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("starlette", reason="needs the optional ui extra")
pytest.importorskip("uvicorn", reason="needs the optional ui extra")

from tests.cli_text_fixtures import FakeClis  # noqa: E402
from tests.conftest import HAVE_FFMPEG, SAMPLE, MakeProject  # noqa: E402
from tests.fake_comfyui import FakeComfyUI, Job  # noqa: E402
from tests.test_translation import AMHARIC, BACK, queue_happy_path, verdicts  # noqa: E402
from tests.ui_server import UiProcess, UiServer, free_port  # noqa: E402
from vidpipe.cli import main  # noqa: E402
from vidpipe.providers.fakes import CANNED_SCRIPT, CANNED_SHOTS  # noqa: E402

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def run_project(project: Path, *args: str) -> None:
    assert main(["run", str(project), *args]) == 0


@pytest.fixture(scope="module")
def ran(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The sample project after a full fake run (up to music without ffmpeg)."""
    root = tmp_path_factory.mktemp("ran") / "project"
    shutil.copytree(SAMPLE, root)
    config = root / "vidpipe.yaml"  # no gates: the run goes through without pausing
    config.write_text(config.read_text(encoding="utf-8") + "gates: []\n", encoding="utf-8")
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


# ---------------------------------------------------------------- every stage's outputs


def test_the_text_stages_serve_the_brief_script_storyboard_and_translation(ui: UiServer) -> None:
    assert outputs(ui, "brief")["brief"]["title"] == "The Coffee Highlands"

    script = outputs(ui, "script")["script"]
    assert script["language"] == "en"
    assert [line["text"] for line in script["lines"]] == CANNED_SCRIPT

    shots = outputs(ui, "storyboard")["storyboard"]["shots"]
    assert [s["visual"] for s in shots] == [visual for visual, _ in CANNED_SHOTS]
    assert shots[1]["line"] == CANNED_SCRIPT[1]  # the line each shot illustrates

    (am,) = outputs(ui, "translation")["translations"]
    assert am["language"] == "am"
    assert am["reviewed"] is False  # the fake translator has no back-translation check
    assert [(line["source"], line["translation"]) for line in am["lines"]] == [
        (text, f"[am] {text}") for text in CANNED_SCRIPT
    ]


def test_narration_is_one_playable_clip_per_shot_and_language_with_its_line(
    ui: UiServer,
) -> None:
    clips = outputs(ui, "narration")["media"]

    assert sorted((c["language"], c["shot_id"]) for c in clips) == [
        (lang, shot) for lang in ("am", "en") for shot in (1, 2, 3)
    ]
    assert {c["content_type"] for c in clips} == {"audio/wav"}
    am_2 = next(c for c in clips if (c["language"], c["shot_id"]) == ("am", 2))
    assert am_2["text"] == f"[am] {CANNED_SCRIPT[1]}"
    assert am_2["duration_s"] > 0
    assert ui.get(am_2["url"]).body[:4] == b"RIFF"


def test_fit_planning_summarises_the_plan(ui: UiServer) -> None:
    plan = outputs(ui, "fit-planning")["fit_plan"]

    assert plan["shots"] == 3
    assert plan["clip_count"] == 3  # shared visuals: one clip per shot for both languages
    assert set(plan["render_seconds"]) == {"en", "am"}
    assert plan["music_seconds"] >= max(plan["render_seconds"].values())
    assert plan["problems"] == []


def test_video_clips_and_music_are_served_as_media(ui: UiServer) -> None:
    clips = outputs(ui, "video")["media"]
    assert [(c["shot_id"], c["clip"], c["kind"]) for c in clips] == [
        (1, 0, "video"),
        (2, 0, "video"),
        (3, 0, "video"),
    ]
    assert all(ui.get(c["url"]).status == 200 for c in clips)

    (music,) = outputs(ui, "music")["media"]
    reply = ui.get(music["url"])
    assert (reply.status, reply.headers["content-type"]) == (200, "audio/wav")


@pytest.mark.needs_ffmpeg
def test_assembly_serves_each_languages_render_and_subtitles(ui: UiServer) -> None:
    media = outputs(ui, "assembly")["media"]

    assert [(m["language"], m["kind"]) for m in media] == [
        ("en", "video"),
        ("en", "subtitles"),
        ("am", "video"),
        ("am", "subtitles"),
    ]
    render = ui.get(media[0]["url"])
    assert render.headers["content-type"] == "video/mp4"
    assert render.body[4:8] == b"ftyp"
    seek = ui.get(media[2]["url"], {"Range": "bytes=0-1023"})
    assert (seek.status, len(seek.body)) == (206, 1024)


def test_timing_and_gpu_time_come_from_the_ledger(ui: UiServer) -> None:
    keyframes = outputs(ui, "keyframes")["timing"]
    assert keyframes["artifacts"] == 3
    assert keyframes["gpu_seconds"] > 0  # the fake keyframer stands in for a GPU provider
    assert keyframes["wall_seconds"] >= keyframes["gpu_seconds"] * 0.99

    script = outputs(ui, "script")["timing"]
    assert (script["artifacts"], script["gpu_seconds"]) == (1, 0)


def test_an_unknown_stage_is_not_found(ui: UiServer) -> None:
    assert ui.get("/api/stages/editing/outputs").status == 404


def test_before_any_run_a_stage_has_nothing_to_show(make_project: MakeProject) -> None:
    server = UiServer(make_project())
    try:
        for stage in ("brief", "translation", "keyframes", "assembly"):
            detail = outputs(server, stage)
            assert detail["timing"] is None
            assert detail["media"] == []
        assert outputs(server, "script")["script"] is None
    finally:
        server.stop()


def test_the_translation_review_flags_drift_beside_the_affected_line(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    reason = "the source says evening; the translation says noon"
    queue_happy_path(fake_clis, verdicts((2, reason)))
    project = make_project(providers={"translation": ["gemini-cli", "claude-cli"]})
    run_project(project, "--until", "translation")
    server = UiServer(project)
    try:
        (am,) = outputs(server, "translation")["translations"]
    finally:
        server.stop()

    assert (am["reviewed"], am["translator"], am["checker"]) == (True, "gemini-cli", "claude-cli")
    assert am["drifted"] == 1
    assert [
        (line["id"], line["source"], line["translation"], line["back_translation"], line["status"])
        for line in am["lines"]
    ] == [
        (i, CANNED_SCRIPT[i - 1], AMHARIC[i - 1], BACK[i - 1], "drift" if i == 2 else "ok")
        for i in (1, 2, 3)
    ]
    assert am["lines"][1]["reason"] == reason


# ---------------------------------------------------------- diagnostics, behind the disclosure


def test_a_stages_ledger_records_are_served_on_request(ui: UiServer) -> None:
    reply = ui.get("/api/stages/keyframes/ledger")

    assert reply.status == 200
    records = reply.json()["records"]
    assert [r["key"] for r in records] == [
        "keyframes/shot_01",
        "keyframes/shot_02",
        "keyframes/shot_03",
    ]
    first = records[0]
    assert (first["provider"], first["seed"]) == ("fake-keyframer", 1)
    assert first["outputs"] == ["build/keyframes/shot_01.png"]
    assert first["gpu_seconds"] > 0
    assert ui.get("/api/stages/editing/ledger").status == 404


def test_the_run_log_is_served_from_its_end(ran: Path, ui: UiServer) -> None:
    log = ran / "build" / "run.log"
    assert ui.get("/api/logs").json() == {"path": "build/run.log", "lines": [], "truncated": False}

    log.write_text("".join(f"line {i}\n" for i in range(1, 1001)), encoding="utf-8")
    try:
        reply = ui.get("/api/logs").json()
    finally:
        log.unlink()

    assert reply["truncated"] is True
    assert reply["lines"][-1] == "line 1000"
    assert len(reply["lines"]) == 200


def test_comfyui_queue_and_gpu_stats_come_from_the_projects_comfyui(
    make_project: MakeProject, comfy: FakeComfyUI
) -> None:
    comfy.devices = [
        {
            "name": "cuda:0 NVIDIA GeForce RTX 4060 Laptop GPU",
            "type": "cuda",
            "vram_total": 8_585_216_000,
            "vram_free": 1_500_000_000,
            "torch_vram_total": 7_000_000_000,
            "torch_vram_free": 200_000_000,
        }
    ]
    comfy.jobs += [
        Job("running-1", {}, None, "success", state="running"),
        Job("queued-1", {}, None, "success"),
        Job("queued-2", {}, None, "success"),
    ]
    server = UiServer(make_project(comfyui={"url": comfy.url}))
    try:
        stats = server.get("/api/comfyui").json()
    finally:
        server.stop()

    assert stats["url"] == comfy.url
    assert (stats["reachable"], stats["version"]) == (True, "0.46.3")
    assert stats["queue"] == {"running": 1, "pending": 2}
    (gpu,) = stats["devices"]
    assert gpu["name"] == "cuda:0 NVIDIA GeForce RTX 4060 Laptop GPU"
    assert (gpu["vram_total"], gpu["vram_free"]) == (8_585_216_000, 1_500_000_000)


def test_an_unreachable_comfyui_is_reported_not_an_error(make_project: MakeProject) -> None:
    url = f"http://127.0.0.1:{free_port()}"
    server = UiServer(make_project(comfyui={"url": url}))
    try:
        reply = server.get("/api/comfyui")
    finally:
        server.stop()

    assert reply.status == 200
    stats = reply.json()
    assert (stats["url"], stats["reachable"]) == (url, False)
    assert "cannot reach ComfyUI" in stats["error"]
    assert stats["queue"] is None
    assert stats["devices"] == []


def test_opened_to_the_network_media_and_detail_need_the_token(ran: Path) -> None:
    server = UiProcess(ran, "--host", "0.0.0.0")
    try:
        link = next(m for line in server.output for m in re.findall(r"\?token=(\S+)", line))
        with_cookie = {"Cookie": f"vidpipe_token={link}"}
        keyframe = "/media/build/keyframes/shot_01.png"
        for path in (keyframe, "/api/stages/keyframes/outputs", "/api/logs", "/api/comfyui"):
            assert server.get(path).status == 401, path
        assert server.get("/api/stages/keyframes/outputs", with_cookie).status == 200
        reply = server.get(keyframe, {**with_cookie, "Range": "bytes=0-7"})
        assert (reply.status, reply.body) == (206, PNG_SIGNATURE)
    finally:
        server.stop()
