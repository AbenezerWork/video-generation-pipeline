# 05: UI skeleton with live stage rail

**What to build:** `vidpipe ui <project>` (optional `ui` extra) serves the Run view: the ten-stage rail with each stage's status, provider and progress ring, updating live over one SSE stream from the run state, for a run started from the CLI. Binds to localhost by default; `--host` opens it to the network and then requires a token printed at startup. On narrow screens the rail becomes a horizontal strip. A polite live region announces only stage start, finish, pause and failure. All interface text is in English.

**Blocked by:** 02, 04

**Status:** resolved

Spec: `.scratch/vidpipe-ui/spec.md`

- [x] HTTP API tests on fakes see SSE run-state events for a full CLI run
- [x] The rail shows all ten stages without scrolling on a laptop screen
- [x] Requests without the token are refused when bound to the network
- [x] Only stage start, finish, pause and failure are announced to screen readers
- [x] The rail is fully operable by keyboard

## Comments

**Implementation (feat/vidpipe-ui-05).** Optional `ui` extra (`starlette`, `uvicorn`; the `dev` group includes `vidpipe[ui]`). `vidpipe ui <project> [--host] [--port 8765]` (`vidpipe.ui.server.serve`) serves `vidpipe.ui.create_app(project_dir, token=, allowed_hosts=, poll_interval=)`. Package layout: `app.py` assembles routes and middleware; one module per area exposes `routes()` (`pages.py`: `/` and `/static`; `api.py`: `GET /api/project`, `GET /api/run`; `events.py`: `GET /api/events`); `summary.py` builds the JSON without Starlette (stages with `label`, `phase`, `provider`, `gate`; `languages`, `gates`, `config_hash`, `pending_change`, `problem`, `run`); `context.py` holds the per-app `UiContext` (`ui_context(request).project_dir`); `access.py` is the token gate. Route conventions are in `app.py`'s docstring: JSON reads `GET /api/<thing>`, actions `POST /api/<thing>/<action>`, media under `/media/...`, one SSE stream with named events (`run` now, `config` later). `pipeline.provider_label` is now public. `read_run_state` now also marks the stage a dead run was in as `failed` (the rail kept it spinning before).

**Access.** Loopback bind (default): no token, `TrustedHostMiddleware` accepts only loopback `Host` names (DNS rebinding). Any other `--host`: `secrets.token_urlsafe(32)`, printed as `http://<LAN address>:<port>/?token=…`; a GET with a valid `?token=` answers 303 to the same URL without it and sets `vidpipe_token` (`HttpOnly`, `SameSite=Lax`, `Path=/`), which the page, assets, `fetch` and `EventSource` carry; `Authorization: Bearer` also works; anything else 401 (JSON under `/api/`). Constant-time comparison.

**Front end.** `static/index.html`, `run.css` (layout only, tokens only), `run.js`. The rail is a `role=tablist` built from `/api/project` with a `<template>`; the selected stage's panel (`#stage-detail`, `role=tabpanel`) shows a summary for now. Native `focusgroup="tablist nomemory"` handles Left/Right/Home/End in Edge 158 but not Up/Down, so run.js handles Up/Down (and everything, as a roving tabindex, where focusgroup is missing). Selection follows the running/paused/failed stage until the user picks one. Under 48rem the rail is a scrolling strip with scroll-driven edge fades (scrollbar hidden only where those are supported). `#announcer` (polite, atomic) gets only "X started/finished/failed" and "X finished. The run is paused at its gate."; fast stages coalesce within one 0.25 s poll, so a quick stage may be announced only as finished. A `stopped` stage uses the `waiting` tone and shape with the label "Stopped" (the design system has no stopped status). Comments in index.html mark where the Run/Config tabs (09), run controls (06) and stage outputs (07/08) go.

**Verified.** `tests/test_ui_run_view.py` (real uvicorn on a free port, stdlib HTTP/SSE client in `tests/ui_server.py`; skipped without the extra): summary before any run; SSE through a full CLI run in a background process (full render with ffmpeg, else `--until music`), with seq order, counts and `/api/run`; a run held in the script stage by the fake CLI and its failure; a killed run read as failed; `vidpipe ui` on loopback (no token, foreign `Host` → 400); `vidpipe ui --host 0.0.0.0` (401 everywhere without the printed token, link → 303 + cookie, cookie works for page, assets, API and SSE, Bearer works). In Edge (Playwright, ad hoc): all ten stages visible at 1366×768 (rail ends at 548 px) with no page scroll; Tab enters the rail on the selected stage, arrows/Home/End move and select, Tab leaves to the panel; announcements over a full run, a gate pause and a killed run were exactly stage start/finish/pause/failure lines; reduced motion leaves only colour transitions; 375 px has no horizontal scroll and the strip scrolls with fades; the token link works in the browser and the stream follows a run; no console errors. Screenshot: `docs/assets/ui-run-view.jpg`.

**For 06.** On Windows `NUL` reports `isatty()` true, so a `vidpipe run` started with stdin and stdout on `DEVNULL` gets the interactive gate prompt and fails on EOF; give the runs the UI starts a pipe for stdin (or make `_interactive_approver` treat EOF as "not approved"). Check `Origin` on the POST actions too; the cookie is `SameSite=Lax`.
