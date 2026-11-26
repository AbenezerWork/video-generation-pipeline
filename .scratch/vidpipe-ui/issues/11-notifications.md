# 11: Browser notifications

**What to build:** Opt-in browser notifications when a run pauses at a gate, fails or finishes, and for nothing else.

**Blocked by:** 06

**Status:** resolved

Spec: `.scratch/vidpipe-ui/spec.md`

- [x] Notifications are off until the user opts in
- [x] Exactly those three events notify
- [x] The page degrades gracefully when notifications are unsupported or denied

## Comments

The masthead control enables notifications for the current page. It follows the existing run-state
stream and alerts on a gate pause, failure or finish. Loading an old run or reconnecting to the same
run status does not send another alert.

Six Playwright Chromium cases passed with portable FFmpeg and fake providers, covering opt-in,
permission fallbacks and replayed run states. Run the cases with
`uv run --with playwright pytest -m browser tests/test_ui_notifications.py`.
