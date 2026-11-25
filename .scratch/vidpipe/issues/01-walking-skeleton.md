# 01: Walking skeleton on fakes

**What to build:** `vidpipe run` on a project directory (brief.md plus YAML config) walks the whole stage graph using a fake provider for every contract, chosen from a registry by config, and renders a real video with ffmpeg. Includes the project/config models, typed provider contracts with capability declarations, and the conformance-suite harness (seam 2) that fakes pass.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

Spec: `.scratch/vidpipe/spec.md`

- [ ] Running the CLI on a sample project produces a playable video, verified with ffprobe
- [x] Every contract has a fake provider that passes its shared conformance suite
- [x] Swapping a provider in YAML changes which provider runs, with no code change
- [x] Plan-time capability check rejects an unsupported request before generation
