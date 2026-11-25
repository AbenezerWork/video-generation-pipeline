# 14: doctor command and setup doc

**What to build:** `vidpipe doctor` checks ComfyUI reachability, ffmpeg and libass, fonts, the text CLIs and required model files, and prints exactly what is missing. The setup doc lists pinned ComfyUI and node versions and required models.

**Blocked by:** 06, 08, 10

**Status:** ready-for-agent

Spec: `.scratch/vidpipe/spec.md`

- [ ] Each missing dependency is reported with a specific fix
- [ ] All-green output when the environment is complete
- [ ] Setup doc lists models, nodes and versions
