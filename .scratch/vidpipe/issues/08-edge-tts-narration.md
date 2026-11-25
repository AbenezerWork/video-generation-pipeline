# 08: edge-tts narration provider

**What to build:** English and Amharic narration through the TTS contract using edge-tts (am-ET-AmehaNeural, am-ET-MekdesNeural), with real durations feeding the fit planner. MMS-TTS offline fallback is declared in config.

**Blocked by:** 01

**Status:** ready-for-agent

Spec: `.scratch/vidpipe/spec.md`

- [ ] Provider passes the TTS conformance suite (integration marker for the real service)
- [ ] Narration artifacts expose per-segment durations used by the planner
