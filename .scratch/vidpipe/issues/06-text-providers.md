# 06: Text providers, script and storyboard stages

**What to build:** Gemini, Claude and Codex CLI adapters (agent tools disabled, empty temp directory, JSON extraction, Pydantic validation, up to 2 re-prompts), a configurable fallback chain, and real script and storyboard stages with a motion-type vocabulary limited to push-in, pan and ambient.

**Blocked by:** 01

**Status:** ready-for-agent

Spec: `.scratch/vidpipe/spec.md`

- [x] A fake CLI executable emitting canned and malformed output exercises extraction and retry
- [x] The fallback chain moves to the next provider on failure or rate limit
- [x] Storyboard shots each carry a motion_type from the allowed vocabulary
- [x] Adapters pass the text conformance suite (fake executables in CI; real Claude CLI verified under `integration`; Gemini and Codex real runs pending login)
