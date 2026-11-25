# 14: doctor command and setup doc

**What to build:** `vidpipe doctor` checks ComfyUI reachability, ffmpeg and libass, fonts, the text CLIs and required model files, and prints exactly what is missing. The setup doc lists pinned ComfyUI and node versions and required models.

**Blocked by:** 06, 08, 10

**Status:** ready-for-agent

Spec: `.scratch/vidpipe/spec.md`

- [x] Each missing dependency is reported with a specific fix
- [x] All-green output when the environment is complete
- [x] Setup doc lists models, nodes and versions

## Comments

Verified the CLI's failure output and exit status with missing tools, libass, fonts, a text CLI,
ComfyUI, nodes and model files. The default setup passed against live ComfyUI 0.46.3 and the
portable FFmpeg build. The [setup guide](../../../docs/setup.md) lists the selected model files
and node pins, including the video and music selections from tickets 11 and 13.
