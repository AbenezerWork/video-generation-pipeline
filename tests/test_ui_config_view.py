"""``vidpipe ui``: the Config view's HTTP API on a temporary project.

The project config is read and validated as the CLI reads it, each stage's provider choices come
with their doctor readiness and their options, and the YAML view shows what saving would write.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

pytest.importorskip("starlette", reason="needs the optional ui extra")
pytest.importorskip("uvicorn", reason="needs the optional ui extra")

from tests.background_run import Writer  # noqa: E402
from tests.cli_text_fixtures import FakeClis  # noqa: E402
from tests.conftest import MakeProject  # noqa: E402
from tests.fake_comfyui import FakeComfyUI  # noqa: E402
from tests.ui_server import Response, UiServer  # noqa: E402
from vidpipe.cli import main  # noqa: E402

WORKFLOWS = Path(__file__).resolve().parents[1] / "workflows"
TEXT = {"claude-cli", "codex-cli", "fake-text", "gemini-cli"}
KEYFRAMER_MODELS = {
    "diffusion_models": ["flux-2-klein-4b-fp8.safetensors"],
    "text_encoders": ["qwen_3_4b.safetensors"],
    "vae": ["flux2-vae.safetensors"],
}

COMMENTED = """\
# My video. Hand-written; keep these comments.
languages: [en, am]
visuals: shared   # one set of pictures
output_name: demo
providers:
  script: fake-text
  translation: fake-translation
  storyboard: fake-text
  narration: fake-tts   # swap for edge-tts later
  keyframes: fake-keyframer
  video: fake-i2v
  music: fake-music
gates: []
# mix:
#   music_level: 0.4
"""


def post(ui: UiServer, path: str, body: Any, headers: dict[str, str] | None = None) -> Response:
    conn = http.client.HTTPConnection("127.0.0.1", ui.port, timeout=30)
    try:
        conn.request(
            "POST",
            path,
            body=json.dumps(body),
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        reply = conn.getresponse()
        return Response(reply.status, {k.lower(): v for k, v in reply.getheaders()}, reply.read())
    finally:
        conn.close()


@pytest.fixture
def project(make_project: MakeProject) -> Path:
    return make_project()


@pytest.fixture
def ui(project: Path) -> Iterator[UiServer]:
    server = UiServer(project)
    yield server
    server.stop()


def stages_of(reply: Response) -> dict[str, dict[str, Any]]:
    assert reply.status == 200, reply.body
    return {s["stage"]: s for s in reply.json()["stages"]}


def choices_of(stage: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["name"]: c for c in stage["choices"]}


def document(project: Path) -> dict[str, Any]:
    return yaml.safe_load((project / "vidpipe.yaml").read_text(encoding="utf-8"))


def test_save_writes_the_preview_and_preserves_comments_and_order(
    project: Path, ui: UiServer
) -> None:
    path = project / "vidpipe.yaml"
    path.write_text(COMMENTED, encoding="utf-8")
    draft = document(project)
    draft["output_name"] = "updated"
    preview = post(ui, "/api/config/validate", {"document": draft}).json()["yaml"]

    reply = post(ui, "/api/config/save", {"document": draft})

    assert reply.status == 200, reply.body
    assert not reply.json()["pending_change"]
    actual = path.read_text(encoding="utf-8")
    assert actual == preview
    assert actual == COMMENTED.replace("output_name: demo", "output_name: updated")
    assert document(project) == draft


def test_reordering_a_yaml_list_keeps_comments_with_its_entries(
    project: Path, ui: UiServer
) -> None:
    path = project / "vidpipe.yaml"
    path.write_text(
        COMMENTED.replace(
            "languages: [en, am]",
            "languages:\n  - en  # English voice\n  - am  # Amharic voice",
        ),
        encoding="utf-8",
    )
    draft = document(project)
    draft["languages"] = ["am", "en"]
    saved = ui.post("/api/config/save", {"document": draft})
    assert saved.status == 200, saved.body
    text = path.read_text(encoding="utf-8")
    assert re.search(r"- am +# Amharic voice\n\s*- en +# English voice", text)


def test_save_refuses_invalid_and_stale_documents(project: Path, ui: UiServer) -> None:
    path = project / "vidpipe.yaml"
    original = path.read_bytes()
    config = ui.get("/api/config").json()
    draft = config["document"]
    draft["mix"] = {"music_level": 0}
    reply = ui.post("/api/config/save", {"document": draft, "revision": config["revision"]})
    assert reply.status == 422
    assert reply.json()["errors"][0]["path"] == "mix.music_level"
    assert path.read_bytes() == original

    external = original + b"\n# changed on disk\n"
    path.write_bytes(external)
    del draft["mix"]
    reply = ui.post("/api/config/save", {"document": draft, "revision": config["revision"]})
    assert reply.status == 409
    assert path.read_bytes() == external


@pytest.mark.needs_ffmpeg
def test_proposed_regeneration_matches_the_cli_plan(
    project: Path, ui: UiServer, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["run", str(project)]) == 0
    capsys.readouterr()
    path = project / "vidpipe.yaml"
    original = path.read_bytes()
    ledger = project / "build" / "ledger.json"
    original_ledger = ledger.read_bytes()
    draft = document(project)
    assert ui.post("/api/config/plan", {"document": draft}).json()["regeneration"]["stages"] == []

    draft["width"] = 192
    preview = ui.post("/api/config/plan", {"document": draft})
    assert preview.status == 200, preview.body
    assert path.read_bytes() == original
    assert ledger.read_bytes() == original_ledger
    impact = preview.json()["regeneration"]
    assert [s["stage"] for s in impact["stages"]] == ["keyframes", "video", "assembly"]
    assert impact["stages"][0]["artifacts"] == 3
    assert impact["gpu_minutes"] > 0

    original_size = document(project)
    original_size["output_name"] = "renamed"
    rename = ui.post("/api/config/plan", {"document": original_size}).json()["regeneration"]
    assert rename == {
        "stages": [{"stage": "assembly", "artifacts": 2, "gpu_minutes": 0.0, "possible": False}],
        "gpu_minutes": 0.0,
        "complete": True,
    }

    assert ui.post("/api/config/save", {"document": draft}).status == 200
    assert main(["plan", str(project), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["regeneration"] == impact
    assert ui.post("/api/config/save", {"document": original_size}).status == 200
    assert main(["run", str(project)]) == 0
    assert (project / "out" / "renamed_en.mp4").is_file()


def test_save_during_a_run_is_pending_and_restart_reuses_finished_work(
    make_project: MakeProject, fake_clis: FakeClis
) -> None:
    project = make_project(providers={"script": "gemini-cli"})
    ui = UiServer(project)
    writer = Writer(project, fake_clis, then=json.dumps({"lines": ["The original script."]}))
    try:
        with contextlib.closing(ui.events()) as stream:
            before = stream.next().data
            assert before["status"] == "running"
            draft = document(project)
            draft["providers"]["script"] = "fake-text"
            saved = ui.post("/api/config/save", {"document": draft}).json()
            assert saved["pending_change"]
            assert saved["config_hash"] != before["config_hash"]
            assert ui.get("/api/project").json()["pending_change"]
            assert ui.get("/api/run").json()["config_hash"] == before["config_hash"]

            assert stream.conn.sock is not None
            stream.conn.sock.settimeout(10)
            config_event = stream.next()
            assert config_event.event == "config"
            assert config_event.data == {
                "revision": saved["revision"],
                "config_hash": saved["config_hash"],
            }

            stopped = ui.post("/api/run/stop", {"run_id": before["run_id"]})
            assert stopped.status == 202, stopped.body
            writer.finish()
            original = ui.get("/api/run").json()
            assert original["status"] == "stopped"
            assert original["config_hash"] == before["config_hash"]
            assert document(project)["providers"]["script"] == "fake-text"
            assert "The original script." in (project / "build" / "script.json").read_text(
                encoding="utf-8"
            )

            started = ui.post("/api/run/start", {"until": before["until"]})
            assert started.status == 202, started.body
            run_id = started.json()["run_id"]
            end = list(
                stream.until(
                    lambda event: (
                        event.event == "run"
                        and event.data["run_id"] == run_id
                        and event.data["status"] == "finished"
                    )
                )
            )[-1].data
            assert end["config_hash"] == saved["config_hash"]
            assert {s["stage"]: (s["status"], s["provider"]) for s in end["stages"]} == {
                "brief": ("reused", None),
                "script": ("done", "fake-text"),
            }
            assert len(fake_clis.calls("gemini")) == 1
            assert not ui.get("/api/project").json()["pending_change"]
    finally:
        writer.finish()
        ui.stop()


# ------------------------------------------------------------------------------ providers


def test_each_stage_offers_only_the_providers_implementing_its_contract(ui: UiServer) -> None:
    stages = stages_of(ui.get("/api/providers"))

    assert {name: set(choices_of(s)) for name, s in stages.items()} == {
        "script": TEXT,
        "storyboard": TEXT,
        # Text providers translate too (vidpipe wraps them), besides translation providers.
        "translation": TEXT | {"fake-translation", "fake-translation-upper"},
        "narration": {"addis-ai", "edge-tts", "fake-tts", "fake-tts-en-only"},
        "keyframes": {"comfyui-keyframer", "fake-keyframer", "fake-keyframer-text-only"},
        "video": {"comfyui-i2v", "fake-i2v", "fake-i2v-hosted"},
        "music": {"comfyui-music", "fake-music"},
        "song": {"fake-song"},
    }
    assert {name: s["selected"] for name, s in stages.items()} == {
        "script": "fake-text",
        "storyboard": "fake-text",
        "translation": "fake-translation",
        "narration": "fake-tts",
        "keyframes": "fake-keyframer",
        "video": "fake-i2v",
        "music": "fake-music",
        "song": None,
    }
    # Fallback chains are acted on for the text stages only.
    assert {name for name, s in stages.items() if s["fallback"]} == {
        "script",
        "storyboard",
        "translation",
    }


def test_each_provider_declares_its_own_options(ui: UiServer) -> None:
    stages = stages_of(ui.get("/api/providers"))

    def options(stage: str, name: str) -> dict[str, Any]:
        return choices_of(stages[stage])[name]["options"]["properties"]

    assert set(options("script", "gemini-cli")) == {"model", "timeout_s", "command"}
    assert set(options("narration", "edge-tts")) == {"voices", "rate"}
    assert set(options("narration", "fake-tts")) == {
        "seconds_per_char",
        "max_seconds",
        "tail_silence_s",
    }
    keyframer = options("keyframes", "comfyui-keyframer")
    assert set(keyframer) == {"workflow", "url", "settings", "retries", "timeout_s", "poll_s"}
    assert keyframer["retries"]["type"] == "integer"
    assert options("keyframes", "fake-keyframer") == {}


def test_providers_carry_doctor_readiness_and_its_fix(
    make_project: MakeProject, tmp_path: Path, comfy: FakeComfyUI
) -> None:
    comfy.node_types = {
        node["class_type"]
        for path in WORKFLOWS.glob("*.json")
        for node in json.loads(path.read_text(encoding="utf-8")).values()
    }
    comfy.models = KEYFRAMER_MODELS  # the video model is not installed
    project = make_project(
        comfyui={"url": comfy.url},
        providers={
            "script": [
                {"name": "gemini-cli", "options": {"command": sys.executable}},
                {"name": "claude-cli", "options": {"command": str(tmp_path / "no-claude")}},
            ],
            "music": {"name": "comfyui-music", "options": {"url": f"{comfy.url}/wrong"}},
        },
    )
    server = UiServer(project)
    try:
        stages = stages_of(server.get("/api/providers"))
    finally:
        server.stop()

    def readiness(stage: str, name: str) -> dict[str, Any]:
        return choices_of(stages[stage])[name]["readiness"]

    assert readiness("script", "gemini-cli")["ready"] is True
    claude = readiness("script", "claude-cli")
    assert claude["ready"] is False
    assert claude["label"] == "CLI not found"
    assert "no-claude" in claude["fix"] and "options.command" in claude["fix"]

    assert readiness("keyframes", "comfyui-keyframer")["ready"] is True
    video = readiness("video", "comfyui-i2v")
    assert (video["ready"], video["label"]) == (False, "Model not found")
    assert "umt5_xxl_fp8_e4m3fn_scaled.safetensors missing" in video["fix"]
    assert "place it at models/" in video["fix"]
    music = readiness("music", "comfyui-music")
    assert (music["ready"], music["label"]) == (False, "ComfyUI not reachable")
    assert "Start ComfyUI" in music["fix"]

    assert readiness("narration", "fake-tts")["ready"] is True
    assert readiness("narration", "edge-tts")["ready"] is True
    # Readiness is read-only: nothing was submitted to ComfyUI.
    assert all(request.startswith("GET ") for request in comfy.requests)


def test_readiness_can_be_checked_for_a_config_not_yet_saved(
    ui: UiServer, project: Path, comfy: FakeComfyUI
) -> None:
    draft = {**document(project), "comfyui": {"url": f"{comfy.url}/wrong"}}

    stages = stages_of(post(ui, "/api/providers/check", {"document": draft}))

    keyframer = choices_of(stages["keyframes"])["comfyui-keyframer"]["readiness"]
    assert (
        keyframer["label"] == "ComfyUI not reachable" and f"{comfy.url}/wrong" in keyframer["fix"]
    )


def test_readiness_uses_provider_options_even_with_an_unrelated_validation_error(
    ui: UiServer, project: Path, tmp_path: Path
) -> None:
    command = (tmp_path / "custom-gemini").as_posix()
    draft = document(project)
    draft["width"] = "wide"
    draft["providers"]["script"] = {"name": "gemini-cli", "options": {"command": command}}

    script = stages_of(post(ui, "/api/providers/check", {"document": draft}))["script"]

    assert script["selected"] == "gemini-cli"
    assert command in choices_of(script)["gemini-cli"]["readiness"]["fix"]


# ------------------------------------------------------------------------------ validation


def test_the_config_is_served_with_its_schema_and_current_yaml(ui: UiServer, project: Path) -> None:
    reply = ui.get("/api/config")

    assert reply.status == 200
    config = reply.json()
    assert config["document"] == document(project)
    assert config["problem"] is None
    schema = config["schema"]["properties"]
    for setting in (
        "languages",
        "visuals",
        "output_name",
        "width",
        "height",
        "fps",
        "gates",
        "subtitles",
        "mix",
        "comfyui",
        "providers",
    ):
        assert setting in schema
    check = config["check"]
    assert check["ok"] is True and check["errors"] == []
    assert check["yaml"] == (project / "vidpipe.yaml").read_text(encoding="utf-8")
    # Defaults the file leaves out are filled in, as the CLI reads the config.
    assert check["effective"]["mix"] == {"music_level": 0.4, "duck_ratio": 8.0}


@pytest.mark.parametrize(
    ("change", "path"),
    [
        ({"width": "wide"}, "width"),
        ({"mix": {"music_level": 5}}, "mix.music_level"),
        ({"visuals": "sometimes"}, "visuals"),
        ({"languages": []}, "languages"),
        ({"subtitles": {"burn_in": True, "colour": "red"}}, "subtitles.colour"),
        ({"gates": ["scripts"]}, "gates"),
        ({"providers": {"narration": "nobody-tts"}}, "providers.narration"),
        ({"providers": {"script": [12, "fake-text"]}}, "providers.script"),
        (
            {"providers": {"keyframes": {"name": "comfyui-keyframer", "options": {"x": 1}}}},
            "providers.keyframes",
        ),
        ({"providers": {"video": {"name": "comfyui-i2v", "options": {"retries": -1}}}}, None),
    ],
)
def test_validation_reports_what_the_cli_rejects(
    ui: UiServer, project: Path, change: dict[str, Any], path: str | None
) -> None:
    draft = document(project)
    for key, value in change.items():
        draft[key] = {**draft[key], **value} if key == "providers" else value

    reply = post(ui, "/api/config/validate", {"document": draft})

    assert reply.status == 200
    check = reply.json()
    assert check["ok"] is False
    assert check["errors"], check
    assert all(error["message"] for error in check["errors"])
    expected = path or "providers.video"
    assert expected in {error["path"] for error in check["errors"]}
    # The CLI refuses the same config.
    (project / "vidpipe.yaml").write_text(check["yaml"], encoding="utf-8")
    assert main(["plan", str(project)]) != 0


def test_a_valid_draft_validates_and_the_cli_accepts_it(ui: UiServer, project: Path) -> None:
    draft = document(project)
    draft["providers"]["narration"] = {"name": "fake-tts", "options": {"max_seconds": 3.0}}
    draft["mix"] = {"music_level": 0.6}

    check = post(ui, "/api/config/validate", {"document": draft}).json()

    assert (check["ok"], check["errors"]) == (True, [])
    assert check["effective"]["mix"] == {"music_level": 0.6, "duck_ratio": 8.0}
    (project / "vidpipe.yaml").write_text(check["yaml"], encoding="utf-8")
    assert main(["plan", str(project)]) == 0


def test_a_config_file_that_is_not_yaml_is_reported(ui: UiServer, project: Path) -> None:
    (project / "vidpipe.yaml").write_text("languages: [en\n", encoding="utf-8")

    config = ui.get("/api/config").json()

    assert config["document"] is None
    assert "vidpipe.yaml" in config["problem"]


def test_validate_refuses_another_sites_origin(ui: UiServer, project: Path) -> None:
    reply = post(
        ui,
        "/api/config/validate",
        {"document": document(project)},
        headers={"Origin": "https://example.com"},
    )

    assert reply.status == 403


# ------------------------------------------------------------------------------ YAML view


def test_the_yaml_view_keeps_comments_and_order_and_writes_nothing(
    ui: UiServer, project: Path
) -> None:
    (project / "vidpipe.yaml").write_text(COMMENTED, encoding="utf-8")
    draft = yaml.safe_load(COMMENTED)
    draft["providers"]["narration"] = "edge-tts"
    draft["providers"]["script"] = ["fake-text", "claude-cli"]
    draft["width"] = 320

    check = post(ui, "/api/config/validate", {"document": draft}).json()

    assert check["ok"] is True, check["errors"]
    rendered: str = check["yaml"]
    assert yaml.safe_load(rendered) == draft
    for kept in (
        "# My video. Hand-written; keep these comments.",
        "languages: [en, am]",
        "visuals: shared   # one set of pictures",
        "#   music_level: 0.4",
    ):
        assert kept in rendered
    keys = [line.split(":")[0] for line in rendered.splitlines() if line[:1].isalpha()]
    assert keys == ["languages", "visuals", "output_name", "providers", "gates", "width"]
    assert (project / "vidpipe.yaml").read_text(encoding="utf-8") == COMMENTED


def test_preview_preserves_scalar_types_with_the_cli_yaml_loader(
    ui: UiServer, project: Path
) -> None:
    draft = document(project)
    draft["output_name"] = "on"
    draft["subtitles"] = {"fonts": {"no": "yes"}}
    draft["mix"] = {"music_level": 1e-5}

    check = post(ui, "/api/config/validate", {"document": draft}).json()

    assert check["ok"] is True
    assert yaml.safe_load(check["yaml"]) == draft


def test_editing_one_aliased_provider_keeps_the_other_provider(ui: UiServer, project: Path) -> None:
    config = COMMENTED.replace(
        "script: fake-text", "script: &text {name: fake-text, options: {}}"
    ).replace("storyboard: fake-text", "storyboard: *text")
    (project / "vidpipe.yaml").write_text(config, encoding="utf-8")
    draft = document(project)
    draft["providers"]["script"] = {"name": "gemini-cli", "options": {}}

    check = post(ui, "/api/config/validate", {"document": draft}).json()

    assert check["ok"] is True
    assert yaml.safe_load(check["yaml"]) == draft
