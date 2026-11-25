# 01: One-writer lock

**What to build:** `run`, `redo` and `approve` hold a cross-platform OS file lock for the project for their whole duration. A second writer fails fast with a clear message instead of overwriting work. A lock left by a killed or crashed process clears itself because the OS releases it. The demo GPU wrapper uses the same mechanism instead of its Windows-only file handle. Projects on network drives are documented as unsupported.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

Spec: `.scratch/vidpipe-ui/spec.md`

- [ ] A second CLI run on a project with a run in progress exits non-zero with a message saying a run is in progress
- [ ] A run whose process was killed leaves no lock that blocks the next run
- [ ] `redo` and `approve` are refused while a run holds the lock
- [ ] The demo GPU wrapper uses the same lock and works on Windows
- [ ] Docs state that projects on network drives are unsupported
