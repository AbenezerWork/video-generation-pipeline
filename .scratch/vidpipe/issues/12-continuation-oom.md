# 12: Continuation clips and OOM step-down

**What to build:** When the plan calls for extra coverage, a continuation clip is generated from the previous clip's last frame with a continuation prompt. On out-of-memory, one recorded step-down (lower resolution or fewer frames from a per-workflow fallback list) is applied, then the stage fails with completed shots preserved.

**Blocked by:** 04, 11

**Status:** ready-for-agent

Spec: `.scratch/vidpipe/spec.md`

- [x] A shot needing extra length gets a continuation clip that joins the first without a frozen frame
- [x] OOM triggers one recorded step-down and no other silent quality change
- [x] After a failed stage, resume keeps completed shots

## Comments

The real Wan 2.2 TI2V 5B Q5_K_M integration passed on the RTX 4060 Laptop GPU
with ComfyUI 0.46.3. The run used portable FFmpeg through `VIDPIPE_FFMPEG_DIR`
and held the exclusive Windows GPU lock after confirming ComfyUI was idle.
The queue was empty when the lock was released.

- One shot used a FLUX.2 keyframe, a 4.25 s opening clip and a 3.00 s continuation.
  Both clips were 640x352 at 24 fps and took 162.66 s and 109.12 s of ComfyUI
  execution. The 7.00 s render covered 6.96 s of narration. All 16 decoded
  frames around the join were distinct. The opening clip's last frame and the
  continuation's first frame differed by a mean of 4.12 grayscale levels on
  a 0–255 scale. An unchanged rerun reused both clips.
- The fake ComfyUI test compared the uploaded conditioning PNG with the preceding
  clip's last decoded frame byte for byte. Injected OOMs verified one recorded
  640x352 to 512x288 step-down with a new seed and the original duration, frame
  rate, and sampler settings. A second OOM stopped the stage. Resuming preserved
  the completed shot and the preceding clip. Real GPU OOM was untested.

The default test suite passed with 237 tests. Ruff, Pyright, and `git diff --check`
passed.
