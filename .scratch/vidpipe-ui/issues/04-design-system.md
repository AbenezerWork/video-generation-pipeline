# 04: Studio console design system

**What to build:** The visual foundation for the UI, delivered as one static style page served with the package: dark and light theme tokens (light designed as its own console, not an inversion), a remembered theme toggle that defaults to the system setting, the four phase signal hues (words, voice, picture, sound), bundled OFL display and monospace fonts, the stage status treatment (soft glow plus text label plus shape), and motion rules that respect reduced motion. Uses modern-web-guidance. Also adds a Browser Support line to the repo agent instructions: newly available features allowed with feature detection and graceful degradation, no polyfills, no external UI dependencies.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

Spec: `.scratch/vidpipe-ui/spec.md`

- [ ] The style page shows every token, status and phase hue in both themes
- [ ] All text and status colours meet WCAG 2.2 AA contrast in both themes
- [ ] Status is distinguishable without colour
- [ ] Motion stops under reduced-motion settings
- [ ] Fonts are bundled with their licences and load offline
- [ ] The Browser Support line is in the agent instructions
