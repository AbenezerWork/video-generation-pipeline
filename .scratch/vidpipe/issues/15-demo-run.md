# 15: Demo run in both languages

**What to build:** Render the placeholder coffee-origin story from brief.md as demo_en.mp4 and demo_am.mp4, each up to 90 s, with narration, music, keyframes, moving shots and subtitles.

**Blocked by:** 05, 07, 08, 12, 13, 14

**Status:** ready-for-agent

Spec: `.scratch/vidpipe/spec.md`

- [x] Both videos are 90 s or shorter and play with all tracks
- [x] The run is resumable and one shot can be re-rolled
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

The resumed run reused all 11 Wan clips, generated the real ACE-Step score, and
assembled both MP4s with matching SRT sidecars. FFprobe measured 41.583 s for
English and 49.625 s for Amharic. Both files contain H.264 and mixed AAC and
decoded in full with FFmpeg's error checks enabled. A sampled Amharic frame
showed burned-in Ethiopic text.

An unchanged full rerun skipped every stage and preserved the ledger and both
MP4 hashes. Redoing shot 2 changed only its keyframe and video ledger records
and the two assembly records. Both rerendered files passed the full decode.
The cross-adapter swap remains to be verified.
