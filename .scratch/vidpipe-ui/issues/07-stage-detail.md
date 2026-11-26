# 07: Stage detail

**What to build:** Selecting a stage opens its detail: keyframe thumbnails, playable clips and narration, the translation review with each Amharic line, its English source, back-translation and drift flag (Amharic in the system font), and timing and GPU time. Logs, ledger details, the ComfyUI queue and GPU stats sit behind a disclosure.

**Blocked by:** 05

**Status:** resolved

Spec: `.scratch/vidpipe-ui/spec.md`

- [x] Each stage with outputs serves them through the API after a fake run
- [x] Media files are served with correct types and play in the browser
- [x] The translation review shows drift flags next to the affected lines
- [x] Logs, ledger, queue and GPU stats are hidden until opened

## Comments

The stage-detail HTTP tests cover all ten stages after a fake run with FFmpeg 9.1, including media types, byte-range seeking, timing, drift flags and diagnostics. Headless Edge verified keyframe decoding and playback of narration, an MP4 shot clip and the assembled render. The shot clip was encoded from the fake provider's raw Y4M output for the playback check. The UI also offered the original Y4M files as downloads.

The browser checks covered the translation review at 320, 390, 860 and 1280 pixels, including the Amharic system font, visible labels in the stacked layout and a drift flag on the affected line. Opening the disclosure with the keyboard fetched the ledger, run log, ComfyUI queue and reported GPU memory from a fake ComfyUI server.
