# 08: Gates and redo in the UI

**What to build:** When a run pauses at a gate, the UI shows that stage's outputs with Approve and Reject. Approving continues the run; rejecting leaves it paused and shows next steps (edit config, redo a shot, edit files). Redo shot N is available for keyframes and video. A gate pause triggers a single pulse.

**Blocked by:** 06, 07

**Status:** resolved

Spec: `.scratch/vidpipe-ui/spec.md`

- [x] Approving a gate through the API resumes the run past it
- [x] Rejecting leaves the run paused with the gate unapproved
- [x] Redo shot N through the API changes only that shot's artifacts and the assemblies
- [x] The pulse respects reduced motion

## Comments

Gate decisions target the paused run ID and stage. Approval resumes through the original stage
limit. Rejection clears any approval for that gate, leaves the run paused, and shows next steps.
Redo uses the normal CLI and honors configured gates. Keyframes and Video each show one redo
button per shot, including shots with multiple clips or visual sets.

The HTTP and SSE tests on fake projects verified approval, rejection, stale decision refusal,
and redo through assembly with portable FFmpeg 9.1. Redo of shot 2 paused for fresh keyframe review.
After approval, the changed artifact records were shot 2's keyframe and video and the English and
Amharic assemblies. Headless Chromium exercised review navigation, keyboard gate decisions, and
redo. Each live pause pulsed once with standard motion and zero times with reduced motion.

Ticket 10 can update the rejection guidance from editing `vidpipe.yaml` to saving in Config.
Ticket 11 receives fresh redo pauses through the shared run event. Rejection keeps the same run
state. Ticket 12 owns the opt-in end-to-end smoke test.
