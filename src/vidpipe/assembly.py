"""Final assembly behind a small interface.

The assembler turns an :class:`AssemblyJob` (per-language lists of timed shots, each a list of
clips, plus music, subtitles and mix settings) into rendered files. :class:`FfmpegAssembler` shells
out to ffmpeg: it concatenates the clips (each played at its planned speed), joins the narration,
mixes music in under it with ducking, and burns the subtitles in.

The sidecar ``.srt`` is written by the assembly stage before the assembler runs (it is plain text
and needs no ffmpeg); the assembler only burns it in.
"""

from __future__ import annotations

import functools
import json
import math
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, Field

from vidpipe.contracts import GenerationError
from vidpipe.subtitles import ass_filter, subtitles_filter


class AssemblyError(Exception):
    pass


class ClipPlay(BaseModel):
    """One clip of a shot, as the render plays it."""

    video: Path
    #: Playback rate of the video clip: below 1 plays it slower so it lasts longer.
    speed: float = 1.0
    #: How much of the clip is used (the rest is trimmed); ``None`` for all of it.
    source_s: float | None = None
    #: How long it plays in the render.
    seconds: float


class ShotSegment(BaseModel):
    shot_id: int
    narration: Path
    #: How long the shot lasts in the render (the narration's length).
    seconds: float
    #: The clips played back to back. A shot has one, plus one per continuation clip.
    clips: list[ClipPlay]


class SubtitleTrack(BaseModel):
    """The ``.srt`` of one render (timed from the start of the render) and how to draw it."""

    srt: Path
    burn_in: bool = True
    #: Folder libass finds fonts in, and the family to force (``None``: libass's default font).
    fonts_dir: Path | None = None
    font: str | None = None
    #: In libass script units, where the video's height is 288.
    font_size: int = 20
    margin_v: int = 12


class MixSettings(BaseModel):
    #: Music gain while nobody speaks.
    music_level: float = 0.4
    #: Ratio of the sidechain compressor that pushes the music down under narration.
    duck_ratio: float = 8.0
    loudness_lufs: float = -14.0


class EndCard(BaseModel):
    """A closing card after the last shot: an ``.ass`` file drawn on black for ``seconds``."""

    ass: Path
    seconds: float
    #: Folder libass finds the card's font in (``None``: system fonts).
    fonts_dir: Path | None = None


class LanguageRender(BaseModel):
    language: str
    output: Path
    segments: list[ShotSegment]
    music: Path | None = None
    subtitles: SubtitleTrack | None = None
    end_card: EndCard | None = None


class AssemblyJob(BaseModel):
    renders: list[LanguageRender]
    width: int
    height: int
    fps: int
    mix: MixSettings = Field(default_factory=MixSettings)


class Assembler(ABC):
    @abstractmethod
    def problems(self) -> list[str]:
        """Reasons assembly cannot run here (checked at plan time); empty when ready."""

    @abstractmethod
    def assemble(self, job: AssemblyJob) -> list[Path]:
        """Render every language in the job; return the written files."""


FFMPEG_DIR_ENV = "VIDPIPE_FFMPEG_DIR"


def find_tool(name: str) -> str | None:
    """Find a media binary in the configured portable bin directory or on PATH."""
    if directory := os.environ.get(FFMPEG_DIR_ENV):
        return shutil.which(str((Path(directory).expanduser() / name).resolve()))
    return shutil.which(name)


def missing_tool_problem(name: str) -> str:
    directory = os.environ.get(FFMPEG_DIR_ENV)
    where = f"in {directory}" if directory else "on PATH"
    return (
        f"{name} not found {where}; install FFmpeg with libass and set "
        f"`{FFMPEG_DIR_ENV}` to the bin directory containing ffmpeg and ffprobe"
    )


def extract_last_frame(video: Path, image: Path) -> None:
    """Decode the final displayed frame of a short clip into a PNG conditioning image."""
    ffmpeg = find_tool("ffmpeg")
    if ffmpeg is None:
        raise GenerationError(missing_tool_problem("ffmpeg"))
    try:
        # Clips last only a few seconds. Reversing their decoded frames avoids guessing a
        # seek position from rounded duration or relying on the container's frame count.
        result = subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-i",
                str(video),
                "-map",
                "0:v:0",
                "-vf",
                "reverse",
                "-frames:v",
                "1",
                "-update",
                "1",
                str(image),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GenerationError(f"could not extract the last frame of {video.name}: {exc}") from exc
    if result.returncode != 0 or not image.is_file():
        reason = result.stderr.strip() or "no frame was decoded"
        raise GenerationError(f"could not extract the last frame of {video.name}: {reason}")


@functools.cache
def ffmpeg_filters(ffmpeg: str) -> frozenset[str]:
    """Names of the filters this ffmpeg was built with (empty if it cannot be asked)."""
    try:
        completed = subprocess.run(
            [ffmpeg, "-hide_banner", "-filters"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return frozenset()
    if completed.returncode != 0:
        return frozenset()
    return frozenset(
        parts[1] for line in completed.stdout.splitlines() if len(parts := line.split()) > 2
    )


#: Filters assembly needs beyond the basics, and why.
REQUIRED_FILTERS = {
    "subtitles": "burned-in subtitles need ffmpeg built with libass",
    "sidechaincompress": "ducking the music under narration needs it",
    "loudnorm": "the final mix uses two-pass loudness normalization",
}


class FfmpegAssembler(Assembler):
    #: Sidechain compressor settings besides the ratio: narration above this (linear, full scale
    #: 1.0) ducks the music; it comes back over ``RELEASE_MS`` once the voice stops.
    DUCK_THRESHOLD = 0.03
    ATTACK_MS = 20
    RELEASE_MS = 400

    def problems(self) -> list[str]:
        found = [
            missing_tool_problem(tool) for tool in ("ffmpeg", "ffprobe") if find_tool(tool) is None
        ]
        ffmpeg = find_tool("ffmpeg")
        if ffmpeg is not None:
            available = ffmpeg_filters(ffmpeg)
            found += [
                f"ffmpeg has no {name!r} filter ({why}); replace {ffmpeg} with a build "
                f"that includes {name!r}"
                for name, why in REQUIRED_FILTERS.items()
                if name not in available
            ]
        return found

    def assemble(self, job: AssemblyJob) -> list[Path]:
        ffmpeg = find_tool("ffmpeg")
        if ffmpeg is None:
            raise AssemblyError(missing_tool_problem("ffmpeg"))
        written: list[Path] = []
        for render in job.renders:
            render.output.parent.mkdir(parents=True, exist_ok=True)
            normalization = self._measure(ffmpeg, job, render)
            command = [ffmpeg, "-y", "-v", "error", *self.arguments(job, render, normalization)]
            result = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8", errors="replace"
            )
            if result.returncode != 0:
                raise AssemblyError(f"ffmpeg failed for {render.language}: {result.stderr.strip()}")
            written.append(render.output)
        return written

    def arguments(
        self, job: AssemblyJob, render: LanguageRender, normalization: str | None = None
    ) -> list[str]:
        """ffmpeg arguments (after the binary) rendering one language."""
        clips = [clip for segment in render.segments for clip in segment.clips]
        args: list[str] = []
        for clip in clips:
            args += ["-i", str(clip.video)]
        audio_args, audio_parts, audio_label, total = self._audio(job, render, first=len(clips))
        args += audio_args

        parts: list[str] = []
        shots: list[str] = []
        next_clip = 0
        for i, seg in enumerate(render.segments):
            shot_clips: list[str] = []
            for clip in seg.clips:
                label = f"c{next_clip}"
                parts.append(self._clip_chain(job, clip, next_clip, label, trim=len(seg.clips) > 1))
                shot_clips.append(f"[{label}]")
                next_clip += 1
            source = shot_clips[0]
            if len(shot_clips) > 1:
                parts.append(f"{''.join(shot_clips)}concat=n={len(shot_clips)}:v=1:a=0[s{i}]")
                source = f"[s{i}]"
            parts.append(
                f"{source}tpad=stop_mode=clone:stop_duration={seg.seconds},"
                f"trim=duration={seg.seconds},setpts=PTS-STARTPTS[v{i}]"
            )
            shots.append(f"[v{i}]")
        n = len(render.segments)
        card = render.end_card
        burn = render.subtitles is not None and render.subtitles.burn_in
        shots_label = "shots" if card else "vout"
        video_label = "joined" if burn else shots_label
        parts.append(f"{''.join(shots)}concat=n={n}:v=1:a=0[{video_label}]")
        if render.subtitles is not None and burn:
            track = render.subtitles
            filter_ = subtitles_filter(
                track.srt,
                fonts_dir=track.fonts_dir,
                font=track.font,
                font_size=track.font_size,
                margin_v=track.margin_v,
            )
            parts.append(f"[joined]{filter_}[{shots_label}]")
        if card is not None:
            # The card is drawn on black after the last shot; the narration is silent under it.
            parts.append(
                f"color=c=black:s={job.width}x{job.height}:r={job.fps}:d={card.seconds},"
                f"setsar=1,{ass_filter(card.ass, fonts_dir=card.fonts_dir)}[card]"
            )
            parts.append("[shots][card]concat=n=2:v=1:a=0[vout]")

        parts += audio_parts
        if normalization is not None:
            parts.append(f"[{audio_label}]{normalization},aresample=48000[normalized]")
            audio_label = "normalized"

        args += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-map", f"[{audio_label}]"]
        args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", f"{total}"]
        args += ["-movflags", "+faststart", str(render.output)]
        return args

    def _audio(
        self, job: AssemblyJob, render: LanguageRender, *, first: int = 0
    ) -> tuple[list[str], list[str], str, float]:
        args: list[str] = []
        parts: list[str] = []
        total = sum(s.seconds for s in render.segments)
        for i, segment in enumerate(render.segments):
            args += ["-i", str(segment.narration)]
            parts.append(
                f"[{first + i}:a]aresample=48000,aformat=channel_layouts=stereo,apad,"
                f"atrim=duration={segment.seconds},asetpts=PTS-STARTPTS[a{i}]"
            )
        n = len(render.segments)
        card = render.end_card
        spoken = "".join(f"[a{i}]" for i in range(n))
        parts.append(f"{spoken}concat=n={n}:v=0:a=1[{'spoken' if card else 'narration'}]")
        if card is not None:
            total += card.seconds
            parts.append(f"[spoken]apad=whole_dur={total}[narration]")
        if render.music is None:
            return args, parts, "narration", total
        args += ["-i", str(render.music)]
        parts += self._mix(
            job, total, music_input=first + n, fade_out_s=card.seconds if card else 0.0
        )
        return args, parts, "mix", total

    def _measure(self, ffmpeg: str, job: AssemblyJob, render: LanguageRender) -> str | None:
        """Measure the exact audio graph, then pass its statistics to the final render."""
        args, parts, label, _ = self._audio(job, render)
        target = f"loudnorm=I={job.mix.loudness_lufs}:TP=-1:LRA=11"
        parts.append(f"[{label}]{target}:print_format=json[analysis]")
        result = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-nostats",
                *args,
                "-filter_complex",
                ";".join(parts),
                "-map",
                "[analysis]",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            raise AssemblyError(f"loudnorm failed for {render.language}: {result.stderr.strip()}")
        try:
            stats = json.loads(result.stderr[result.stderr.rindex("{") :])
            measured = {
                "measured_I": float(stats["input_i"]),
                "measured_TP": float(stats["input_tp"]),
                "measured_LRA": float(stats["input_lra"]),
                "measured_thresh": float(stats["input_thresh"]),
                "offset": float(stats["target_offset"]),
            }
        except (ValueError, KeyError, TypeError) as exc:
            raise AssemblyError(
                f"loudnorm returned invalid statistics for {render.language}"
            ) from exc
        if not math.isfinite(measured["measured_I"]):
            return None  # no measurable signal in the mix
        if not all(math.isfinite(value) for value in measured.values()):
            raise AssemblyError(f"loudnorm returned invalid statistics for {render.language}")
        return ":".join([target, "linear=true", *(f"{k}={v}" for k, v in measured.items())])

    @staticmethod
    def _clip_chain(job: AssemblyJob, clip: ClipPlay, index: int, label: str, *, trim: bool) -> str:
        """One clip: cut to the part used, played at its planned speed, in the render's format.
        Clips of a multi-clip shot are also fixed to their length so they join without a gap."""
        chain = [f"[{index}:v]"]
        if clip.source_s is not None:
            chain.append(f"trim=duration={clip.source_s},setpts=PTS-STARTPTS,")
        chain.append(
            f"setpts=PTS/{clip.speed},fps={job.fps},"
            # Cover the frame, then crop to it: a no-op when the clip already has its size.
            f"scale={job.width}:{job.height}:force_original_aspect_ratio=increase:"
            f"flags=lanczos,crop={job.width}:{job.height},setsar=1"
        )
        if trim:
            chain.append(f",trim=duration={clip.seconds}")
        chain.append(f",setpts=PTS-STARTPTS[{label}]")
        return "".join(chain)

    def _mix(
        self, job: AssemblyJob, total: float, *, music_input: int, fade_out_s: float = 0.0
    ) -> list[str]:
        """Music under narration: the narration drives a sidechain compressor on the music, so the
        music sits at ``music_level`` and drops while someone speaks. With ``fade_out_s`` (an end
        card's length) the mix fades out over its last seconds, up to three."""
        mix = job.mix
        fade = min(fade_out_s, 3.0)
        fade_filter = f",afade=t=out:st={total - fade}:d={fade}" if fade > 0 else ""
        return [
            "[narration]asplit=2[voice][sidechain]",
            f"[{music_input}:a]aresample=48000,aformat=channel_layouts=stereo,apad,"
            f"atrim=duration={total},volume={mix.music_level}[music]",
            f"[music][sidechain]sidechaincompress=threshold={self.DUCK_THRESHOLD}:"
            f"ratio={mix.duck_ratio}:attack={self.ATTACK_MS}:release={self.RELEASE_MS}:"
            "makeup=1[ducked]",
            # amix scales each input by 1/2, so double it back; the limiter only guards clipping
            "[voice][ducked]amix=inputs=2:duration=first:dropout_transition=0,volume=2,"
            f"alimiter=limit=0.95:level=0{fade_filter}[mix]",
        ]
