## Agent skills

### Issue tracker

Issues and specs are local markdown under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `GLOSSARY.md` plus `docs/adr/`. See `docs/agents/domain.md`.

### Browser Support

**Browser Support:** newly available web features are allowed, behind feature detection with graceful degradation; no polyfills and no external UI dependencies (no frameworks, CDN scripts, stylesheets or fonts). The UI front end is no-build vanilla HTML, CSS and JS in `src/vidpipe/ui/static/`; style only with the tokens in `tokens.css` and the components in `console.css`, and look at `style.html` there for every token and component.
