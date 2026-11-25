"""Final assembly behind a small interface.

The assembler turns an :class:`AssemblyJob` (per-language lists of timed shot segments plus music)
into rendered files. :class:`FfmpegAssembler` shells out to ffmpeg. Ticket 05 extends the job
(ducking, subtitles) and the ffmpeg graph without changing how the stage calls it.
"""

from __future__ import annotations

import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel


class AssemblyError(Exception):
    pass


class ShotSegment(BaseModel):
    shot_id: int
    video: Path
    narration: Path
    seconds: float


class LanguageRender(BaseModel):
    language: str
    output: Path
    segments: list[ShotSegment]
    music: Path | None = None


class AssemblyJob(BaseModel):
    renders: list[LanguageRender]
    width: int
    height: int
    fps: int


class Assembler(ABC):
    @abstractmethod
    def problems(self) -> list[str]:
        """Reasons assembly cannot run here (checked at plan time); empty when ready."""

    @abstractmethod
    def assemble(self, job: AssemblyJob) -> list[Path]:
        """Render every language in the job; return the written files."""


def find_tool(name: str) -> str | None:
    return shutil.which(name)


class FfmpegAssembler(Assembler):
    MUSIC_LEVEL = 0.25

    def problems(self) -> list[str]:
        return [
            f"{tool} not found on PATH (needed for assembly)"
            for tool in ("ffmpeg", "ffprobe")
            if find_tool(tool) is None
        ]

    def assemble(self, job: AssemblyJob) -> list[Path]:
        ffmpeg = find_tool("ffmpeg")
        if ffmpeg is None:
            raise AssemblyError("ffmpeg not found on PATH")
        written: list[Path] = []
        for render in job.renders:
            render.output.parent.mkdir(parents=True, exist_ok=True)
            command = [ffmpeg, "-y", "-v", "error", *self.arguments(job, render)]
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                raise AssemblyError(f"ffmpeg failed for {render.language}: {result.stderr.strip()}")
            written.append(render.output)
        return written

    def arguments(self, job: AssemblyJob, render: LanguageRender) -> list[str]:
        """ffmpeg arguments (after the binary) rendering one language."""
        args: list[str] = []
        for segment in render.segments:
            args += ["-i", str(segment.video)]
        for segment in render.segments:
            args += ["-i", str(segment.narration)]
        n = len(render.segments)
        total = sum(s.seconds for s in render.segments)

        parts: list[str] = []
        for i, seg in enumerate(render.segments):
            parts.append(
                f"[{i}:v]fps={job.fps},scale={job.width}:{job.height},setsar=1,"
                f"tpad=stop_mode=clone:stop_duration={seg.seconds},trim=duration={seg.seconds},"
                f"setpts=PTS-STARTPTS[v{i}]"
            )
            parts.append(
                f"[{n + i}:a]aresample=48000,aformat=channel_layouts=stereo,apad,"
                f"atrim=duration={seg.seconds},asetpts=PTS-STARTPTS[a{i}]"
            )
        joined = "".join(f"[v{i}][a{i}]" for i in range(n))
        parts.append(f"{joined}concat=n={n}:v=1:a=1[vout][narration]")

        audio_label = "narration"
        if render.music is not None:
            args += ["-i", str(render.music)]
            parts.append(
                f"[{2 * n}:a]aresample=48000,aformat=channel_layouts=stereo,apad,"
                f"atrim=duration={total},volume={self.MUSIC_LEVEL}[music]"
            )
            parts.append("[narration][music]amix=inputs=2:duration=first:dropout_transition=0[mix]")
            audio_label = "mix"

        args += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-map", f"[{audio_label}]"]
        args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", f"{total}"]
        args += ["-movflags", "+faststart", str(render.output)]
        return args
