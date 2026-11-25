# 06: Start, stop and resume from the UI

**What to build:** Start a run (optionally up to a chosen stage), stop, Stop now and resume from the Run view. The server starts each run as a separate background process running the normal CLI, so it survives the browser tab closing and the server quitting. Quitting the server asks whether to leave a run in progress going or stop it, defaulting to leaving it going. A run started from the CLI shows the same controls.

**Blocked by:** 03, 05

**Status:** ready-for-agent

Spec: `.scratch/vidpipe-ui/spec.md`

- [ ] Starting a run from the API produces the same run state as a CLI run
- [ ] Start up to a stage stops after that stage
- [ ] Stop and Stop now behave as in ticket 03 when triggered from the UI
- [ ] Closing the client leaves the run running; reopening picks it up
- [ ] Starting a run while one is in progress is refused with the lock message
