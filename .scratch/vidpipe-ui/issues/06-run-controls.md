# 06: Start, stop and resume from the UI

**What to build:** Start a run (optionally up to a chosen stage), stop, Stop now and resume from the Run view. The server starts each run as a separate background process running the normal CLI, so it survives the browser tab closing and the server quitting. Quitting the server asks whether to leave a run in progress going or stop it, defaulting to leaving it going. A run started from the CLI shows the same controls.

**Blocked by:** 03, 05

**Status:** resolved

Spec: `.scratch/vidpipe-ui/spec.md`

- [x] Starting a run from the API produces the same run state as a CLI run
- [x] Start up to a stage stops after that stage
- [x] Stop and Stop now behave as in ticket 03 when triggered from the UI
- [x] Closing the client leaves the run running; reopening picks it up
- [x] Starting a run while one is in progress is refused with the lock message

## Comments

**Implementation.** The Run view can start through a chosen stage, stop, escalate to Stop now,
and resume with the previous stage limit selected. The API starts the normal CLI as a detached
process with closed piped stdin and correlates its run state by run ID, including under a Windows
virtual environment. CLI runs have the same stop controls. Each UI launch gets its own log in
`build/logs/`. The Run log disclosure shows the recent output for the current UI-started run.
Ctrl+C at the UI server prompts to keep the run going or request a graceful stop.

**Verification.** HTTP and SSE tests on Windows cover launch through assembly with portable FFmpeg
9.1, a stage-limited launch, an unattended gate pause, reconnection after client and server exit,
lock refusal for both origins, graceful stop, Stop now, and reuse on resume. Chromium exercised the
Run controls and log disclosure with the keyboard at a narrow viewport. A Windows ConPTY smoke
test exercised both choices at the real Ctrl+C prompt while a fake ComfyUI artifact was in progress.
