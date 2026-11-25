# 07: Translation with back-translation check

**What to build:** Script translation from English to Amharic through the text contract, with a back-translation check by a different model that flags meaning drift for review.

**Blocked by:** 06

**Status:** ready-for-agent

Spec: `.scratch/vidpipe/spec.md`

- [x] Translation stage produces a translated script artifact
- [ ] Drifted back-translation is flagged in the artifact and at the gate (done: flags in `translation/<lang>.review.json`, the ledger and the `vidpipe run` report; pending ticket 03: the gate must show `vidpipe.translate.drift_flags(project)`)
- [x] The checker model differs from the translator when the chain allows it
