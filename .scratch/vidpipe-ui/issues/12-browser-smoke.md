# 12: Browser smoke test

**What to build:** One Playwright test under its own opt-in marker, outside the default suite: open the UI on a fake project, start a run, watch the rail update, open a stage, approve a gate and save a config change.

**Blocked by:** 08, 10

**Status:** ready-for-agent

Spec: `.scratch/vidpipe-ui/spec.md`

- [ ] The test passes locally under its marker
- [ ] The default test suite does not require Playwright
