# 13: Music stage and song contract stub

**What to build:** Instrumental music via ACE-Step in ComfyUI (hosted fallback if it does not fit in 8 GB) and a song contract with lyrics and vocals backed by one stub provider, outside the demo's critical path.

**Blocked by:** 10

**Status:** ready-for-agent

Spec: `.scratch/vidpipe/spec.md`

- [ ] Music artifact covers the planned video length on real ACE-Step. The fake ComfyUI run wrote
  an 11-second FLAC that covered both language renders and was used in both assembled MP4s.
- [x] Song contract and stub pass the conformance suite
- [x] Music provider is swappable via config

## Comments

The bundled ACE-Step 1.5 Turbo graph matches the running ComfyUI 0.46.3 node schemas. CPU tests
with portable ffmpeg/ffprobe covered FLAC duration, provider switching, cached reruns, the
duration limit in `plan`, and a simulated OOM retry that keeps the duration.

Real ACE-Step contract conformance and the sample-length and 90-second GPU runs were skipped.
The checkpoint was still queued behind the Wan text encoder and was absent from ComfyUI's
checkpoint list. The existing download queue was used and the GPU lock was left available to
ticket 11. The 8 GB fit, generated audio and GPU timing remain unverified. The README documents
how to select a hosted ComfyUI endpoint manually if local execution needs more memory.

Once the shared checkpoint is verified and visible in ComfyUI, run
`uv run pytest -m integration -k 'comfyui_music or comfyui-music'` with portable ffmpeg on
`PATH`. For the shared Windows setup, hold an exclusive Windows file handle on
`C:/Users/abene/.t3/vidpipe-deps/integration-gpu.lock` during the GPU tests and release it in a
`finally` block. Check that the ComfyUI queue is idle before submitting.
