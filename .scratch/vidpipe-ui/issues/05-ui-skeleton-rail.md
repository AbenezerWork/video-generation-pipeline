# 05: UI skeleton with live stage rail

**What to build:** `vidpipe ui <project>` (optional `ui` extra) serves the Run view: the ten-stage rail with each stage's status, provider and progress ring, updating live over one SSE stream from the run state, for a run started from the CLI. Binds to localhost by default; `--host` opens it to the network and then requires a token printed at startup. On narrow screens the rail becomes a horizontal strip. A polite live region announces only stage start, finish, pause and failure. All interface text is in English.

**Blocked by:** 02, 04

**Status:** ready-for-agent

Spec: `.scratch/vidpipe-ui/spec.md`

- [ ] HTTP API tests on fakes see SSE run-state events for a full CLI run
- [ ] The rail shows all ten stages without scrolling on a laptop screen
- [ ] Requests without the token are refused when bound to the network
- [ ] Only stage start, finish, pause and failure are announced to screen readers
- [ ] The rail is fully operable by keyboard
