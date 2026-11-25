# 11: Image-to-video stage

**What to build:** Keyframes are animated into 2-5 s clips by a small image-to-video model through ComfyUI, one model resident at a time and shots sequential.

**Blocked by:** 04, 10

**Status:** ready-for-agent

Spec: `.scratch/vidpipe/spec.md`

- [x] Each shot gets a clip matching its planned duration and motion type
- [x] Provider passes the video conformance suite under the integration marker
- [x] GPU time is recorded per clip

## Comments

Verified with Wan 2.2 TI2V 5B Q5_K_M on the RTX 4060 Laptop GPU with 8 GB VRAM
and shared ComfyUI 0.46.3. Once the shared queue verified the model files,
both runs checked that ComfyUI was idle and held the shared Windows GPU lock.
The real conformance test passed with a 2.00 s clip. The real pipeline test
generated three clips with FLUX.2 keyframes and reused all three on rerun.
Portable ffprobe measured each clip at 640x352, 24 fps, and its planned duration.

| Motion | Clip duration | ComfyUI execution |
|---|---:|---:|
| Pan | 5.00 s | 185.65 s |
| Ambient | 3.25 s | 119.97 s |
| Push-in | 2.75 s | 101.95 s |

The first pan also pushed in substantially. After tightening its prompt, a
separate 5.00 s rerender with the same keyframe and seed showed subtle lateral
motion at nearly constant subject size. It took 187.77 s.

The resolution step-down and resume after a failed shot were verified against
the fake ComfyUI server. Real VRAM exhaustion and 832x480 output were untested.
Continuation clips are covered by ticket 12.
