# 10: ComfyUI provider and keyframe stage with the bible

**What to build:** A ComfyUI provider (workflow JSON plus field mapping, async submit/poll/fetch, 2 retries with new seeds) and the keyframe stage, with the project bible of characters, locations and style references fed into every keyframe.

**Blocked by:** 02, 09

**Status:** ready-for-agent

Spec: `.scratch/vidpipe/spec.md`

- [x] Keyframes generated for every storyboard shot using bible references
- [x] Retries with new seeds are recorded in the artifact
- [x] Provider passes the keyframer conformance suite under the integration marker
