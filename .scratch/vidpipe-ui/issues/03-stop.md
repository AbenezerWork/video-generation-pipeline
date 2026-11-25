# 03: Stop and Stop now

**What to build:** A stop request makes the run end with status `stopped` once the artifact in progress finishes, so no finished work is lost. Stop now additionally cancels the current ComfyUI job and discards that one artifact. Resuming is an ordinary run that reuses all finished work. For now both are requested through CLI commands.

**Blocked by:** 02

**Status:** ready-for-agent

Spec: `.scratch/vidpipe-ui/spec.md`

- [ ] A stop during a multi-artifact stage ends after the current artifact, with status `stopped` in the run state
- [ ] Stop now cancels the ComfyUI job (verified against the fake ComfyUI server) and the run ends
- [ ] A resumed run reuses every artifact finished before the stop
