# 12: Continuation clips and OOM step-down

**What to build:** When the plan calls for extra coverage, a continuation clip is generated from the previous clip's last frame with a continuation prompt. On out-of-memory, one recorded step-down (lower resolution or fewer frames from a per-workflow fallback list) is applied, then the stage fails with completed shots preserved.

**Blocked by:** 04, 11

**Status:** ready-for-agent

Spec: `.scratch/vidpipe/spec.md`

- [ ] A shot needing extra length gets a continuation clip that joins the first without a frozen frame
- [ ] OOM triggers one recorded step-down and no other silent quality change
- [ ] After a failed stage, resume keeps completed shots
