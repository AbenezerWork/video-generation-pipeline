# 02: Run state published by the runner

**What to build:** During any run, the runner keeps an up-to-date run state in the project build folder, rewritten atomically: run id, origin (CLI or UI), start time, process id, overall status, current stage, per-stage status, per-stage progress (done and total artifact counts), reused versus generated counts, the last error, and the hash of the project config the run started with. It is updated when a stage begins, after each artifact and when a stage ends. The lock refusal message from ticket 01 names who holds the lock and since when, from the run state.

**Blocked by:** 01

**Status:** resolved

Spec: `.scratch/vidpipe-ui/spec.md`

- [x] A CLI run on fakes produces a run state that moves through every stage with correct progress counts
- [x] A paused, failed and finished run each leave the matching overall status
- [x] The run state records the project config hash the run started with
- [x] The lock refusal message names the run origin and start time

## Comments

**Implementation (feat/vidpipe-ui-02).** `vidpipe.runstate` holds the record (`RunState`, schema in the README, "Run state") and the runner's `RunStatePublisher`; `pipeline._run` publishes to `build/run_state.json` (temp file + `os.replace`, retried while a Windows reader holds the file) at run start, stage begin, after each artifact (throttled to 0.25 s) and stage/run end. Each `Stage` now has `artifact_count(ctx)`, worked out from disk; totals of waiting stages are refreshed whenever a stage ends. `StageContext.on_artifact` is the after-artifact hook. Origin comes from `VIDPIPE_RUN_ORIGIN` (`cli`/`ui`, else refused) or `pipeline.run(..., origin=)`. `config_hash(config | project_dir)` hashes the validated config (comments don't count). `read_run_state(project_dir)` reports a record left `running` by a dead process as `failed`. `describe_holder` now returns e.g. `started from the CLI at 2026-11-26 14:03, process 1234` (None when the holder is `approve`). `manifest.json` unchanged. A run refused at plan time leaves a `failed` run state; `tests.conftest.nothing_generated` allows it. Tests: `tests/test_run_state.py` (mid-run state from a real `vidpipe run` held by the fake CLI's `hang`, finished/reused/paused/failed/plan-refused/killed runs, config hash, refusal for CLI and UI origins); `Writer` moved to `tests/background_run.py`.

**For 03 (stop):** check for a stop request in the `ctx.on_artifact` callback set in `pipeline._run_stages` (it runs between artifacts, after each one finishes) and before each stage begins; raise a dedicated exception there and catch it in `pipeline._run` next to the `PlanError`/`Exception` branches, marking the stage in progress and the run `stopped` (add a `stop()` to the publisher like `fail()`; `RunStatus.STOPPING`/`STOPPED` and `StageStatus.STOPPED` already exist). Set `stopping` when the request is seen by the runner (or have the requester write it, but only the runner should write the file).

**For 05 (UI):** read with `read_run_state(project_dir)`, never parse the file by hand; poll it (or watch `build/`) and emit an SSE event when `seq` changes. Pass `VIDPIPE_RUN_ORIGIN=ui` in the environment of the `vidpipe run` processes it starts. Compare `config_hash(project_dir)` with the record's `config_hash` to mark a pending change.
