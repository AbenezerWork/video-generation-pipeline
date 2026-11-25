# 10: Config save, change cost and pending changes

**What to build:** Saving the project config through the form, keeping comments and key order. Before saving, a summary shows which stages regenerate, how many artifacts and the estimated GPU time, matching `vidpipe plan`. A save made while a run is in progress becomes a pending change: the run keeps the config it started with (ADR 0002), the UI marks the change as pending and offers stop and restart.

**Blocked by:** 02, 09

**Status:** resolved

Spec: `.scratch/vidpipe-ui/spec.md`

- [x] Saving keeps YAML comments and key order
- [x] Invalid configs cannot be saved
- [x] The change-cost summary matches `vidpipe plan` for the edited config
- [x] A save during a run is marked pending and the run keeps its original config hash
- [x] Stop and restart applies the pending change and reuses finished work

## Comments

HTTP tests on fake projects verified the YAML preview and saved bytes, comment and key order
preservation, invalid and stale saves, and parity with the CLI regeneration estimate. A blocked
fake CLI run kept its original config hash through the stop. The restarted run used the saved
provider and reused the finished brief. A headless Chromium smoke test exercised the Config tab
through validation, preview, save, pending state and restart using ticket 06's run endpoints.
