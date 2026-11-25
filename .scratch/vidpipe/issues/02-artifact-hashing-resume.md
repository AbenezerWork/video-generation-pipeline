# 02: Content-hashed artifacts, skip-unchanged and resume

**What to build:** Artifacts are content-addressed and each stage's inputs are hashed. Re-running skips unchanged stages, and an interrupted run resumes. Each artifact records provider, parameters, seed and timing.

**Blocked by:** 01

**Status:** ready-for-agent

Spec: `.scratch/vidpipe/spec.md`

- [ ] A second run with no changes executes no stages
- [ ] Editing one script line reruns only affected downstream stages
- [ ] A run killed mid-way resumes without redoing completed shots
- [ ] Artifact records contain provider, seed and GPU time
