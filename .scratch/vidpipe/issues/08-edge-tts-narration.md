# 08: edge-tts narration provider

**What to build:** English and Amharic narration through the TTS contract using edge-tts (am-ET-AmehaNeural, am-ET-MekdesNeural), with real durations feeding the fit planner. MMS-TTS offline fallback is declared in config.

**Blocked by:** 01

**Status:** ready-for-agent

Spec: `.scratch/vidpipe/spec.md`

- [x] Provider passes the TTS conformance suite (integration marker for the real service)
- [x] Narration artifacts expose per-segment durations used by the planner

## Notes

- Duration contract: `TTSResult.duration_s` (provider) -> `NarrationClip.duration_s` in
  `build/narration.json` (one clip per shot and language, `path` relative to `build/`). Seconds,
  float, measured from the written file by a pure-Python MP3 frame walk
  (`providers/_audio.py`), not from service boundary events and not via ffprobe.
- Real voices run longer than the fake TTS: the sample script's first line is 5.66 s in English,
  above the fake i2v 5 s cap, so the ticket 01 planner errors on real narration until ticket 04
  (segmentation, speed change, continuation clips) lands.
- The MMS-TTS offline fallback is declared only: `fallback: [mms-tts]` on the provider selection
  is validated and ignored. No `mms-tts` provider exists.
