# 10: Config save, change cost and pending changes

**What to build:** Saving the project config through the form, keeping comments and key order. Before saving, a summary shows which stages regenerate, how many artifacts and the estimated GPU time, matching `vidpipe plan`. A save made while a run is in progress becomes a pending change: the run keeps the config it started with (ADR 0002), the UI marks the change as pending and offers stop and restart.

**Blocked by:** 02, 09

**Status:** ready-for-agent

Spec: `.scratch/vidpipe-ui/spec.md`

- [ ] Saving keeps YAML comments and key order
- [ ] Invalid configs cannot be saved
- [ ] The change-cost summary matches `vidpipe plan` for the edited config
- [ ] A save during a run is marked pending and the run keeps its original config hash
- [ ] Stop and restart applies the pending change and reuses finished work
