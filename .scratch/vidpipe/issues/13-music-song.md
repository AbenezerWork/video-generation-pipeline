# 13: Music stage and song contract stub

**What to build:** Instrumental music via ACE-Step in ComfyUI (hosted fallback if it does not fit in 8 GB) and a song contract with lyrics and vocals backed by one stub provider, outside the demo's critical path.

**Blocked by:** 10

**Status:** ready-for-agent

Spec: `.scratch/vidpipe/spec.md`

- [x] Music artifact covers the planned video length on real ACE-Step.
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

### Live verification on 25 November 2026

The shared downloader completed the ACE-Step 1.5 Turbo checkpoint at 21:04 Moscow time.
The completed file matched the expected SHA-256, and ComfyUI 0.46.3 listed it in both
`/models/checkpoints` and `CheckpointLoaderSimple`.

All four checks selected by `pytest -m integration -k 'comfyui_music or comfyui-music'`
passed with `VIDPIPE_FFMPEG_DIR` pointing to portable FFmpeg 9.1. The test runner waited
for an idle queue before taking the exclusive Windows GPU handle, checked the queue before
each submission, and released the handle with the queue empty.

- Real-provider contract conformance generated a 2.00 s FLAC in 6.82 s of ComfyUI execution.
- The sample's real music stage generated an 11.00 s stereo 48 kHz FLAC, covering the
  planned English (10.10 s) and Amharic (10.85 s) renders. Its ledger recorded 6.75 s of
  ComfyUI execution and one successful attempt. The sample used fake providers for the
  upstream stages. ComfyUI prompt `081251d4-abd3-4363-8230-7e486d19d027`.
- The 90.00 s FLAC rendered in 22.78 s of ComfyUI execution on an RTX 4060 Laptop GPU
  (8,188 MiB). `nvidia-smi` sampled a peak of 6,231 MiB of device memory in that job.
  The default decode tile size of 512 succeeded on the first attempt. ComfyUI prompt
  `ccaad3ba-3f14-41eb-b465-e39c8915f4bc`.

The default suite also passed with 237 tests. Ruff and Pyright passed.
