# 01: One-writer lock

**What to build:** `run`, `redo` and `approve` hold a cross-platform OS file lock for the project for their whole duration. A second writer fails fast with a clear message instead of overwriting work. A lock left by a killed or crashed process clears itself because the OS releases it. The demo GPU wrapper uses the same mechanism instead of its Windows-only file handle. Projects on network drives are documented as unsupported.

**Blocked by:** None (can start immediately)

**Status:** done (branch feat/vidpipe-ui-01)

Spec: `.scratch/vidpipe-ui/spec.md`

- [x] A second CLI run on a project with a run in progress exits non-zero with a message saying a run is in progress
- [x] A run whose process was killed leaves no lock that blocks the next run
- [x] `redo` and `approve` are refused while a run holds the lock
- [x] The demo GPU wrapper uses the same lock and works on Windows
- [x] Docs state that projects on network drives are unsupported

## Comments

**Implementation (feat/vidpipe-ui-01).** `vidpipe.lock.writer_lock(root)` holds a `filelock` OS lock on `build/run.lock` (no soft fallback, file preserved) around `pipeline.run`, `redo` (from before the re-roll) and `approve`; a second writer gets `RunInProgress` (a `ProjectError`, so the CLI prints `error: <project>: a run is in progress on this project. ...` and exits 1). Tests: `tests/test_one_writer.py`, with a real `vidpipe run` in another process held mid-script by the fake CLI's new `hang` reply.

GPU wrapper: `run-gpu.ps1` now calls `examples/coffee-origin/run_gpu.py`, which waits for the machine-wide GPU lock through `filelock` and for an idle ComfyUI queue, then runs vidpipe in process (so the project lock applies too). Verified on Windows against the fake ComfyUI server with the sample project: runs, waits while the GPU lock is held by `filelock`, and also waits while it is held by the old exclusive .NET handle.

**Seam for 02:** `vidpipe.lock.describe_holder(build) -> str | None` returns `None` today; make it read the run state and return e.g. `"started from the CLI at 2026-11-26 14:03"`. `RunInProgress(root, holder)` puts it in the message as `a run is in progress on this project (<holder>)`, and exposes `.holder` for the UI. A side effect to know: a run refused at plan time now leaves `build/run.lock`; tests use `tests.conftest.nothing_generated(project)` for "nothing was written".
