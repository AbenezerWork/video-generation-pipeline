# 11: Image-to-video stage

**What to build:** Keyframes are animated into 2-5 s clips by a small image-to-video model through ComfyUI, one model resident at a time and shots sequential.

**Blocked by:** 04, 10

**Status:** ready-for-agent

Spec: `.scratch/vidpipe/spec.md`

- [ ] Each shot gets a clip matching its planned duration and motion type
- [ ] Provider passes the video conformance suite under the integration marker
- [ ] GPU time is recorded per clip
