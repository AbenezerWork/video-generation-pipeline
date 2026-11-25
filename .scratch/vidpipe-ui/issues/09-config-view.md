# 09: Config view with provider readiness

**What to build:** A Config tab, connected to the Run view by a view transition, showing the project config as a form generated from its schema. Each stage's provider dropdown lists only providers implementing that stage's contract, each with its doctor readiness (ready, missing key, model not found, CLI not logged in) and the suggested fix. Choosing a provider shows only that provider's options. Fallback chains for text stages are editable in the form. A read-only YAML view shows the result. No saving yet.

**Blocked by:** 05

**Status:** ready-for-agent

Spec: `.scratch/vidpipe-ui/spec.md`

- [ ] Provider choices per stage are filtered by contract
- [ ] Each provider carries readiness and a fix from the doctor checks
- [ ] Every project config setting is reachable in the form
- [ ] The form validates as you type using the same schema as the CLI
- [ ] The YAML view matches what would be saved
