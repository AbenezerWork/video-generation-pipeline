# 12: Browser smoke test

**What to build:** One Playwright test under its own opt-in marker, outside the default suite: open the UI on a fake project, start a run, watch the rail update, open a stage, approve a gate and save a config change.

**Blocked by:** 08, 10

**Status:** resolved

Spec: `.scratch/vidpipe-ui/spec.md`

- [x] The test passes locally under its marker
- [x] The default test suite does not require Playwright

## Answer

`tests/test_ui_browser_smoke.py` has one test under the existing `browser` marker. The default
`addopts` deselects that marker, and the module skips at import when Playwright is absent. It runs
`UiServer` on `make_project(gates=["script"])` against the live SSE stream in headless Chromium
159. The test starts a run through Storyboard and watches Script go from Waiting to Paused. It
opens the Script detail and approves the gate, then waits until Storyboard is Done, Script is
Reused and the run shows Finished. Finally it changes Output name in Config. It waits for the
finished "Estimated GPU time is …" estimate and an Assembly line before it clicks Save. Then it
checks that `vidpipe.yaml` now has `output_name: smoke`. A run through Storyboard leaves Assembly
as "may regenerate", so the test accepts "will" or "may".

Evidence: `uv run --locked --with playwright pytest -m browser` passed all 7 browser tests. The
default suite, run with Playwright absent from the locked environment, gave 341 passed, 2 skipped,
24 deselected. Ruff check, ruff format and pyright were all clean. Portable FFmpeg 9.1 was used,
with no GPU runs.
