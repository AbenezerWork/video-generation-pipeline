"""Animate a keyframe with the bundled Wan 2.2 TI2V 5B workflow.

The request's prompt is the shot's picture and what moves in it, to which this adds one camera
sentence; the negative prompt is the workflow's (Wan's official one) plus the camera moves the
motion type rules out. The positive prompt says only what to show, never what not to: Wan's encoder
does not read "nothing appears" as a prohibition (docs/research/model-strengths.md).
"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from vidpipe.assembly import find_tool, missing_tool_problem
from vidpipe.comfy.provider import ComfyProvider
from vidpipe.comfy.workflow import WorkflowError, WorkflowModel
from vidpipe.contracts import (
    MOTION_DESCRIPTIONS,
    GenerationError,
    ImageToVideoCapabilities,
    ImageToVideoProvider,
    ImageToVideoRequest,
    ImageToVideoResult,
    MotionType,
    UnsupportedRequest,
)
from vidpipe.registry import register

FPS = 24

#: Added to the workflow's negative prompt: the camera moves each motion type must not make.
MOTION_NEGATIVES: dict[MotionType, str] = {
    MotionType.PAN: "zoom in, zoom out, dolly in, push in",
    MotionType.PUSH_IN: "pan, sideways camera movement, fast zoom",
    MotionType.AMBIENT: "camera movement, zoom, pan, camera shake",
}


def motion_prompt(scene: str, motion_type: MotionType) -> str:
    """The image-to-video prompt: ``scene`` (the picture and what moves in it), then one camera
    sentence. Wan's own i2v prompt rewriter keeps only the motion, but the 5B model left without
    the picture described painted bars and blobs into the lower frame in our A/B runs."""
    scene = scene.strip()
    if scene and scene[-1] not in ".!?":
        scene += "."
    return " ".join(p for p in (scene, MOTION_DESCRIPTIONS[motion_type]) if p)


def _video_seconds(ffprobe: str, path: Path) -> float:
    try:
        info = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=duration",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        seconds = float(info.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise GenerationError(f"ffprobe could not read the duration of {path.name}: {exc}") from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise GenerationError(f"invalid video duration {seconds} in {path.name}")
    return seconds


@register
class ComfyImageToVideo(ComfyProvider[ImageToVideoCapabilities], ImageToVideoProvider):
    name = "comfyui-i2v"
    default_workflow = "video_wan22_ti2v_5b"
    required_fields = (
        "prompt",
        "seed",
        "width",
        "height",
        "frames",
        "output_frames",
        "fps",
        "filename_prefix",
    )

    def declare_capabilities(self, model: WorkflowModel) -> ImageToVideoCapabilities:
        if 1 not in model.image_counts:
            raise WorkflowError(f"{model.spec.name} needs a workflow accepting one keyframe")
        caps = ImageToVideoCapabilities.model_validate(model.spec.capabilities)
        for field, limit in (("width", caps.max_width), ("height", caps.max_height)):
            size = model.value(field, self.settings, 1)
            if type(size) is not int or not 32 <= size <= limit or size % 32:
                raise WorkflowError(f"video {field} must be a multiple of 32 within 32-{limit}")
        width, height = (
            model.value("width", self.settings, 1),
            model.value("height", self.settings, 1),
        )
        if caps.max_pixels is not None and int(width) * int(height) > caps.max_pixels:
            raise WorkflowError(
                f"video size {width}x{height} is more than {caps.max_pixels} pixels"
            )
        return caps

    def animate(self, request: ImageToVideoRequest) -> ImageToVideoResult:
        caps = self.capabilities
        if not caps.min_seconds <= request.duration_s <= caps.max_seconds:
            raise UnsupportedRequest(
                f"duration {request.duration_s:g}s is outside {caps.min_seconds:g}-"
                f"{caps.max_seconds:g}s"
            )
        if request.motion_type not in caps.motion_types:
            raise UnsupportedRequest(f"motion type {request.motion_type.value!r}")
        if (ffprobe := find_tool("ffprobe")) is None:
            raise GenerationError(missing_tool_problem("ffprobe"))

        output_frames = math.ceil(request.duration_s * FPS)
        # Wan decodes 4k+1 frames. Trim the surplus at the native playback rate.
        frames = 1 + 4 * math.ceil((output_frames - 1) / 4)
        values = {
            "prompt": motion_prompt(request.prompt, request.motion_type),
            "frames": frames,
            "output_frames": output_frames,
            "fps": FPS,
            "width": self.model.value("width", self.settings, 1),
            "height": self.model.value("height", self.settings, 1),
        }
        negative = self.model.value("negative_prompt", {**self.settings, **request.extras}, 1)
        if isinstance(negative, str):
            values["negative_prompt"] = f"{negative}, {MOTION_NEGATIVES[request.motion_type]}"
        outcome = self.run_workflow(
            values,
            seed=request.seed,
            images=[request.image],
            extras=request.extras,
        )
        dest = request.output_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=dest.parent) as temp:
            path = self.save_output(outcome, Path(temp) / dest.name)
            seconds = _video_seconds(ffprobe, path)
            if not math.isclose(seconds, output_frames / FPS, abs_tol=0.001):
                raise GenerationError(
                    f"ComfyUI saved {seconds:g}s of video, expected {output_frames / FPS:g}s"
                )
            path = path.replace(dest.with_suffix(path.suffix))
        record = self.record(outcome, images=1)
        record.details["motion_type"] = request.motion_type.value
        return ImageToVideoResult(path=path, duration_s=seconds, record=record)
