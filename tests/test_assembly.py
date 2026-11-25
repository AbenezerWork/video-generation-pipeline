"""Seam 1 for assembly: a full run through the CLI, then ffprobe, the SRT sidecars, the audio mix
and the burned-in frames of the final renders are inspected. Nothing here calls the assembler
directly.
"""

from __future__ import annotations

import array
import json
import math
import os
import shutil
import stat
import subprocess
import wave
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import MakeProject, ffprobe, nothing_generated
from tests.test_resume import StubAssembler
from vidpipe import pipeline
from vidpipe.assembly import FFMPEG_DIR_ENV, find_tool
from vidpipe.cli import main

BUNDLED_FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
#: Two Ge'ez strings of the same length made of different letters: if the font lacked the glyphs,
#: both would render as the same row of "missing glyph" boxes and the two frames would match.
GEEZ_A = "ሀሁሂሃሄህሆ"
GEEZ_B = "ለሉሊላሌልሎ"
GEEZ_C = "ቡና ከኢትዮጵያ"
#: Large letters, so a small test frame has enough text pixels to measure.
BIG_TEXT = {"font_size": 44}


def run_cli(*args: str) -> int:
    return main(list(args))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def edit_config(project: Path, **changes: Any) -> None:
    path = project / "vidpipe.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config.update(changes)
    text: str = yaml.safe_dump(config)  # pyright: ignore[reportUnknownMemberType]
    path.write_text(text, encoding="utf-8")


# ------------------------------------------------------------------------------------ SRT


def srt_time(text: str) -> float:
    h, m, rest = text.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def read_srt(path: Path) -> list[tuple[float, float, str]]:
    cues: list[tuple[float, float, str]] = []
    for block in path.read_text(encoding="utf-8").strip().split("\n\n"):
        lines = block.split("\n")
        start, end = lines[1].split(" --> ")
        cues.append((srt_time(start), srt_time(end), "\n".join(lines[2:])))
    return cues


def narration_timeline(project: Path, language: str) -> list[tuple[float, float]]:
    """Where each shot's narration sits in a render: back to back, in storyboard order."""
    narration = read_json(project / "build" / "narration.json")["clips"]
    timeline: list[tuple[float, float]] = []
    offset = 0.0
    for shot in read_json(project / "build" / "storyboard.json")["shots"]:
        clip = next(
            c for c in narration if c["shot_id"] == shot["id"] and c["language"] == language
        )
        timeline.append((offset, offset + clip["duration_s"]))
        offset += clip["duration_s"]
    return timeline


# ------------------------------------------------------------------------------------ media


def decode_audio(path: Path, rate: int = 8000) -> array.array[int]:
    tool = find_tool("ffmpeg")
    assert tool is not None
    raw = subprocess.run(
        [tool, "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(rate)]
        + ["-f", "s16le", "-"],
        check=True,
        capture_output=True,
    ).stdout
    samples = array.array("h")
    samples.frombytes(raw)
    return samples


def tone_amplitude(samples: array.array[int], rate: int, frequency: float, t0: float, t1: float):
    """Amplitude (0..1 of full scale) of one frequency in a window, by the Goertzel algorithm."""
    window = samples[int(t0 * rate) : int(t1 * rate)]
    coeff = 2 * math.cos(2 * math.pi * frequency / rate)
    s1 = s2 = 0.0
    for x in window:
        s1, s2 = x / 32768 + coeff * s1 - s2, s1
    power = s1 * s1 + s2 * s2 - coeff * s1 * s2
    return 2 * math.sqrt(max(power, 0.0)) / len(window)


def music_frequency(wav_path: Path) -> int:
    with wave.open(str(wav_path)) as wav:
        rate = wav.getframerate()
        samples = array.array("h")
        samples.frombytes(wav.readframes(rate))  # the first second is plenty
    return max(range(100, 181), key=lambda f: tone_amplitude(samples, rate, f, 0, 1))


def gray_frame(video: Path, at_s: float, size: tuple[int, int]) -> bytes:
    tool = find_tool("ffmpeg")
    assert tool is not None
    raw = subprocess.run(
        [tool, "-v", "error", "-ss", str(at_s), "-i", str(video), "-frames:v", "1"]
        + ["-f", "rawvideo", "-pix_fmt", "gray", "-"],
        check=True,
        capture_output=True,
    ).stdout
    assert len(raw) == size[0] * size[1]
    return raw


def text_mask(burned: bytes, plain: bytes, size: tuple[int, int]) -> set[int]:
    """The white fill of the subtitle letters in the lower third: pixels that are white in the
    burned frame and clearly were not in the plain one. (Their outline is left out: how much of it
    stands out depends on the background colour, the white does not.)"""
    width, height = size
    return {
        i
        for i in range(width * height * 2 // 3, width * height)
        if burned[i] >= 215 and burned[i] - plain[i] > 40
    }


# ------------------------------------------------------------------------------------ tests


@pytest.mark.needs_ffmpeg
def test_each_render_is_a_playable_video_with_audio_within_90_seconds(
    make_project: MakeProject,
) -> None:
    project = make_project()

    assert run_cli("run", str(project)) == 0

    expected = read_json(project / "build" / "fit_plan.json")["render_seconds"]
    for lang in ("en", "am"):
        probe = ffprobe(project / "out" / f"demo_{lang}.mp4")
        streams = {s["codec_type"]: s for s in probe["streams"]}
        assert sorted(streams) == ["audio", "video"]
        assert (streams["video"]["width"], streams["video"]["height"]) == (160, 90)
        duration = float(probe["format"]["duration"])
        assert duration == pytest.approx(expected[lang], abs=0.2)
        assert duration <= 90


@pytest.mark.needs_ffmpeg
def test_sidecar_srt_files_follow_the_narration_timing(make_project: MakeProject) -> None:
    project = make_project()

    assert run_cli("run", str(project)) == 0

    for lang in ("en", "am"):
        cues = read_srt(project / "out" / f"demo_{lang}.srt")
        timeline = narration_timeline(project, lang)
        script = read_json(
            project / "build" / ("script.json" if lang == "en" else f"translation/{lang}.json")
        )
        assert [text for _, _, text in cues] == [line["text"] for line in script["lines"]]
        for (start, end, _), (shot_start, shot_end) in zip(cues, timeline, strict=True):
            assert start == pytest.approx(shot_start, abs=0.002)
            assert end == pytest.approx(shot_end, abs=0.002)
        probe = ffprobe(project / "out" / f"demo_{lang}.mp4")
        assert cues[-1][1] == pytest.approx(float(probe["format"]["duration"]), abs=0.2)


@pytest.mark.needs_ffmpeg
def test_music_level_drops_under_narration(make_project: MakeProject) -> None:
    # Each shot: 2 s of narration, then 2 s of silence, so the music is heard both ways.
    project = make_project(
        providers={
            "narration": {
                "name": "fake-tts",
                "options": {"max_seconds": 2.0, "tail_silence_s": 2.0},
            }
        }
    )

    assert run_cli("run", str(project)) == 0

    rate = 8000
    samples = decode_audio(project / "out" / "demo_en.mp4", rate)
    frequency = music_frequency(project / "build" / "music" / "music.wav")
    for start in (0.0, 4.0, 8.0):  # each shot
        under_voice = tone_amplitude(samples, rate, frequency, start + 0.5, start + 1.5)
        in_silence = tone_amplitude(samples, rate, frequency, start + 3.2, start + 3.9)
        assert in_silence > 0.04  # the music is clearly there when nobody speaks
        assert under_voice < 0.4 * in_silence  # and at least 8 dB lower under the voice


@pytest.mark.needs_ffmpeg
def test_the_voice_stays_clear_over_the_music(make_project: MakeProject) -> None:
    project = make_project(
        providers={"narration": {"name": "fake-tts", "options": {"max_seconds": 2.0}}}
    )

    assert run_cli("run", str(project)) == 0

    rate = 8000
    samples = decode_audio(project / "out" / "demo_en.mp4", rate)
    music = music_frequency(project / "build" / "music" / "music.wav")
    voice_hz = max(range(180, 300), key=lambda f: tone_amplitude(samples, rate, f, 0.5, 1.5))
    voice = tone_amplitude(samples, rate, voice_hz, 0.5, 1.5)
    assert voice > 3 * tone_amplitude(samples, rate, music, 0.5, 1.5)


def set_translation(project: Path, lines: list[str]) -> None:
    """Hand-edit the Amharic translation (the fake translator does not write Ge'ez)."""
    assert run_cli("run", str(project), "--until", "translation") == 0
    path = project / "build" / "translation" / "am.json"
    data = read_json(path)
    for line, text in zip(data["lines"], lines, strict=True):
        line["text"] = text
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.mark.needs_ffmpeg
def test_amharic_subtitles_render_real_ethiopic_glyphs(
    make_project: MakeProject, tmp_path: Path
) -> None:
    size = (480, 270)
    project = make_project(width=size[0], height=size[1], subtitles=BIG_TEXT)
    set_translation(project, [GEEZ_A, GEEZ_B, GEEZ_C])
    plain = tmp_path / "plain-project"
    shutil.copytree(project, plain)
    edit_config(plain, subtitles={"burn_in": False})

    assert run_cli("run", str(project)) == 0
    assert run_cli("run", str(plain)) == 0

    timeline = narration_timeline(project, "am")
    masks: list[set[int]] = []
    for start, end in timeline[:2]:
        at = (start + end) / 2
        burned = gray_frame(project / "out" / "demo_am.mp4", at, size)
        unburned = gray_frame(plain / "out" / "demo_am.mp4", at, size)
        masks.append(text_mask(burned, unburned, size))
    assert all(len(mask) > 400 for mask in masks)  # text is on screen in the lower third
    # Same-length strings of different letters: missing-glyph boxes would draw the same pixels (an
    # overlap of about 0.84 when measured on boxes), real letters mostly do not (about 0.13).
    overlap = len(masks[0] & masks[1]) / len(masks[0] | masks[1])
    assert overlap < 0.5


@pytest.mark.needs_ffmpeg
def test_english_subtitles_are_burned_in_and_the_option_turns_them_off(
    make_project: MakeProject, tmp_path: Path
) -> None:
    size = (480, 270)
    project = make_project(width=size[0], height=size[1], subtitles=BIG_TEXT)
    plain = tmp_path / "plain-project"
    shutil.copytree(project, plain)
    edit_config(plain, subtitles={"burn_in": False})

    assert run_cli("run", str(project)) == 0
    assert run_cli("run", str(plain)) == 0

    start, end = narration_timeline(project, "en")[0]
    burned = gray_frame(project / "out" / "demo_en.mp4", (start + end) / 2, size)
    unburned = gray_frame(plain / "out" / "demo_en.mp4", (start + end) / 2, size)
    assert len(text_mask(burned, unburned, size)) > 400
    top = size[0] * size[1] // 2  # above the subtitle band the frames are the same picture
    assert sum(abs(burned[i] - unburned[i]) for i in range(top)) / top < 1.0
    assert (plain / "out" / "demo_en.srt").is_file()  # the sidecar is written either way


@pytest.mark.needs_ffmpeg
def test_burn_in_survives_awkward_paths(make_project: MakeProject, tmp_path: Path) -> None:
    """A drive colon, spaces, quotes, brackets, commas and semicolons in the project path and in
    the fonts folder must not break the ffmpeg filter."""
    size = (480, 270)
    made = make_project(width=size[0], height=size[1])
    project = tmp_path / "it's [an] odd, dir; a=b"
    shutil.move(made, project)
    odd_fonts = project / "fo'nts [x], y;z=1"
    shutil.copytree(BUNDLED_FONTS, odd_fonts)
    edit_config(project, subtitles={**BIG_TEXT, "fonts_dir": odd_fonts.name})
    set_translation(project, [GEEZ_A, GEEZ_B, GEEZ_C])
    plain = tmp_path / "plain-project"
    shutil.copytree(project, plain)
    edit_config(plain, subtitles={"burn_in": False, "fonts_dir": odd_fonts.name})

    assert run_cli("run", str(project)) == 0
    assert run_cli("run", str(plain)) == 0

    start, end = narration_timeline(project, "am")[0]
    burned = gray_frame(project / "out" / "demo_am.mp4", (start + end) / 2, size)
    unburned = gray_frame(plain / "out" / "demo_am.mp4", (start + end) / 2, size)
    assert len(text_mask(burned, unburned, size)) > 400


# ------------------------------------------------------------------- plan-time checks


def test_a_missing_fonts_folder_is_a_plan_error_before_any_generation(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(subtitles={"fonts_dir": "no-such-fonts"})

    assert run_cli("plan", str(project)) == 1
    err = capsys.readouterr().err
    assert "no-such-fonts" in err and "fonts" in err

    assert run_cli("run", str(project)) == 1
    assert nothing_generated(project)


def test_a_fonts_folder_without_the_needed_font_names_it(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(subtitles={"fonts_dir": "empty-fonts"})
    (project / "empty-fonts").mkdir()

    assert run_cli("plan", str(project)) == 1

    err = capsys.readouterr().err
    assert "Noto Sans Ethiopic" in err and "empty-fonts" in err and "'am'" in err


def test_fonts_are_not_needed_when_subtitles_are_not_burned_in(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(subtitles={"burn_in": False, "fonts_dir": "no-such-fonts"})

    run_cli("plan", str(project))

    assert "fonts" not in capsys.readouterr().err


def test_the_bundled_font_is_found_without_any_configuration(
    make_project: MakeProject, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project()  # the sample config names no fonts folder

    run_cli("plan", str(project))

    assert "fonts" not in capsys.readouterr().err


def test_an_ffmpeg_without_libass_is_a_plan_error(
    make_project: MakeProject,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bin_dir = tmp_path / "fake-ffmpeg"
    bin_dir.mkdir()
    listing = " ... anull A->A Pass the source unchanged\n ... null V->V Do nothing\n"
    (bin_dir / "filters.txt").write_text(listing, encoding="utf-8")
    for tool in ("ffmpeg", "ffprobe"):
        if os.name == "nt":
            (bin_dir / f"{tool}.cmd").write_text(
                f'@type "{bin_dir / "filters.txt"}"\n', encoding="utf-8"
            )
        else:
            script = bin_dir / tool
            script.write_text(f'#!/bin/sh\ncat "{bin_dir / "filters.txt"}"\n', encoding="utf-8")
            script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv(FFMPEG_DIR_ENV, str(bin_dir))
    project = make_project()

    assert run_cli("plan", str(project)) == 1

    err = capsys.readouterr().err
    assert "subtitles" in err and "libass" in err
    assert "sidechaincompress" in err


# ----------------------------------------------------------- re-rendering (no ffmpeg needed)


def test_subtitle_and_mix_settings_rerender_assembly_and_nothing_before_it(
    make_project: MakeProject,
) -> None:
    project = make_project()
    assembler = StubAssembler()
    pipeline.run(project, assembler=assembler)
    assert sorted(assembler.rendered) == ["am", "en"]
    assert (project / "out" / "demo_en.srt").is_file()  # the sidecar needs no ffmpeg

    for change in ({"subtitles": {"font_size": 30}}, {"mix": {"music_level": 0.2}}):
        assembler.rendered.clear()
        edit_config(project, **change)
        result = pipeline.run(project, assembler=assembler)
        assert sorted(assembler.rendered) == ["am", "en"]
        assert {r.stage for r in result.manifest.stages if not r.skipped} == {"assembly"}


def test_editing_a_translation_rewrites_that_languages_srt_only(make_project: MakeProject) -> None:
    project = make_project()
    assembler = StubAssembler()
    pipeline.run(project, assembler=assembler)
    english = (project / "out" / "demo_en.srt").read_text(encoding="utf-8")

    am_path = project / "build" / "translation" / "am.json"
    am = read_json(am_path)
    am["lines"][0]["text"] = GEEZ_A
    am_path.write_text(json.dumps(am, ensure_ascii=False), encoding="utf-8")
    pipeline.run(project, assembler=assembler)

    assert GEEZ_A in (project / "out" / "demo_am.srt").read_text(encoding="utf-8")
    assert (project / "out" / "demo_en.srt").read_text(encoding="utf-8") == english
