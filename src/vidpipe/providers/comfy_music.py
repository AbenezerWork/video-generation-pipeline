"""Instrumental music through a mapped ComfyUI workflow."""

from __future__ import annotations

import math
import wave
from pathlib import Path
from tempfile import TemporaryDirectory

from vidpipe.comfy.provider import ComfyProvider
from vidpipe.comfy.workflow import WorkflowModel
from vidpipe.contracts import (
    GenerationError,
    MusicCapabilities,
    MusicProvider,
    MusicRequest,
    MusicResult,
    UnsupportedRequest,
)
from vidpipe.providers._audio import audio_duration_s
from vidpipe.registry import register


@register
class ComfyMusic(ComfyProvider[MusicCapabilities], MusicProvider):
    name = "comfyui-music"
    default_workflow = "music_ace_step"
    required_fields = ("prompt", "seed", "seconds", "filename_prefix")

    def declare_capabilities(self, model: WorkflowModel) -> MusicCapabilities:
        return MusicCapabilities.model_validate(model.spec.capabilities)

    def compose(self, request: MusicRequest) -> MusicResult:
        model = self.model  # also loads capabilities for a project-relative mapping
        if problem := self.capabilities.duration_problem(request.duration_s):
            raise UnsupportedRequest(problem)
        seconds = request.duration_s
        if model.spec.name == "music_ace_step":
            # ACE-Step rounds to 25 latent frames per second. Round up so fractional requests fit.
            seconds = math.ceil(seconds * 25) / 25
        outcome = self.run_workflow(
            {"prompt": f"instrumental, no vocals, {request.prompt.strip()}", "seconds": seconds},
            seed=request.seed,
            extras=request.extras,
        )

        requested = request.output_path
        requested.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=requested.parent) as directory:
            saved = self.save_output(outcome, Path(directory) / requested.name)
            try:
                duration = audio_duration_s(saved)
            except (ValueError, EOFError, wave.Error) as exc:
                raise GenerationError(f"ComfyUI returned invalid audio: {exc}") from exc
            if duration < request.duration_s:
                raise GenerationError(
                    f"ComfyUI returned {duration:g} s of audio, shorter than the "
                    f"requested {request.duration_s:g} s"
                )
            path = saved.replace(requested.with_suffix(saved.suffix))
        return MusicResult(path=path, duration_s=duration, record=self.record(outcome, images=0))
