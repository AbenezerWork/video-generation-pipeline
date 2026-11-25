# Experiments and decisions

A running log of what we tried, what happened, and what we decided because of it.
Newest entries go at the bottom of each section. Measurements are from the
development machine unless stated: RTX 4060 Laptop GPU (8 GB VRAM), 31 GB RAM,
Windows 11, ComfyUI Desktop 0.46.3.

Longer write-ups live in [`docs/adr/`](docs/adr/) and in the comments of each
ticket under [`.scratch/vidpipe/issues/`](.scratch/vidpipe/issues/).

## Summary

| Area | Decision | Main reason |
|---|---|---|
| Keyframes | FLUX.2 klein 4B fp8 with reference images | Fast (about 6.5 s per still) and kept the character recognisable |
| Motion | Wan 2.2 TI2V 5B, GGUF Q5_K_M | Fits in 8 GB; usable subtle motion |
| Music | ACE-Step 1.5 Turbo | 90 s of audio in about 23 s, under 6.3 GB VRAM |
| Text | Claude, Codex and Gemini CLIs with fallback | Uses existing subscriptions instead of per-call API billing |
| English voice | Edge TTS | Free, no key, good quality |
| Amharic voice | Edge TTS by default, Addis Voices 2 available | Edge works out of the box; Addis is a dedicated Amharic option |
| Demo resolution | 512x288 at 24 fps | Keeps the 8 GB card stable across a full demo |
| Shot timing | Speed change up to 1.3x first, then a continuation clip | Avoids frozen frames while keeping generation cost down |
| Visuals across languages | One shared set, sized to the longer narration | Halves GPU time versus per-language visuals |

## Planning decisions (25 Nov 2026)

These came out of the design interview, before any code.

- **Local first, ComfyUI as an external service.** Hosted APIs stay possible
  through the same provider contracts. Why: local runs cost nothing per call,
  and keeping ComfyUI outside the pipeline avoids managing its install.
- **Typed contract per stage, workflow JSON plus a mapping file per model.**
  Why: adding a local model should need no new Python.
- **Content-hashed project directory, no database.** Why: skip unchanged work,
  resume after a crash, and re-roll one shot cheaply.
- **Approval gates after script, storyboard and keyframes.** Why: catch problems
  before the expensive stages.
- **Narration before video, with a fit planner in between.** Why: real voice
  lengths decide how much video each shot needs, before any GPU time is spent.
- **Amharic as the second language, with a back-translation check by a different
  model.** Why: no one on the project reads every line, so drift needs flagging.
- **Testing at two seams only:** a full pipeline run on fake providers, and a
  shared conformance suite every provider must pass. Why: the fakes keep tests
  fast without a GPU, and conformance proves providers are swappable.

## Environment trials

- **ffmpeg through winget failed.** The 264 MB full build stalled at 0 MB, then
  crawled at about 7–35 KB/s from GitHub, and finally failed with a network
  timeout at 37 MB.
  **Decision:** use Gyan's 9.1 essentials build (36.7 MB, sha256-checked, has
  libass), pointed to with `VIDPIPE_FFMPEG_DIR`. The ffmpeg bundled with Stremio
  (4.4.1) was used read-only as a stopgap for tests.
- **Hugging Face downloads ran at about 2.3 MB/s**, against roughly 11 KB/s from
  GitHub releases. **Decision:** a background downloader queue (segmented,
  resumable, sha256-verified) fetched all models from Hugging Face while code
  was written in parallel.
- **The Python on PATH was the Microsoft Store stub**, not a real install.
  Python 3.12 and uv were installed with winget.

## Keyframes ([ADR 0001](docs/adr/0001-keyframe-model.md))

- **Trial:** FLUX.2 klein 4B fp8 with `ReferenceLatent` conditioning, over 60
  jobs, no out-of-memory errors or hangs.

  | Size | No reference | 1 reference (0.5 MP) | 1 reference (1.0 MP) |
  |---|---:|---:|---:|
  | 640x352 | 4.1 s | 5.7 s | 7.8 s |
  | 832x480 | 4.5 s | 6.5 s | 8.7 s |
  | 1024x576 | 5.2 s | 7.4 s | 9.8 s |
  | 1280x720 | 6.6 s | 9.2 s | 11.7 s |

  Peak VRAM was 7.0–7.5 GB. The 8 GB text encoder swapping in for each new prompt
  dominates the time.
- **Consistency:** with a reference image, the character stayed recognisable
  across about 18 shots. Described only in words, she came out as a visibly
  different girl. Defects seen: one shot drew two girls, and two drifted to the
  wrong setting (a modern rooftop, a European market) when the prompt lacked
  highland cues.
- **Decision:** FLUX.2 klein with references, 4 steps, references scaled to
  0.5 MP. Why: fast, stable on 8 GB, and the reference is what keeps the
  character consistent. Prompts need setting cues, and the keyframe gate plus
  `redo shot N` handle the occasional bad shot.
- **Not tested:** Flux Kontext GGUF and SDXL with IP-Adapter, which were the
  fallbacks.

## Motion (ticket 11 and 12)

- **Trial:** Wan 2.2 TI2V 5B Q5_K_M at 640x352, 24 fps.

  | Motion | Clip | ComfyUI time |
  |---|---:|---:|
  | Pan | 5.00 s | 185.65 s |
  | Ambient | 3.25 s | 119.97 s |
  | Push-in | 2.75 s | 101.95 s |

- **Finding:** the first pan also pushed in strongly. A tighter prompt with the
  same keyframe and seed gave subtle sideways motion at a steady subject size.
  **Decision:** keep the motion vocabulary to push-in, pan and ambient, with
  prompt wording tuned per motion type.
- **Continuation clips:** a 4.25 s opening clip plus a 3.00 s continuation
  started from its last frame covered 6.96 s of narration. The frames either
  side of the join differed by a mean of 4.12 grey levels out of 255, so the
  join is close to seamless.
  **Decision:** keep continuation clips as the fallback when a speed change of up
  to 1.3x isn't enough.
- **Out-of-memory fallback:** one recorded step-down from 640x352 to 512x288
  with a new seed, verified only against the fake ComfyUI server. Real GPU
  memory exhaustion has not happened yet.

## Music (ticket 13)

- **Trial:** ACE-Step 1.5 Turbo through ComfyUI. 90 s of stereo 48 kHz audio
  rendered in 22.78 s, peaking at 6,231 MiB of VRAM. An 11 s score for the
  sample project took 6.75 s.
- **Decision:** ACE-Step for instrumental music. Why: fast and fits comfortably
  in 8 GB. The song contract (lyrics and vocals) exists with a stub provider only.

## Text and translation

- **Claude CLI passed the real text conformance suite.** Gemini was never logged
  in, so its adapter has only been tested against a fake executable.
- **The demo uses Claude Code and Codex**, with Codex as the fallback when Claude
  is rate limited. Translation uses Codex `gpt-6.2-astra` and the back-check uses
  `gpt-6.2-sol`. Why: two distinct models are required for a meaningful back-check.
- **The back-check caught real wording problems.** It flagged lines 3 and 4 of
  the Amharic draft, which were corrected by hand before narration was generated.
- **Provider swap:** changing only the storyboard model in YAML
  (`gpt-6.2-sol` to `gpt-6.2-astra`, and later `codex-cli` to `claude-cli`)
  regenerated only the storyboard. Every other stage was skipped.

## Narration

- **Edge TTS** produced valid English and Amharic audio (`am-ET-AmehaNeural`,
  `am-ET-MekdesNeural`). Durations are read from the MP3 in pure Python, so no
  ffprobe is needed.
- **Real narration was longer than one clip.** The sample's first English line
  was 5.66 s against a 5 s clip cap, which drove the speed-then-continuation
  design of the fit planner.
- **Addis Voices 2** was added as an Amharic voice option (`addis-ai`, voice
  `am-hamen`, key from `ADDIS_API_KEY`), with English still going to Edge TTS.
  The architecture audit found that because one adapter covers both languages,
  `doctor` checked only Edge and missed a missing Addis key. A per-language voice
  setting is the proposed fix.

## Full demo run: The Coffee Highlands (ticket 15)

- **Result:** both renders assembled, 41.58 s in English and 49.63 s in Amharic,
  from 10 FLUX.2 keyframes, 11 Wan clips (including a continuation) and one
  ACE-Step score, at 512x288. Both decoded cleanly, and a sampled Amharic frame
  showed real Ethiopic subtitles.
- **Resume:** an interrupted Edge TTS run kept all six finished clips. An
  unchanged full rerun skipped every stage and kept both MP4 hashes.
- **Redo:** `redo shot 2` changed only that shot's keyframe and video plus the two
  assemblies.

## Visual style

- **Finding:** the bible's style description goes into every storyboard and
  keyframe prompt. When it described coffee brewing, unrelated keyframes gained
  inset brewing images.
- **Decision:** keep only the look (lighting, lens, treatment) in the bible's
  style, and describe actions in each shot. A full-frame style description
  cleared the insets. Why: anything in the style text leaks into every shot.
  Stills are reviewed at the keyframe gate before animation, since that's the
  cheapest point to catch a bad shot.

## Open questions

- Real GPU out-of-memory recovery for keyframes, video and music is untested.
- 832x480 video output is untested on 8 GB.
- Gemini and Codex tool-disabling flags are unverified against the real CLIs
  (Codex has since run real storyboard and translation jobs).
- The FLUX.2 VAE repack carries a non-commercial licence tag. Check it before
  any commercial use.
