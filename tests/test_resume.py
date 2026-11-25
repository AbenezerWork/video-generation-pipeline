"""Seam 1 (artifact hashing, skip-unchanged and resume): the pipeline run on a project directory.

Observed only through external behavior: what ``vidpipe run`` reports per stage, which provider
calls a run makes, the artifacts on disk, and the artifact records in ``build/ledger.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import MakeProject
from tests.recording import Recorder, RecordingRegistry
from vidpipe import pipeline
from vidpipe.assembly import Assembler, AssemblyJob
from vidpipe.cli import main
from vidpipe.contracts import ProviderKind
from vidpipe.providers.fakes import FakeTTS
from vidpipe.registry import Registry, default_registry


def run_stages(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, str]:
    """Run the CLI; return {stage: status} parsed from its report."""
    capsys.readouterr()
    assert main(["run", *args]) == 0
    report: dict[str, str] = {}
    for line in capsys.readouterr().out.splitlines():
        stage, _provider, status = line.split(None, 2)
        report[stage] = status.split()[0]
    return report


def test_second_run_with_no_changes_executes_no_stages(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project()

    first = run_stages(capsys, str(project), "--until", "music")
    second = run_stages(capsys, str(project), "--until", "music")

    assert set(first.values()) == {"ran"}
    assert set(second) == set(first)
    assert set(second.values()) == {"skipped"}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ran_stages(result: pipeline.RunResult) -> set[str]:
    return {r.stage for r in result.manifest.stages if not r.skipped}


def test_editing_one_script_line_reruns_only_affected_downstream_stages(
    make_project: MakeProject,
) -> None:
    project = make_project()
    pipeline.run(project, until="music")

    script_path = project / "build" / "script.json"
    script = read_json(script_path)
    script["lines"][1]["text"] = "Dancing goats."  # much shorter: shot 2's narration changes length
    script_path.write_text(json.dumps(script), encoding="utf-8")

    recorder = Recorder()
    result = pipeline.run(project, until="music", registry=RecordingRegistry(recorder))

    # Keyframes (and everything upstream of the edit) are untouched.
    assert ran_stages(result) == {
        "translation",
        "storyboard",
        "narration",
        "fit-planning",
        "video",
        "music",
    }
    assert recorder.of(ProviderKind.KEYFRAMER) == []
    # Only shot 2 is re-narrated (in both languages) and re-animated.
    assert recorder.stems(ProviderKind.TTS) == ["am/shot_02", "en/shot_02"]
    assert [c.output_stem for c in recorder.of(ProviderKind.IMAGE_TO_VIDEO)] == ["shot_02"]
    assert len(recorder.of(ProviderKind.MUSIC)) == 1
    # The edit itself is kept, and flows into the translation.
    assert read_json(script_path)["lines"][1]["text"] == "Dancing goats."
    am = read_json(project / "build" / "translation" / "am.json")
    assert am["lines"][1]["text"] == "[am] Dancing goats."


def test_regenerating_an_artifact_with_identical_content_does_not_rerun_downstream(
    make_project: MakeProject,
) -> None:
    project = make_project()
    pipeline.run(project, until="music")

    brief = project / "brief.md"
    brief.write_text(brief.read_text(encoding="utf-8") + "\nA new sentence.\n", encoding="utf-8")
    result = pipeline.run(project, until="music")

    # The script is rewritten from the new brief, but the fake writer produces the same script,
    # so nothing after it has anything new to depend on.
    assert ran_stages(result) == {"brief", "script"}


def test_a_run_killed_midway_resumes_without_redoing_completed_shots(
    make_project: MakeProject,
) -> None:
    project = make_project()

    # "Kill" the run on the fourth narration call: English is done, Amharic hasn't started.
    first = Recorder()
    first.crash_when = lambda c: c.kind == ProviderKind.TTS and len(first.of(c.kind)) == 3
    with pytest.raises(KeyboardInterrupt):
        pipeline.run(project, until="music", registry=RecordingRegistry(first))
    assert first.stems(ProviderKind.TTS) == ["en/shot_01", "en/shot_02", "en/shot_03"]

    resumed = Recorder()
    pipeline.run(project, until="music", registry=RecordingRegistry(resumed))

    # Completed work (script, translation, storyboard and the English narration) is not redone...
    assert resumed.of(ProviderKind.TEXT) == []
    assert resumed.of(ProviderKind.TRANSLATION) == []
    assert resumed.stems(ProviderKind.TTS) == ["am/shot_01", "am/shot_02", "am/shot_03"]
    # ...and the stages after the interruption each run once per shot.
    assert len(resumed.of(ProviderKind.KEYFRAMER)) == 3
    assert len(resumed.of(ProviderKind.IMAGE_TO_VIDEO)) == 3
    assert len(resumed.of(ProviderKind.MUSIC)) == 1


def test_a_run_killed_between_shots_of_one_stage_only_redoes_the_unfinished_shots(
    make_project: MakeProject,
) -> None:
    project = make_project()

    first = Recorder()
    first.crash_when = lambda c: (
        c.kind == ProviderKind.IMAGE_TO_VIDEO and c.output_stem == "shot_03"
    )
    with pytest.raises(KeyboardInterrupt):
        pipeline.run(project, until="music", registry=RecordingRegistry(first))
    assert [c.output_stem for c in first.of(ProviderKind.IMAGE_TO_VIDEO)] == ["shot_01", "shot_02"]

    resumed = Recorder()
    result = pipeline.run(project, until="music", registry=RecordingRegistry(resumed))

    assert [c.output_stem for c in resumed.of(ProviderKind.IMAGE_TO_VIDEO)] == ["shot_03"]
    assert resumed.of(ProviderKind.KEYFRAMER) == []
    assert resumed.of(ProviderKind.TTS) == []
    assert ran_stages(result) == {"video", "music"}
    assert len(read_json(project / "build" / "video.json")["items"]) == 3


def test_swapping_a_provider_reruns_that_stage_and_what_depends_on_it(
    make_project: MakeProject,
) -> None:
    project = make_project()
    pipeline.run(project, until="music")

    config = project / "vidpipe.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "translation: fake-translation", "translation: fake-translation-upper"
        ),
        encoding="utf-8",
    )
    recorder = Recorder()
    result = pipeline.run(project, until="music", registry=RecordingRegistry(recorder))

    # The Amharic text changed, so it is narrated again and the fit plan (which records the text it
    # cut) is re-derived; the fake narrator's audio and durations depend only on the language, so
    # the new clips are byte-identical and nothing after the plan reruns.
    assert ran_stages(result) == {"translation", "narration", "fit-planning"}
    assert recorder.stems(ProviderKind.TTS) == ["am/shot_01", "am/shot_02", "am/shot_03"]
    assert recorder.of(ProviderKind.KEYFRAMER) == []
    assert recorder.of(ProviderKind.TEXT) == []


def sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_artifact_records_hold_provider_seed_gpu_time_and_content_hashes(
    make_project: MakeProject,
) -> None:
    project = make_project()
    pipeline.run(project, until="music")

    artifacts = read_json(project / "build" / "ledger.json")["artifacts"]

    keyframe = artifacts["keyframes/shot_02"]
    assert keyframe["provider"] == "fake-keyframer"
    assert keyframe["seed"] == 2
    assert keyframe["gpu_seconds"] > 0  # the fake stands in for a GPU provider
    assert keyframe["parameters"] == {"width": 160, "height": 90}
    (output,) = keyframe["outputs"]
    assert output["path"] == "build/keyframes/shot_02.png"
    assert output["sha256"] == sha256(project / output["path"])

    narration = artifacts["narration/am/shot_01"]
    assert narration["provider"] == "fake-tts"
    assert narration["gpu_seconds"] == 0  # a TTS provider is not GPU-bound
    assert narration["wall_seconds"] >= 0
    assert narration["parameters"]["language"] == "am"

    video = artifacts["video/shot_03"]
    assert (video["provider"], video["seed"]) == ("fake-i2v", 3)
    assert video["gpu_seconds"] > 0

    # Every generated artifact says which provider (if any) made it, and keeps its input hash.
    assert {a["provider"] for a in artifacts.values()} == {
        None,
        "fake-text",
        "fake-translation",
        "fake-tts",
        "fake-keyframer",
        "fake-i2v",
        "fake-music",
    }
    assert all(len(a["input_hash"]) == 64 for a in artifacts.values())


@pytest.mark.needs_ffmpeg
def test_assembly_is_skipped_when_nothing_changed_and_redone_per_language_otherwise(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project()
    assert set(run_stages(capsys, str(project)).values()) == {"ran"}
    renders = {p.name: p.stat().st_mtime_ns for p in (project / "out").glob("*.mp4")}
    assert set(renders) == {"demo_en.mp4", "demo_am.mp4"}

    assert set(run_stages(capsys, str(project)).values()) == {"skipped"}
    assert {p.name: p.stat().st_mtime_ns for p in (project / "out").glob("*.mp4")} == renders


class StubAssembler(Assembler):
    """Stands in for ffmpeg: writes a small file per language and remembers what it was asked."""

    def __init__(self) -> None:
        self.rendered: list[str] = []

    def problems(self) -> list[str]:
        return []

    def assemble(self, job: AssemblyJob) -> list[Path]:
        written: list[Path] = []
        for render in job.renders:
            render.output.parent.mkdir(parents=True, exist_ok=True)
            render.output.write_bytes(f"{render.language}:{len(render.segments)}".encode())
            self.rendered.append(render.language)
            written.append(render.output)
        return written


def test_changing_one_languages_narration_only_rerenders_that_language(
    make_project: MakeProject,
) -> None:
    project = make_project()
    assembler = StubAssembler()
    pipeline.run(project, assembler=assembler)
    assert sorted(assembler.rendered) == ["am", "en"]

    assembler.rendered.clear()
    result = pipeline.run(project, assembler=assembler)
    assert assembler.rendered == [] and ran_stages(result) == set()

    # Hand-edit the Amharic translation of line 2 to a slightly different length: the Amharic
    # narration changes, but the shared clip for that shot (sized to the longer narration, rounded
    # up to a quarter second) does not, so only the Amharic render is redone.
    am_path = project / "build" / "translation" / "am.json"
    am = read_json(am_path)
    am["lines"][1]["text"] = "[am] " + "x" * 64  # 69 chars instead of 70: 0.05 s shorter
    am_path.write_text(json.dumps(am), encoding="utf-8")
    result = pipeline.run(project, assembler=assembler)
    assert assembler.rendered == ["am"]
    assert "assembly" in ran_stages(result)
    assert (project / "out" / "demo_en.mp4").read_bytes() == b"en:3"


class VoicePackTTS(FakeTTS):
    """Like edge-tts: takes its options as constructor arguments instead of keeping them."""

    name = "fake-tts-voice-pack"

    def __init__(self, *, voice_pack: str = "v1") -> None:
        super().__init__()
        self.voice_pack = voice_pack


def test_changing_a_providers_configured_options_regenerates_what_it_made(
    make_project: MakeProject,
) -> None:
    registry = Registry()
    for cls in default_registry().classes():
        registry.register(cls)
    registry.register(VoicePackTTS)

    def narrate_with(project: Path, voice_pack: str) -> Recorder:
        config = yaml.safe_load((project / "vidpipe.yaml").read_text(encoding="utf-8"))
        config["providers"]["narration"] = {
            "name": VoicePackTTS.name,
            "options": {"voice_pack": voice_pack},
        }
        text: str = yaml.safe_dump(config)  # pyright: ignore[reportUnknownMemberType]
        (project / "vidpipe.yaml").write_text(text, encoding="utf-8")
        recorder = Recorder()
        pipeline.run(project, until="music", registry=RecordingRegistry(recorder, registry))
        return recorder

    project = make_project()
    assert len(narrate_with(project, "v1").of(ProviderKind.TTS)) == 6
    assert narrate_with(project, "v1").of(ProviderKind.TTS) == []

    # Every clip, in both languages, is made again under the new option.
    assert len(narrate_with(project, "v2").of(ProviderKind.TTS)) == 6
    ledger = read_json(project / "build" / "ledger.json")["artifacts"]
    assert ledger["narration/en/shot_01"]["provider_options"] == {"voice_pack": "v2"}
