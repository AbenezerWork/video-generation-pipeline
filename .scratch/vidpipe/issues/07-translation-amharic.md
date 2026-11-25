# 07: Translation with back-translation check

**What to build:** Script translation from English to Amharic through the text contract, with a back-translation check by a different model that flags meaning drift for review.

**Blocked by:** 06

**Status:** ready-for-agent

Spec: `.scratch/vidpipe/spec.md`

- [ ] Translation stage produces a translated script artifact
- [ ] Drifted back-translation is flagged in the artifact and at the gate
- [ ] The checker model differs from the translator when the chain allows it
