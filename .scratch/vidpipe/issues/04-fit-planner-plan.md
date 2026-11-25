# 04: Fit planner, natural segmentation, plan and dry-run

**What to build:** From narration durations, narration is split at natural boundaries (sentence, then clause, then pause) into 3-5 s segments. Per shot the plan tries a speed change up to 1.3x, then adds a continuation clip. `visuals: shared|per_language|primary_only` is supported (default shared, sized to the longer narration). `plan` reports clip counts and estimated GPU time without generating anything.

**Blocked by:** 02

**Status:** ready-for-agent

Spec: `.scratch/vidpipe/spec.md`

- [ ] With fake durations, plan output lists segments, speed factors and continuation clips per shot
- [ ] No segment cuts mid-phrase when a natural boundary fits the range
- [ ] Both language renders fit within 90 s under shared visuals
- [ ] Dry-run makes no provider generation calls
