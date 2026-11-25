# 02: Run state published by the runner

**What to build:** During any run, the runner keeps an up-to-date run state in the project build folder, rewritten atomically: run id, origin (CLI or UI), start time, process id, overall status, current stage, per-stage status, per-stage progress (done and total artifact counts), reused versus generated counts, the last error, and the hash of the project config the run started with. It is updated when a stage begins, after each artifact and when a stage ends. The lock refusal message from ticket 01 names who holds the lock and since when, from the run state.

**Blocked by:** 01

**Status:** ready-for-agent

Spec: `.scratch/vidpipe-ui/spec.md`

- [ ] A CLI run on fakes produces a run state that moves through every stage with correct progress counts
- [ ] A paused, failed and finished run each leave the matching overall status
- [ ] The run state records the project config hash the run started with
- [ ] The lock refusal message names the run origin and start time
