# 03: Stop and Stop now

**What to build:** A stop request makes the run end with status `stopped` once the artifact in progress finishes, so no finished work is lost. Stop now additionally cancels the current ComfyUI job and discards that one artifact. Resuming is an ordinary run that reuses all finished work. For now both are requested through CLI commands.

**Blocked by:** 02

**Status:** resolved

Spec: `.scratch/vidpipe-ui/spec.md`

- [x] A stop during a multi-artifact stage ends after the current artifact, with status `stopped` in the run state
- [x] Stop now cancels the ComfyUI job (verified against the fake ComfyUI server) and the run ends
- [x] A resumed run reuses every artifact finished before the stop

## Comments

**Implementation (feat/vidpipe-ui-03).** `vidpipe.stop`: the requester writes `build/stop_request.json` (`{run_id, now, requested_at}`, atomically, via `runstate.write_atomically`) without the project lock; `request_stop` refuses with `NoRunInProgress` (a `ProjectError`) unless `read_run_state` shows an active run, and keeps `now` once set for that run. In the runner, `pipeline._run` starts a `StopWatcher` (a thread polling every 0.1 s) that marks the run state `stopping` (`RunStatePublisher.stopping()`) on seeing a request for its own `run_id`, and removes the request when the run ends; a stale request from an earlier run is removed at start. `watcher.check()` runs in `ctx.on_artifact` and before each stage and raises `RunStopped`; `_run_stages` catches it (and `contracts.Cancelled` when a stop now was asked) and returns `RunResult(stopped=True)` with the manifest so far; `RunStatePublisher.stop(generated, reused)` marks the stage in progress and the run `stopped`. The publisher now holds a lock around changes and writes, since the watcher thread writes too. Stop now: `ProjectContext.stop_now` (a callable, excluded from serialization) reaches `ComfyProvider` → `run_job` → `ComfyClient.wait`, which raises `Cancelled` (not a `GenerationError`) once it is true; `run_job` takes that job out of ComfyUI's queue / interrupts it and does not retry. Non-ComfyUI providers finish the artifact, as for a stop. CLI: `vidpipe stop <project> [--now]`; a stopped `vidpipe run`/`redo` exits with code 4 (`vidpipe.stop.EXIT_STOPPED`). Docs: README "Stop and stop now", glossary **Stop now**. Tests: `tests/test_stop.py` (graceful stop mid-keyframes against the fake ComfyUI with a new `hold` outcome, resume reuses the finished keyframes, stop now cancels only that job and discards only that keyframe, stop then stop now, a stop reaching a `vidpipe run` in another process holding the lock, refused with no run); the fake CLI's `hang` gained a `then` reply.

**For 06 (UI run controls):** call `vidpipe.stop.request_stop(project_dir)` for Stop and `request_stop(project_dir, now=True)` for Stop now, from the server process; no lock needed. It returns the `StopRequest` (`run_id`, `now`). Map `NoRunInProgress` to a 409. Show "Stop now" while the run state's `status` is `stopping`; the run's own state changes (`stopping`, then `stopped`) arrive through the run state as usual. Resume = start an ordinary run. A run started by the UI that stops exits with code 4, not an error.
