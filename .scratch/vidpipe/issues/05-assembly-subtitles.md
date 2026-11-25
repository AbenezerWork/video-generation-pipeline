# 05: Assembly: ducking, burned-in subtitles and two renders

**What to build:** Assembly mixes narration and music with ducking, burns in subtitles (Noto Sans Ethiopic for Amharic, libass), writes sidecar SRTs, and produces demo_en.mp4 and demo_am.mp4.

**Blocked by:** 01, 04

**Status:** ready-for-agent

Spec: `.scratch/vidpipe/spec.md`

- [x] ffprobe shows expected duration, video and audio tracks for each render
- [x] Music level drops under narration
- [x] SRT files match narration timing; Amharic glyphs render in the burned-in subtitles
