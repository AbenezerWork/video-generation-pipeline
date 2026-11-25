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
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, Field

from vidpipe.subtitles import subtitles_filter


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


class MixSettings(BaseModel):
    #: Music gain while nobody speaks.
    music_level: float = 0.4
    #: Ratio of the sidechain compressor that pushes the music down under narration.
    duck_ratio: float = 8.0


class LanguageRender(BaseModel):
    language: str
    output: Path
    segments: list[ShotSegment]
    music: Path | None = None
    subtitles: SubtitleTrack | None = None


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


def find_tool(name: str) -> str | None:
    return shutil.which(name)


@functools.cache
def ffmpeg_filters(ffmpeg: str) -> frozenset[str]:
    """Names of the filters this ffmpeg was built with (empty if it cannot be asked)."""
    try:
        listing = subprocess.run(
            [ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True, check=False
        ).stdout
    except OSError:
        return frozenset()
    return frozenset(parts[1] for line in listing.splitlines() if len(parts := line.split()) > 2)


#: Filters assembly needs beyond the basics, and why.
REQUIRED_FILTERS = {
    "subtitles": "burned-in subtitles need ffmpeg built with libass",
    "sidechaincompress": "ducking the music under narration needs it",
}


class FfmpegAssembler(Assembler):
    #: Sidechain compressor settings besides the ratio: narration above this (linear, full scale
    #: 1.0) ducks the music; it comes back over ``RELEASE_MS`` once the voice stops.
    DUCK_THRESHOLD = 0.03
    ATTACK_MS = 20
    RELEASE_MS = 400

    def problems(self) -> list[str]:
        found = [
            f"{tool} not found on PATH (needed for assembly)"
            for tool in ("ffmpeg", "ffprobe")
            if find_tool(tool) is None
        ]
        ffmpeg = find_tool("ffmpeg")
        if ffmpeg is not None:
            available = ffmpeg_filters(ffmpeg)
            found += [
                f"ffmpeg has no {name!r} filter: {why}"
                for name, why in REQUIRED_FILTERS.items()
                if name not in available
            ]
        return found

    def assemble(self, job: AssemblyJob) -> list[Path]:
        ffmpeg = find_tool("ffmpeg")
        if ffmpeg is None:
            raise AssemblyError("ffmpeg not found on PATH")
        written: list[Path] = []
        for render in job.renders:
            render.output.parent.mkdir(parents=True, exist_ok=True)
            command = [ffmpeg, "-y", "-v", "error", *self.arguments(job, render)]
            result = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8", errors="replace"
            )
            if result.returncode != 0:
                raise AssemblyError(f"ffmpeg failed for {render.language}: {result.stderr.strip()}")
            written.append(render.output)
        return written

    def arguments(self, job: AssemblyJob, render: LanguageRender) -> list[str]:
        """ffmpeg arguments (after the binary) rendering one language."""
        clips = [clip for segment in render.segments for clip in segment.clips]
        args: list[str] = []
        for clip in clips:
            args += ["-i", str(clip.video)]
        for segment in render.segments:
            args += ["-i", str(segment.narration)]
        total = sum(s.seconds for s in render.segments)

        parts: list[str] = []
        pairs: list[str] = []
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
            parts.append(
                f"[{len(clips) + i}:a]aresample=48000,aformat=channel_layouts=stereo,apad,"
                f"atrim=duration={seg.seconds},asetpts=PTS-STARTPTS[a{i}]"
            )
            pairs.append(f"[v{i}][a{i}]")
        n = len(render.segments)
        burn = render.subtitles is not None and render.subtitles.burn_in
        video_label = "joined" if burn else "vout"
        parts.append(f"{''.join(pairs)}concat=n={n}:v=1:a=1[{video_label}][narration]")
        if render.subtitles is not None and burn:
            track = render.subtitles
            filter_ = subtitles_filter(
                track.srt, fonts_dir=track.fonts_dir, font=track.font, font_size=track.font_size
            )
            parts.append(f"[joined]{filter_}[vout]")

        audio_label = "narration"
        if render.music is not None:
            args += ["-i", str(render.music)]
            parts += self._mix(job, total, music_input=len(clips) + n)
            audio_label = "mix"

        args += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-map", f"[{audio_label}]"]
        args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", f"{total}"]
        args += ["-movflags", "+faststart", str(render.output)]
        return args

    @staticmethod
    def _clip_chain(job: AssemblyJob, clip: ClipPlay, index: int, label: str, *, trim: bool) -> str:
        """One clip: cut to the part used, played at its planned speed, in the render's format.
        Clips of a multi-clip shot are also fixed to their length so they join without a gap."""
        chain = [f"[{index}:v]"]
        if clip.source_s is not None:
            chain.append(f"trim=duration={clip.source_s},setpts=PTS-STARTPTS,")
        chain.append(
            f"setpts=PTS/{clip.speed},fps={job.fps},scale={job.width}:{job.height},setsar=1"
        )
        if trim:
            chain.append(
                f",tpad=stop_mode=clone:stop_duration={clip.seconds},trim=duration={clip.seconds}"
            )
        chain.append(f",setpts=PTS-STARTPTS[{label}]")
        return "".join(chain)

    def _mix(self, job: AssemblyJob, total: float, *, music_input: int) -> list[str]:
        """Music under narration: the narration drives a sidechain compressor on the music, so the
        music sits at ``music_level`` and drops while someone speaks."""
        mix = job.mix
        return [
            "[narration]asplit=2[voice][sidechain]",
            f"[{music_input}:a]aresample=48000,aformat=channel_layouts=stereo,apad,"
            f"atrim=duration={total},volume={mix.music_level}[music]",
            f"[music][sidechain]sidechaincompress=threshold={self.DUCK_THRESHOLD}:"
            f"ratio={mix.duck_ratio}:attack={self.ATTACK_MS}:release={self.RELEASE_MS}:"
            "makeup=1[ducked]",
            # amix scales each input by 1/2, so double it back; the limiter only guards clipping
            "[voice][ducked]amix=inputs=2:duration=first:dropout_transition=0,volume=2,"
            "alimiter=limit=0.95:level=0[mix]",
        ]
