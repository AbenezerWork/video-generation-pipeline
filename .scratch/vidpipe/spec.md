Status: ready-for-agent

# vidpipe: a provider-pluggable studio pipeline for short video

## Problem Statement

I want to make short stylized videos (up to 90 s) that need every studio stage: script, translation, storyboard, narration, keyframes, moving shots, music and song. Today each stage is a separate tool or model with its own interface, so swapping a model, re-running one shot, or producing a second language means redoing work by hand. My hardware is a laptop with an 8 GB GPU, so local models are tightly constrained, and I want to use free or subscription CLIs (Gemini, Claude, Codex) for text instead of paying per API call. I need one tool that runs the whole chain, lets me pick a different model for any stage through configuration, and survives failures without regenerating everything.

## Solution

`vidpipe` is a Python library with a CLI on top. A project is a directory holding a `brief.md`, a YAML config and the generated artifacts. `vidpipe run` walks the stage graph: script, translation, storyboard, narration, fit-planning, keyframes, video, music, assembly. Each stage talks to a typed provider contract, and the config chooses which provider implements each stage. ComfyUI runs as an external service for images, video and music. Text uses Gemini/Claude/Codex CLIs, and narration uses `edge-tts`. Every artifact is content-hashed so unchanged stages are skipped, interrupted runs resume, and single shots can be re-rolled. `vidpipe plan` shows what would run, with estimated GPU time (and money for hosted providers), before anything is generated. The first deliverable is the pipeline plus a demo of up to 90 s, rendered in English and Amharic.

## User Stories

1. As a creator, I want to write a short `brief.md` and run one command, so that I get a finished video without driving each tool by hand.
2. As a creator, I want to see a plan before anything is generated, so that I know the shots, clip counts and estimated GPU time up front.
3. As a creator, I want a dry-run mode that makes no paid or GPU calls, so that I can check a project safely.
4. As a creator, I want unchanged stages to be skipped on re-run, so that editing one line of the script doesn't regenerate everything.
5. As a creator, I want an interrupted run to resume where it stopped, so that a crash or an out-of-memory error doesn't cost completed work.
6. As a creator, I want to re-roll a single shot (`vidpipe redo shot 7`), so that I can fix one bad clip cheaply.
7. As a creator, I want the pipeline to pause for my approval after script, storyboard and keyframes, so that I can catch problems before expensive stages.
8. As a creator, I want an `--auto` flag that skips the gates, so that I can run unattended.
9. As a creator, I want to choose a provider for each stage in YAML, so that I can swap models without touching code.
10. As a creator, I want a `doctor` command that checks ComfyUI, ffmpeg, fonts, CLIs and required model files, so that I'm told exactly what is missing.
11. As a creator, I want the script written from my brief, so that I start from a structured draft.
12. As a creator, I want the script translated into Amharic, so that I can publish in a second language.
13. As a creator, I want a back-translation check on translations, so that meaning drift is flagged for review.
14. As a creator, I want a storyboard of shots with visual description and motion type, so that every shot is planned before generation.
15. As a creator, I want shot motion limited to what the video model handles (push-in, pan, ambient), so that clips look intentional rather than broken.
16. As a creator, I want narration generated in each language, so that the video is voiced.
17. As a creator, I want narration split at natural boundaries (sentence, then clause, then pause) within the 3-5 s shot range, so that the delivery sounds natural.
18. As a creator, I want a fit planner that uses real narration durations, so that clip counts are decided before video generation.
19. As a creator, I want speed adjustment of up to 1.3x tried first when narration and clip length differ, so that most shots need no extra generation.
20. As a creator, I want an extra continuation clip, started from the previous clip's last frame, when speed adjustment isn't enough, so that narration fits without frozen frames.
21. As a creator, I want a project bible of characters, locations and style with reference images, so that visuals stay consistent across shots.
22. As a creator, I want keyframes generated with the character reference as input, so that the character is recognizable in every shot.
23. As a creator, I want an optional style LoRA, so that the look stays consistent.
24. As a creator, I want keyframes animated by an image-to-video model, so that shots have subtle motion.
25. As a creator, I want instrumental music generated for the video, so that it has a soundtrack.
26. As a creator, I want a song stage contract with lyrics and vocals, so that songs can be plugged in later.
27. As a creator, I want music to duck under narration in the final mix, so that the voice stays clear.
28. As a creator, I want burned-in subtitles in each language, including Amharic in a Ge'ez font, so that the videos are readable.
29. As a creator, I want sidecar `.srt` files, so that I can reuse subtitles elsewhere.
30. As a creator, I want separate `demo_en.mp4` and `demo_am.mp4` renders, so that each language is a finished video.
31. As a creator, I want a `visuals` setting (`shared`, `per_language`, `primary_only`) defaulting to `shared`, so that I choose between GPU cost and per-language timing.
32. As a creator, I want shared visuals sized to the longer narration per shot, so that both languages fit one set of clips.
33. As a creator, I want ComfyUI jobs retried twice with new seeds, so that transient failures don't stop the run.
34. As a creator, I want a recorded lower-resolution fallback after an out-of-memory error, so that the run continues and I can see what changed.
35. As a creator, I want a cost ledger recording GPU time per artifact, so that I can see where time went.
36. As a creator, I want an optional spend cap that applies to hosted providers, so that a hosted-model run can't overspend.
37. As a creator, I want text providers tried in a configurable fallback chain, so that a rate limit on one doesn't stop the run.
38. As a creator, I want CLI text providers to return validated structured output with retries, so that malformed output doesn't break stages.
39. As a creator, I want CLI text providers run with agent tools disabled in an empty directory, so that they never touch my files.
40. As a creator, I want hosted-API adapters addable later through the same contracts, so that I can use stronger models for hero shots.
41. As a creator, I want a provider capability declaration checked at plan time, so that an unsupported feature fails before any generation.
42. As a creator, I want ComfyUI workflows plugged in as workflow JSON plus a small field mapping, so that adding a local model needs no new Python.
43. As a creator, I want one model resident in GPU memory at a time and shots generated sequentially, so that everything fits in 8 GB.
44. As a developer, I want a fake provider for every contract returning small deterministic assets, so that pipeline logic runs in seconds without a GPU.
45. As a developer, I want one shared conformance suite per contract that every provider runs, so that "swap a provider via config" is verifiable.
46. As a developer, I want real-provider tests behind an opt-in `integration` marker, so that CI stays fast.
47. As a creator, I want a demo of up to 90 s covering narration, music, keyframes, moving shots and two languages, so that the pipeline is proven end to end.

## Implementation Decisions

- **Shape:** a Python 3.12+ library with a CLI on top, working name `vidpipe`. Personal tool: no auth, no multi-tenancy, no database.
- **Tooling:** `uv`, `pytest`, `ruff`, `pyright`, src layout. Pydantic models for every stage input and output.
- **Project directory:** holds `brief.md`, the YAML config, the bible, and generated artifacts. Artifacts are content-addressed, and each stage's inputs are hashed, which drives skip-unchanged, resume and per-shot re-roll. Each artifact records provider, parameters, seed, GPU time and any fallback applied.
- **Stage graph:** brief, script, translation, storyboard, narration, fit-planning, keyframes, video, music (parallel to the visual stages), assembly. Narration runs before video so durations are known.
- **Provider contracts:** one typed contract per stage (text, translation, TTS, keyframer, image-to-video, music, song). Each provider declares capabilities and accepts a request model with an `extras` dict for provider-specific options. Providers register through a registry or entry points and are chosen per stage in YAML. The plan step validates capabilities before generation.
- **Text providers:** a `complete(prompt, schema)` contract returning validated JSON. Adapters: Gemini CLI, Claude CLI, Codex CLI (subprocess, agent tools disabled, empty temp directory, JSON extraction, Pydantic validation, up to 2 re-prompts with the error), Ollama for offline English, and API-key adapters later. A per-stage fallback chain is configurable. Defaults: script, storyboard and translation start with Gemini CLI and fall back to Claude CLI. Back-translation of Amharic is checked by a different model from the translator. Users should check each vendor's current terms for automated CLI use.
- **Narration:** `edge-tts` is the default for English and Amharic (`am-ET-AmehaNeural`, `am-ET-MekdesNeural`). MMS-TTS is the offline fallback and Azure Speech the official upgrade. TTS is a plain Python provider, not a ComfyUI workflow.
- **ComfyUI provider:** ComfyUI is an external service reached by URL (default `localhost:8188`). Each workflow is a JSON file plus a mapping of request fields to node inputs and outputs. Jobs are asynchronous (submit, poll, fetch). The ComfyUI version and custom nodes used are pinned in the project docs.
- **Keyframes and consistency:** reference-conditioned keyframes (a reference-input image model that fits in 8 GB, such as a quantized Flux Kontext or an SDXL IP-Adapter, chosen by a spike test on the target GPU before the contract is final), plus an optional style LoRA. The bible stores reference image paths and a text description for providers that cannot take images.
- **Video:** image-to-video from keyframes, using a small model suited to 8 GB (2-5 s, 480p-class). The storyboard assigns each shot a `motion_type` from a vocabulary limited to what the model does well; prompts avoid complex action.
- **Music and song:** instrumental music through ACE-Step in ComfyUI if it fits in 8 GB, otherwise a hosted provider. Song is a contract only, with one provider, outside the demo's critical path.
- **Fit planning:** the storyboard and fit planner segment narration at natural boundaries (sentence, then clause, then pause) so each segment fits a 3-5 s clip. Per shot, the plan tries a speed change of up to 1.3x first, then adds a continuation clip generated from the previous clip's last frame with a continuation prompt. Visuals use `visuals: shared | per_language | primary_only`, default `shared`, sized to the longer narration per shot. Both renders stay within 90 s.
- **Assembly:** ffmpeg concatenates clips, mixes narration and music with ducking, and burns in subtitles. Amharic subtitles use Noto Sans Ethiopic and require libass. Outputs are `demo_en.mp4`, `demo_am.mp4` and sidecar SRTs. OTIO export comes later.
- **Gates:** configurable pauses default to after script, storyboard and keyframes. `--auto` skips them.
- **Cost and time:** providers declare a cost model (GPU minutes locally, dollars for hosted). `plan` shows the estimate. A spend cap applies to hosted providers only and is off by default.
- **Failure handling:** ComfyUI jobs retry twice with new seeds. On out-of-memory, one recorded step-down (lower resolution or fewer frames, from a per-workflow fallback list). After that the stage fails and the run stops, keeping completed shots for `resume`. No other silent quality changes.
- **Resource model:** one model resident at a time, shots sequential.
- **Environment:** the pipeline does not install or manage ComfyUI. `doctor` checks ComfyUI reachability, ffmpeg, libass, fonts, the text CLIs and required model files, and says exactly what is missing. A setup doc lists the models and nodes. Target machine: an 8 GB GPU laptop with 31 GB RAM.
- **Demo:** a roughly 60-90 s stylized short about an Ethiopian highland coffee-origin story as a placeholder, with narration and instrumental music, in English and Amharic. The concept lives in `brief.md` and is swappable.

## Testing Decisions

- A good test checks external behavior only: the artifacts produced, what `plan` reports, and what the final render contains. It never asserts on internal functions, prompts or call order.
- **Seam 1, the pipeline run:** tests drive the CLI or library entry point (`run`, `plan`, `resume`, `redo`) on a project directory with every provider replaced by a fake (tiny deterministic images, a sine-wave audio file, a short test clip, a canned text provider). Assertions cover artifacts and their hashes, resume and skip-unchanged, gate behavior, the plan's clip counts and cost estimate, retry and out-of-memory fallback records, and the final render's duration, audio tracks and subtitles (inspected with ffprobe). This seam also covers stage ordering, the fit planner, segmentation and assembly, so these get no separate unit tests.
- **Seam 2, provider conformance:** one shared test suite per stage contract, run against every provider. Fakes run in CI. Real ComfyUI, CLI and `edge-tts` providers run the same suite under the opt-in `integration` marker. This makes "swap a provider via config alone" checkable.
- Prior art: none, because the repo is empty. These two seams are the project's testing conventions.
- Subprocess-based text providers are tested with a fake executable on the path that emits canned and malformed output, covering JSON extraction and retry.

## Out of Scope

- A web UI, a node-graph editor, and approval through any interface other than the CLI.
- Multi-user support, authentication and a database.
- OTIO or editor-timeline export (later).
- Real vocals and lyrics generation in the demo (the song contract exists, but the demo uses instrumental music).
- Lip-sync and on-screen talking characters.
- Installing or managing ComfyUI, models or custom nodes.
- Hosted video or image adapters beyond what the contracts allow (added later on request).
- Photorealistic output and quality parity with hosted models.
- More than two languages in the demo.

## Further Notes

- **Proposed ticket order (for `/to-tickets`):**
  1. Fakes-first vertical slice: project directory, config, hashing, resume and re-roll, `plan` with dry-run, gates, fit planner, ffmpeg assembly, and a fake provider for every contract with the conformance suite.
  2. Text providers (Gemini, Claude and Codex CLI adapters, fallback chain, validation and retry) with script, translation (including the back-translation check) and storyboard.
  3. TTS provider (`edge-tts`) with natural segmentation.
  4. Spike test: reference-conditioned keyframe workflow on the 8 GB GPU, deciding the keyframe model. Then the ComfyUI provider and the keyframe stage with the bible.
  5. ComfyUI image-to-video stage with continuation clips.
  6. Music stage (ACE-Step), then the song contract stub.
  7. `doctor`, setup doc and the demo run in both languages.
- ComfyUI is installing through its desktop client now, so tickets 1-3 need no ComfyUI.
- The spec does not use a glossary yet. Terms to define when `GLOSSARY.md` is started: bible, shot, fit plan, continuation clip, provider, contract, gate.
