# 09: Spike: keyframe workflow on the 8 GB GPU

**What to build:** Determine which reference-conditioned keyframe model and workflow (quantized Flux Kontext, SDXL IP-Adapter or similar) runs reliably on the RTX 4060 Laptop 8 GB, and record the decision with timings and VRAM use. Needs the user's ComfyUI running.

**Blocked by:** None (needs ComfyUI installed)

**Status:** resolved

Spec: `.scratch/vidpipe/spec.md`

- [x] Decision record states chosen model, workflow, resolution, time per keyframe and VRAM
- [x] Workflow JSON saved for ticket 10
- [x] Notes on character consistency across at least 3 shots

Decision: FLUX.2 [klein] 4B fp8 with reference images, see `docs/adr/0001-keyframe-model.md`; workflow files and field mapping in `workflows/`.
