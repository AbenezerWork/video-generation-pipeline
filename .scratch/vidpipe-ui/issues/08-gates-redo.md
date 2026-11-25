# 08: Gates and redo in the UI

**What to build:** When a run pauses at a gate, the UI shows that stage's outputs with Approve and Reject. Approving continues the run; rejecting leaves it paused and shows next steps (edit config, redo a shot, edit files). Redo shot N is available for keyframes and video. A gate pause triggers a single pulse.

**Blocked by:** 06, 07

**Status:** ready-for-agent

Spec: `.scratch/vidpipe-ui/spec.md`

- [ ] Approving a gate through the API resumes the run past it
- [ ] Rejecting leaves the run paused with the gate unapproved
- [ ] Redo shot N through the API changes only that shot's artifacts and the assemblies
- [ ] The pulse respects reduced motion
