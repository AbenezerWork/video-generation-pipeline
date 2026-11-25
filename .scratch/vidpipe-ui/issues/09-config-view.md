# 09: Config view with provider readiness

**What to build:** A Config tab, connected to the Run view by a view transition, showing the project config as a form generated from its schema. Each stage's provider dropdown lists only providers implementing that stage's contract, each with its doctor readiness (ready, missing key, model not found, CLI not logged in) and the suggested fix. Choosing a provider shows only that provider's options. Fallback chains for text stages are editable in the form. A read-only YAML view shows the result. No saving yet.

**Blocked by:** 05

**Status:** resolved

Spec: `.scratch/vidpipe-ui/spec.md`

- [x] Provider choices per stage are filtered by contract
- [x] Each provider carries readiness and a fix from the doctor checks
- [x] Every project config setting is reachable in the form
- [x] The form validates as you type using the same schema as the CLI
- [x] The YAML view matches what would be saved

## Comments

The Config tab uses the CLI schema and the provider registry. It shows the selected provider's
options, the doctor's readiness and fixes, and editable fallback chains for script, storyboard,
and translation. The doctor's CLI checks cover executable discovery. The read-only YAML preview
keeps comments and key order and checks the draft without writing it. Saving belongs to ticket 10.

After merging integration tip `8f305df`, all 68 Config, design system, Run, and stage detail tests
passed with portable FFmpeg 9.1. Edge smoke covered keyboard navigation with and without native
focus groups, reduced motion, provider switches, readiness fixes, fallback reordering, form edits,
validation focus, YAML preview on desktop and mobile, and the unchanged project file.
