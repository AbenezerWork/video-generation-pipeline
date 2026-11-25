# 15: Demo run in both languages

**What to build:** Render the placeholder coffee-origin story from brief.md as demo_en.mp4 and demo_am.mp4, each up to 90 s, with narration, music, keyframes, moving shots and subtitles.

**Blocked by:** 05, 07, 08, 12, 13, 14

**Status:** ready-for-agent

Spec: `.scratch/vidpipe/spec.md`

- [ ] Both videos are 90 s or shorter and play with all tracks
- [ ] The run is resumable and one shot can be re-rolled
- [ ] Swapping one provider through config works on the real pipeline

## Comments

2026-11-25 Windows integration run. The [Coffee Highlands example](../../../examples/coffee-origin/README.md)
documents the real-provider configuration, portable FFmpeg setup and shared GPU lock.
The live project is `%USERPROFILE%\.t3\vidpipe-demos\coffee-origin`. Keep its
`build/` directory and configuration to resume. The expected outputs are
`out/demo_en.mp4` and `out/demo_am.mp4` in that project.

- [x] Resumed an interrupted Edge TTS run. All six completed English clips kept
  their ledger records and file hashes. The fit plan subsequently used all 20
  narration clips and predicted 41.568 s in English and 49.608 s in Amharic.
- [x] Generated all ten FLUX.2 keyframes. The keyframe and narration files match
  their ledger hashes. The first Wan clip matches its ledger hash and decodes
  as 4.75 s of 512×288 H.264 at 24 fps, with 114 distinct decoded frames. The
  remaining shared clips, including the shot 1 continuation, are running under
  the exclusive GPU handle. See `video-run.log` and `video-run.err` in the live
  project. `video-run.exit` appears when the run finishes.
- [x] Swapped the storyboard model from `gpt-6.2-sol` to `gpt-6.2-astra` via YAML
  in a sibling project. The real Codex CLI regenerated the storyboard, and the
  script, translation and review retained their hashes. A cross-adapter swap
  remains open. Claude was authenticated but rate-limited, and Gemini required
  sign-in.

The separate back-translation model flagged wording in the Amharic draft. Lines
3 and 4 were corrected in the live translation before its narration was generated.
The updated review still records smaller wording differences.

The shared tracker is already downloading the ACE-Step checkpoint. After the
video run exits and `doctor` sees the verified checkpoint, resume the same project
with the full run in the example instructions. Verify both exports, then exercise
the single-shot redo and retry the cross-adapter swap when a second CLI is available.
