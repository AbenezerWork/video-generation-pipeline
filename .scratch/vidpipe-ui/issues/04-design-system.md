# 04: Studio console design system

**What to build:** The visual foundation for the UI, delivered as one static style page served with the package: dark and light theme tokens (light designed as its own console, not an inversion), a remembered theme toggle that defaults to the system setting, the four phase signal hues (words, voice, picture, sound), bundled OFL display and monospace fonts, the stage status treatment (soft glow plus text label plus shape), and motion rules that respect reduced motion. Uses modern-web-guidance. Also adds a Browser Support line to the repo agent instructions: newly available features allowed with feature detection and graceful degradation, no polyfills, no external UI dependencies.

**Blocked by:** None (can start immediately)

**Status:** resolved

Spec: `.scratch/vidpipe-ui/spec.md`

- [x] The style page shows every token, status and phase hue in both themes
- [x] All text and status colours meet WCAG 2.2 AA contrast in both themes
- [x] Status is distinguishable without colour
- [x] Motion stops under reduced-motion settings
- [x] Fonts are bundled with their licences and load offline
- [x] The Browser Support line is in the agent instructions

## Comments

**Implementation (feat/vidpipe-ui-04).** Assets live in `src/vidpipe/ui/static/` and ship in the wheel through the existing `packages = ["src/vidpipe"]` hatch config: `tokens.css` (all tokens and `@font-face`), `console.css` (base elements and components), `theme.js` (toggle), `console.js` (ring, dialog and toast behaviours), `style.html` (every token and component, stamped into a dark and a daylight sheet side by side), and `fonts/` (Mona Sans 2.027 variable, JetBrains Mono 2.304 Regular and SemiBold, OFL texts, README with sources and hashes). Screenshots: `docs/assets/ui-style-page.jpg`, `docs/assets/ui-style-components.jpg`.

**Token names for later tickets.** Use only the semantic tokens: surfaces `--color-bg`, `--color-surface`, `--color-raised`, `--color-inset`, `--color-selected`; lines `--color-line` (decorative) and `--color-line-strong` (component boundary); text `--color-text`, `--color-text-muted`, `--color-text-faint`; `--color-accent`, `--color-on-accent`, `--color-focus`; `--color-status-{waiting,running,done,reused,paused,failed}` and `--color-on-failed`; `--color-phase-{words,voice,picture,sound}`; `--color-shadow`, `--shadow-raised`, `--glow-radius`; fonts `--font-display`, `--font-ui`, `--font-mono`, `--font-content-am`; `--text-{2xs,xs,sm,md,lg,xl,2xl,3xl}`, `--weight-{regular,medium,strong,display}`, `--stretch-{display,label,dense}`, `--leading-*`, `--tracking-*`; `--space-0..8`; `--radius-{1,2,3,round}`, `--control-height`, `--focus-width`, `--focus-offset`; `--duration-{instant,quick,base,slow,pulse,spin}`, `--ease-{out,in,in-out,signal}`. Markup hooks: `data-status="…"` sets `--tone`, `data-phase="…"` sets `--phase`; components `.status` + `.status-mark`, `.phase-stripe`, `.phase-label`, `.ring` + `progress.ring-progress` + `.ring-content`, `.btn` (`-primary`, `-danger`, `-quiet`, `-icon`), `.field` + `.input`/`.select`/`.textarea` (`.field-hint`, `.field-error`), `dialog.dialog`, `.toast-region` + `showToast()` from `console.js`, `.label`, `.numeral`, `.panel`, `.well`, `.theme-toggle[data-theme-toggle]`. Set `data-changed` on a re-rendered status to play the landing animation; a gate pause pulses once on its own.

**Verified.** `tests/test_ui_design_system.py`: WCAG 2.2 AA (4.5:1) for every text, accent, status and phase colour on all five backgrounds in both themes, 3:1 for boundaries and focus, every `animation` in `console.css` only under `prefers-reduced-motion: no-preference`, fonts are local woff2 with OFL texts, and a built wheel contains every static file. In Edge (Playwright, ad hoc): fonts load from the package, reduced motion leaves zero running animations, the toggle persists across reload and clears when it matches the system, it still switches with storage blocked, dialog opens with focus on "Keep running" and returns focus on Esc, toasts stack and move focus on close, 375px width has no horizontal scroll, and forced colours keep every status shape and label.
