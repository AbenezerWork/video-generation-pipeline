Status: ready-for-agent

# vidpipe UI: a studio console for monitoring and configuring a project

## Problem Statement

Runs take up to an hour, and today the only window into a run in progress is the terminal that started it. I can't see which stage is running or how far through it is, because the runner only records a stage once it finishes. Changing which provider a stage uses means hand-editing YAML, with no way to see whether a provider is actually ready or what a change will cost to regenerate. Reviewing a gate means opening files in a file browser. Two runs on the same project can also silently overwrite each other's work, and nothing stops a second run from starting.

## Solution

`vidpipe ui <project>` starts a local web app for one project. It shows the ten stages as a rail with each stage's status, provider and live progress. Selecting a stage opens its outputs (keyframes, clips, narration, translation review) and timing. From the same screen I can start, stop and resume a run, redo a shot, and approve or reject at a gate with the outputs in front of me. A separate view edits the project config through a form, shows each provider's readiness, and shows what a change will regenerate before I save it. Runs started from the CLI show up the same way, because the runner now publishes its run state. A per-project lock ensures only one run writes to a project at a time.

The look is a dark-first "studio console": instrument-like, uncluttered, with generated media as the most colorful thing on screen.

## User Stories

### Opening and access

1. As a creator, I want to open the UI with `vidpipe ui <project>`, so that I can watch and control a project without the terminal.
2. As a creator, I want the UI bound to my own machine by default, so that nobody else on my network can reach it.
3. As a creator, I want an explicit option to open the UI to my network, so that I can watch a long run from my phone.
4. As a creator, I want a token required whenever the UI is reachable from the network, so that only I can control my runs.
5. As a creator, I want the UI to work without an internet connection, so that it behaves the same offline.
6. As a creator, I want the UI installed as an optional extra, so that the core pipeline stays lightweight.

### Monitoring a run

7. As a creator, I want to see all ten stages at once without scrolling, so that I know where the run is at a glance.
8. As a creator, I want each stage to show its status (waiting, running, done, reused, paused at a gate, failed), so that I know what has happened.
9. As a creator, I want each stage to show which provider it uses, so that I know which tool did the work.
10. As a creator, I want a running stage to show live progress such as "video 4/11 clips", so that I know how far through it is.
11. As a creator, I want an estimate of the time left in the running stage, so that I can plan around it.
12. As a creator, I want stages that reused earlier work shown differently from stages that generated new work, so that I can see what was actually spent.
13. As a creator, I want to open a stage and see its outputs, so that I can judge the results without opening files.
14. As a creator, I want keyframe thumbnails, playable clips and playable narration in a stage's detail, so that I can review media in place.
15. As a creator, I want the translation review shown with each Amharic line, its English source, back-translation and any drift flag, so that I can check the translation.
16. As a creator, I want each stage's timing and GPU time shown, so that I can see where time went.
17. As a creator, I want logs, ledger details, the ComfyUI queue and GPU stats hidden until I ask for them, so that the screen stays uncluttered.
18. As a creator, I want a run started from the CLI to appear in the UI exactly like one started from the UI, so that I have one place to watch.
19. As a creator, I want to close the browser tab without affecting a run, so that I can leave and come back.
20. As a creator, I want reopening the UI to pick up a run in progress, so that I never lose sight of it.
21. As a creator, I want an opt-in browser notification when a run pauses at a gate, fails or finishes, so that I don't have to keep watching.
22. As a creator, I want the UI to explain a failed stage in plain words with the error, so that I know what to fix.

### Controlling a run

23. As a creator, I want to start a run from the UI, so that I don't need the terminal.
24. As a creator, I want to start a run up to a chosen stage, so that I can run only the text stages, for example.
25. As a creator, I want to stop a run after the artifact in progress finishes, so that no finished work is lost.
26. As a creator, I want a "Stop now" option while a stop is waiting, so that I can cancel a long ComfyUI job immediately.
27. As a creator, I want to resume a stopped or failed run, so that it continues from where it ended.
28. As a creator, I want to redo a single shot from the UI, so that I can fix one bad keyframe or clip.
29. As a creator, I want to approve a gate with that stage's outputs in front of me, so that the review and the decision happen in one place.
30. As a creator, I want to reject a gate and see what to do next (edit, redo a shot, change config), so that the run doesn't continue on bad output.
31. As a creator, I want quitting the UI server to ask whether to leave a run going or stop it, so that I don't kill a run by accident.
32. As a creator, I want a run left going after the server quits to keep running, so that long runs survive the UI closing.

### One writer per project

33. As a creator, I want only one run to write to a project at a time, so that two runs can't overwrite each other's work.
34. As a creator, I want a CLI run to refuse with a clear message when a run is already in progress, so that I know why it didn't start.
35. As a creator, I want a lock left by a crashed run to clear itself, so that a crash never blocks the next run.
36. As a creator, I want the demo GPU wrapper to use the same lock, so that there is one locking mechanism on every platform.

### Changing the project config

37. As a creator, I want to edit the project config through a form, so that I don't hand-edit YAML.
38. As a creator, I want the form to validate as I type, so that I can't save an invalid config.
39. As a creator, I want a read-only view of the resulting YAML, so that I can see exactly what will be saved.
40. As a creator, I want saving to keep my comments and key order in the YAML, so that hand edits and UI edits can coexist.
41. As a creator, I want each stage's provider dropdown to list only providers that fit that stage, so that I can't pick something nonsensical.
42. As a creator, I want each provider shown with its readiness (ready, missing key, model not found, CLI not logged in), so that I know whether it will work.
43. As a creator, I want a provider that isn't ready to show the fix the doctor suggests, so that I can make it ready.
44. As a creator, I want choosing a provider to show only that provider's options, so that the form stays short.
45. As a creator, I want to edit fallback chains for text stages, so that I control the order providers are tried.
46. As a creator, I want to edit languages, visuals mode, resolution, gates, subtitles and mix, so that every project setting is reachable.
47. As a creator, I want to see what a change will regenerate and the estimated GPU time before I save, so that I know its cost.
48. As a creator, I want to edit the config during a run, so that I can prepare the next run without waiting.
49. As a creator, I want a change made during a run saved as a pending change that applies to the next run, so that the run in progress stays consistent.
50. As a creator, I want a pending change clearly marked, with an offer to stop and restart, so that I can apply it sooner when I want to.

### Look, feel and accessibility

51. As a creator, I want a dark-first console look, so that generated media and live status stand out.
52. As a creator, I want a light theme designed as its own console, following my system setting and with a remembered toggle, so that I can work in bright rooms.
53. As a creator, I want each phase (words, voice, picture, sound) to have its own signal color, so that I can orient myself on the rail.
54. As a creator, I want motion only where it means something, so that the interface feels alive without being busy.
55. As a creator, I want reduced-motion settings respected, so that motion never bothers me.
56. As a creator, I want the interface entirely in English, so that it reads consistently.
57. As a creator, I want Amharic shown only where it is the content itself, in the system font, so that I can review translations without the interface switching language.
58. As a creator, I want every action reachable by keyboard, so that I can work without a mouse.
59. As a creator, I want status conveyed by text and shape as well as color, so that it reads without color vision.
60. As a creator using a screen reader, I want to hear when a stage starts, finishes, pauses or fails, without hearing every progress tick, so that updates are useful and not noise.
61. As a creator on a phone, I want the stage rail to collapse into a strip, so that the UI works on a small screen.

### Development

62. As a developer, I want the UI tested through its HTTP API on fake providers, so that tests are fast and need no GPU.
63. As a developer, I want a browser policy recorded in the repo instructions, so that every implementer uses the same feature rules.

## Implementation Decisions

- **Packaging:** the UI ships as an optional `ui` extra adding Starlette, uvicorn, ruamel.yaml and filelock. `vidpipe ui <project>` is a new CLI subcommand. The core pipeline gains filelock as a core dependency because the CLI also takes the lock.
- **Server:** a Starlette app served by uvicorn. It binds to localhost by default. `--host` opens it to the network and then requires a random token, printed at startup and sent by the browser on every request. No other authentication.
- **Front end:** no-build vanilla HTML, CSS and JS served as static files from the package, following modern-web-guidance. Bundled OFL fonts: one variable display font and one monospace font, chosen during design. No Ethiopic font is bundled for the UI; Amharic content uses the system font.
- **Browser policy:** newly available web features are allowed with feature detection and graceful degradation; no polyfills and no external UI dependencies. Record this as a **Browser Support** line in the repo's agent instructions.
- **Run state (new, written by the runner):** the runner publishes a run-state record in the project's build folder, rewritten atomically on every change. It holds: run id, origin (CLI or UI), start time, process id, overall status (running, stopping, paused, failed, finished, stopped), the current stage, per-stage status, per-stage progress (done and total counts of artifacts, such as clips), reused versus generated counts, and the last error. The runner updates it when a stage begins, after each artifact, and when a stage ends. Both the UI and the CLI read it. The existing manifest is unchanged.
- **One-writer lock (new):** each project has a lock file in its build folder, held for the whole of `run`, `redo` and `approve` through a cross-platform OS file lock (filelock). The OS releases it when the process dies, so stale locks clear themselves. A second writer fails fast with a message naming who holds the lock and since when, read from the run state. The demo GPU wrapper is changed to use the same mechanism. Projects on network drives are unsupported and documented as such.
- **Runs launched by the UI:** the server starts each run as a separate background process running the normal CLI, so a run survives the browser closing and the server quitting. Quitting the server asks whether to leave a run in progress going or stop it, defaulting to leaving it going.
- **Stop:** a stop request is a signal the runner checks between artifacts, so the artifact in progress finishes and the run ends with status `stopped`. "Stop now" additionally cancels the current ComfyUI job, discarding that one artifact. Resume is an ordinary run, since finished artifacts are reused.
- **Pending changes (ADR 0002):** config edits save immediately. If a run is in progress, the edit is a pending change: the run keeps the config it started with, and the UI marks the change and offers "stop and restart". The run state records the config hash the run started with so the UI can tell.
- **Config editing:** the form is generated from the project config schema. Each stage's provider choices come from the registry, filtered to providers implementing that stage's contract. Each provider's options form comes from its declared options. Readiness comes from the existing doctor checks, per provider. Saving goes through ruamel.yaml to keep comments and key order, and validation uses the same schema as the CLI. A read-only YAML view shows the result.
- **Cost of a change:** before saving, the server computes a plan for the edited config against the current ledger and reports which stages regenerate, how many artifacts, and the estimated GPU time, reusing the existing plan and estimate logic.
- **HTTP API:** JSON endpoints for: project summary; current run state; plan for a proposed config; config read and validate; config save; start run (optional "until" stage); stop; stop now; redo shot; approve and reject gate; stage outputs and media files; provider list with readiness; logs. Live updates come from a single SSE stream that emits run-state changes and config changes. Actions are POSTs.
- **Layout:** two views, Run and Config, switched by tabs and connected by a view transition. Run view: the stage rail on the left, always visible, and the selected stage's detail on the right. Logs, ledger, ComfyUI queue and GPU stats sit behind a disclosure. On narrow screens the rail becomes a horizontal strip.
- **Visual direction ("studio console"):** dark-first; a light theme designed separately; a remembered toggle that defaults to the system setting. Phase signal hues are words, voice, picture and sound. Stage status uses a soft glow plus a text label and a shape. Monospace numerals for timings and counts.
- **Motion:** only meaningful motion: view transition between views, progress ring on the running stage, animated status changes in place, animated dialogs and toasts, one pulse when a gate pauses. Everything respects reduced motion.
- **Notifications:** opt-in browser notifications for pause at gate, failure and finish only.
- **Accessibility:** WCAG 2.2 AA contrast including status glows, full keyboard operation, status not conveyed by color alone, and a polite live region announcing only stage start, finish, pause and failure.
- **Language:** all interface text in English. Amharic appears only as artifact content (translation review, narration lines, subtitle previews).

## Testing Decisions

- A good test checks external behavior only: HTTP responses, SSE events, files written to the project, and the run's outcome. It never asserts on internal functions, template markup or call order.
- **Primary seam, the UI's HTTP API:** tests start the Starlette app in process against a temporary project using fake providers and drive it over HTTP. Assertions cover: run state over SSE through a full run (stage start, progress counts, finish); start up to a stage; graceful stop ends after the artifact in progress; stop now cancels; resume reuses work; redo shot changes only that shot; approve and reject at a gate; config validation errors; save keeps comments and key order; a change during a run becomes pending and the run keeps its config; the change-cost summary matches `vidpipe plan`; provider choices are filtered by contract and carry doctor readiness; the token is required when bound to the network; a second writer is refused.
- **Existing seam, the pipeline run:** CLI tests cover the run-state record during a CLI run, the refusal message when a run holds the lock, and that a lock from a killed process doesn't block the next run.
- **Browser smoke test:** one Playwright test under its own opt-in marker, outside the default suite. It opens the UI, starts a run on fakes, sees the rail update, opens a stage, approves a gate and saves a config change.
- **Prior art:** the existing pipeline tests that drive the CLI against fake providers, the fake ComfyUI server for cancellation, and the fake CLI executables.

## Out of Scope

- Editing the brief or the bible from the UI.
- More than one project per UI session, and a project list or home screen.
- Multi-user access, accounts and roles.
- Applying config changes to a run already in progress.
- A desktop app wrapper.
- Hosting the UI anywhere other than the user's own machine.
- Projects on network drives.
- Translating the interface into other languages.

## Further Notes

- Decisions and terms come from the design session recorded in `GLOSSARY.md` and `docs/adr/0002-config-changes-apply-next-run.md`.
- The run-state record and the one-writer lock also close the audit's "two runs at once can lose work" finding, and they are useful without the UI. They should land first.
- The look should be designed before the components are built, so implementers share one set of tokens, fonts and motion rules.
