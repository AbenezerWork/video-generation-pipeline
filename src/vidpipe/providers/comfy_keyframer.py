"""``comfyui-keyframer``: reference-conditioned keyframes on ComfyUI.

The default workflow is FLUX.2 [klein] 4B fp8 (``docs/adr/0001-keyframe-model.md``): up to two
reference images, which the prompt calls "image 1" and "image 2", each scaled to
``reference_megapixels`` (0.5) inside the workflow. Sizes are multiples of 16::

    width: 832
    height: 480
    providers:
      keyframes: comfyui-keyframer
      # or: {name: comfyui-keyframer, options: {settings: {reference_megapixels: 0.25}}}
"""

from __future__ import annotations

from vidpipe.comfy.provider import ComfyProvider
from vidpipe.comfy.workflow import WorkflowModel
from vidpipe.contracts import (
    GenerationError,
    KeyframerCapabilities,
    KeyframeRequest,
    KeyframeResult,
    KeyframerProvider,
    UnsupportedRequest,
)
from vidpipe.providers._media import png_size
from vidpipe.registry import register


@register
class ComfyKeyframer(ComfyProvider[KeyframerCapabilities], KeyframerProvider):
    name = "comfyui-keyframer"
    default_workflow = "keyframe_flux2_klein_4b"
    required_fields = ("prompt", "seed", "width", "height")

    def declare_capabilities(self, model: WorkflowModel) -> KeyframerCapabilities:
        return KeyframerCapabilities.model_validate(
            {**model.spec.capabilities, "max_reference_images": model.max_images}
        )

    def generate(self, request: KeyframeRequest) -> KeyframeResult:
        caps = self.capabilities
        if problems := caps.size_problems(request.width, request.height):
            raise UnsupportedRequest("; ".join(problems))
        # Stripped: trailing spaces would change the image (and so what a re-roll or cache means).
        prompt = request.prompt.strip()
        outcome = self.run_workflow(
            {"prompt": prompt, "width": request.width, "height": request.height},
            seed=request.seed,
            images=request.reference_images,
            extras=request.extras,
        )
        path = self.save_output(outcome, request.output_path)
        try:
            width, height = png_size(path)
        except ValueError as exc:
            raise GenerationError(f"ComfyUI did not return a PNG image: {exc}") from exc
        return KeyframeResult(
            path=path,
            width=width,
            height=height,
            record=self.record(outcome, images=len(request.reference_images)),
        )
