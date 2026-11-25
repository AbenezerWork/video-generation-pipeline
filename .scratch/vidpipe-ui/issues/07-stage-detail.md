# 07: Stage detail

**What to build:** Selecting a stage opens its detail: keyframe thumbnails, playable clips and narration, the translation review with each Amharic line, its English source, back-translation and drift flag (Amharic in the system font), and timing and GPU time. Logs, ledger details, the ComfyUI queue and GPU stats sit behind a disclosure.

**Blocked by:** 05

**Status:** ready-for-agent

Spec: `.scratch/vidpipe-ui/spec.md`

- [ ] Each stage with outputs serves them through the API after a fake run
- [ ] Media files are served with correct types and play in the browser
- [ ] The translation review shows drift flags next to the affected lines
- [ ] Logs, ledger, queue and GPU stats are hidden until opened
