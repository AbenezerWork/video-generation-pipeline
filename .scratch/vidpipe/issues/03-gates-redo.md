# 03: Gates, --auto and per-shot re-roll

**What to build:** The run pauses for approval after script, storyboard and keyframes (configurable), `--auto` skips the gates, and `vidpipe redo shot N` regenerates one shot and its dependents only.

**Blocked by:** 02

**Status:** ready-for-agent

Spec: `.scratch/vidpipe/spec.md`

- [ ] Gates pause and resume on approval; the gate set is configurable
- [ ] `--auto` runs end to end without pausing
- [ ] Redo of one shot leaves other shots' artifacts unchanged
