# Experiments and decisions

What we tried, what happened, and what we decided because of it.

Measurements are from the development machine unless stated: RTX 4060 Laptop GPU
(8 GB VRAM), 31 GB RAM, Windows 11, ComfyUI Desktop 0.46.3. "ComfyUI time" and
"GPU seconds" are the execution time ComfyUI reports.

**How to read this file.** The log was first kept as trials and decisions. It was
restructured on 26 November 2026 into numbered entries. The *Hypothesis* lines were
written then, from what each trial set out to check; most were not written down
before the trial ran. Results and decisions are as logged at the time. Where a
number was recomputed from a run's ledger (`build/ledger.json`), the entry says so.
The demo projects and their ledgers live outside the repository, in
`%USERPROFILE%\.t3\vidpipe-demos\`.

Longer write-ups are in [`docs/adr/`](docs/adr/) and in the comments of each ticket
under [`.scratch/vidpipe/issues/`](.scratch/vidpipe/issues/). Blockers and fixes are
in [FAILURES.md](FAILURES.md), timing and cost in [COSTS.md](COSTS.md).

## Summary

| Area | Decision | Main reason | Entries |
|---|---|---|---|
| Keyframes | FLUX.2 klein 4B fp8, references optional | Fast (about 6.5 s per still); references keep a character recognisable, and text alone held up for Khalid | 2, 3, 4, 19 |
| Motion | Wan 2.2 TI2V 5B, GGUF Q5_K_M | Fits in 8 GB; usable subtle motion | 5, 6 |
| Music | ACE-Step 1.5 Turbo | 90 s of audio in about 23 s, under 6.3 GB VRAM | 10 |
| Text | Claude, Codex and Gemini CLIs with fallback | Uses existing subscriptions instead of per-call API billing; Claude took over translation when Codex hit its quota | 11, 12, 19 |
| English voice | Edge TTS | Free, no key, good quality | 13 |
| Amharic voice | Edge TTS by default, Addis Voices 2 for Lion's Whisker | Three viewers found the earlier voice robotic. The Addis take also changes clip timing | 13 |
| Demo resolution | 512x288 at 24 fps, then 640x352 for Khalid | Both stable on the 8 GB card; 640x352 takes about 3 min per 5 s clip | 9 |
| Shot timing | Speed change up to 1.3x first, then a continuation clip | Avoids frozen frames while keeping generation cost down | 7, 8 |
| Visuals across languages | One shared set, sized to the longer narration | Halves GPU time versus per-language visuals | 8 |
| Look | Live-action by default, plus storyboard rules | Photographic footage held up better in motion. Cast descriptions and counts helped with duplicates | 15, 16, 17, 25 |
| Script length | 6 to 18 lines, under 90 s, or the brief's own count | A hard-coded 60 s cap cut the Khalid script short | 18 |
| UI | Local Starlette app with live run state, one-writer lock, English only | See runs as they happen; never let two runs overwrite each other | 24 |
| Disclosure | Optional AI end card in every language | It has to survive re-renders, so it lives in the pipeline | 20 |
| Aspect ratio | `output_size` crop-and-scale; portrait generated fresh, not cropped | Exact 16:9 and 9:16 from multiple-of-32 model sizes; a crop would lose 70% of the frame | 21 |
| Review point | Check every keyframe before animating | A bad still costs about 7 s to redraw; a clip costs about 3 min | 23 |
| Final mix | Two-pass loudness normalisation | The earlier mixes measured -20.6 to -24.4 LUFS | 26 |
| Captions | English subtitles on the Amharic cut | The brief calls for English captions timed to the native-language narration | 27 |

## Entries

### 1. Getting tools and models over a slow network (25 Nov)

- **Hypothesis:** the normal installers are good enough to get ffmpeg and about
  35 GB of model files onto the machine the same day.
- **Change:** installed the full ffmpeg build through winget; pulled models from
  Hugging Face.
- **Result:** winget's 264 MB build stalled at 0 MB, then crawled at about 7 to
  35 KB/s from GitHub, and failed with a network timeout at 37 MB. Hugging Face
  ran at about 2.3 MB/s, against roughly 11 KB/s from GitHub releases.
- **Decision:** use Gyan's 9.1 essentials build (36.7 MB, sha256-checked, has
  libass), pointed to with `VIDPIPE_FFMPEG_DIR`. The ffmpeg bundled with Stremio
  (4.4.1) was used read-only as a stopgap for tests. A background downloader queue
  (segmented, resumable, sha256-verified) fetched all models from Hugging Face
  while code was written in parallel.

### 2. A reference-conditioned keyframe model on 8 GB ([ADR 0001](docs/adr/0001-keyframe-model.md))

- **Hypothesis:** FLUX.2 klein 4B fp8 with `ReferenceLatent` conditioning runs
  reliably in 8 GB and is fast enough to draw every shot of a short.
- **Change:** a spike of about 60 jobs, 4 steps, at four sizes with and without
  reference images.
- **Result:** no out-of-memory errors or hangs.

  | Size | No reference | 1 reference (0.5 MP) | 1 reference (1.0 MP) |
  |---|---:|---:|---:|
  | 640x352 | 4.1 s | 5.7 s | 7.8 s |
  | 832x480 | 4.5 s | 6.5 s | 8.7 s |
  | 1024x576 | 5.2 s | 7.4 s | 9.8 s |
  | 1280x720 | 6.6 s | 9.2 s | 11.7 s |

  Peak VRAM was 7.0 to 7.5 GB. The same seed and inputs gave identical pixels in
  four pairs. Adding trailing spaces to a prompt changed the image. A 640x360
  request was silently produced as 640x352.
- **Decision:** FLUX.2 klein, 4 steps, references scaled to 0.5 MP. Sizes are
  multiples of 16. Prompts are stripped so re-rolls and cache keys stay stable.
  Flux Kontext GGUF and SDXL with IP-Adapter, the fallbacks, were not tested.

### 3. Reference picture versus a description in words

- **Hypothesis:** a character stays recognisable across shots only if the model
  receives a picture, not just a description.
- **Change:** the same character drawn across hand-written shots from a character
  sheet, and the same scene drawn from words alone (same seed, size and style).
- **Result:** with the reference image the character stayed recognisable across
  about 18 shots. Described only in words, she came out as a visibly different
  girl. Defects seen: one shot drew two girls, and two drifted to the wrong setting
  (a modern rooftop, a European market) when the prompt lacked highland cues.
- **Decision:** pass reference pictures when a project has them, and use bible text
  only for providers that cannot take images. Prompts need setting cues, and the
  keyframe gate plus `redo shot N` handle the occasional bad shot. Later films used
  text-only characters on purpose, to avoid using anyone's photograph (see entries
  19 and 23 for how well that held).

### 4. Where the text encoder lives, and host RAM

- **Hypothesis:** moving the 8 GB text encoder off the GPU would relieve the
  tight VRAM margin without much cost.
- **Change:** ran the encoder on the CPU; compared repeated and new prompts;
  compared runs with plenty and little free host RAM.
- **Result:** on the CPU the encoder took 25 to 48 s per prompt and drove free RAM
  to 0.0 GB. With a cached prompt, 832x480 took 2.0 s without a reference, against
  4.5 s for a new prompt. With only about 4 GB of RAM free, the same jobs took 3 to
  5 s longer. After `POST /free`, the next job took 8.9 s instead of 6.4 s.
- **Decision:** leave the encoder to ComfyUI's built-in offload on the GPU. Keep
  one model resident: the pipeline asks ComfyUI to free memory after each stage.

### 5. Wan 2.2 TI2V 5B for motion on 8 GB (tickets 11 and 12)

- **Hypothesis:** the quantised 5B model animates a keyframe at 640x352, 24 fps,
  within 8 GB.
- **Change:** Wan 2.2 TI2V 5B Q5_K_M through ComfyUI, one clip per motion type.
- **Result:** it ran. The model draws about 37 s of ComfyUI time per output second.

  | Motion | Clip | ComfyUI time |
  |---|---:|---:|
  | Pan | 5.00 s | 185.65 s |
  | Ambient | 3.25 s | 119.97 s |
  | Push-in | 2.75 s | 101.95 s |

- **Decision:** use it. Generate one clip at a time. The resolution step-down on
  out-of-memory (640x352 to 512x288, new seed) is verified only against the fake
  ComfyUI server; real GPU memory exhaustion has not happened yet.

### 6. Prompt wording for camera motion

- **Hypothesis:** the motion prompt, not the keyframe or the seed, decides how much
  the camera moves.
- **Change:** the first pan also pushed in strongly. Rewrote the pan prompt and
  rerendered with the same keyframe and seed.
- **Result:** the second 5.00 s render showed subtle sideways motion at a nearly
  constant subject size (187.77 s).
- **Decision:** keep the motion vocabulary to `push_in`, `pan` and `ambient`, with
  prompt wording tuned per motion type.

### 7. Continuation clips for long narration lines

- **Hypothesis:** a second clip started from the first clip's last frame can cover
  a line that one clip cannot, without a visible jump or a frozen frame.
- **Change:** a 4.25 s opening clip plus a 3.00 s continuation for one shot.
- **Result:** 7.00 s of render covered 6.96 s of narration. All 16 decoded frames
  around the join were distinct, and the frames either side of it differed by a mean
  of 4.12 grey levels out of 255. The clips took 162.66 s and 109.12 s.
- **Decision:** keep continuation clips as the fallback when a speed change of up to
  1.3x is not enough.

### 8. Narration first, then fit the picture to it

- **Hypothesis:** real narration lengths will not match a fixed clip length, so the
  video has to be planned after the voice exists.
- **Change:** narration runs before video. A fit planner first changes playback
  speed (up to 1.3x either way), and only then adds a continuation clip. One shared
  visual set is sized to the longer language.
- **Result:** the sample's first English line was 5.66 s against a 5 s clip cap,
  which drove the design. From the ledgers' fit plans:

  | Film | Speeds, Amharic | Speeds, English | Continuation clips |
  |---|---|---|---:|
  | Coffee Highlands (512x288) | 0.86 to 1.02x | 1.07 to 1.30x | 1 |
  | Khalid | 0.82 to 1.24x | 0.90 to 1.25x | 0 |
  | Lion's Whisker | 0.90 to 1.08x | 1.00 to 1.30x | 0 |

- **Decision:** keep speed-then-continuation and `visuals: shared`. Shorter lines
  (about 10 words) kept the Lion's Whisker Amharic motion nearly unaltered.

### 9. Generation size against GPU time

- **Hypothesis:** the larger 640x352 frame is worth its extra time for a film.
- **Change:** rendered the same coffee story at 512x288 and then at 640x352; used
  640x352 (and 352x640) for the later films.
- **Result (recomputed from the ledgers):**

  | Run | Size | Clips | Output seconds | GPU time | Per output second | Mean 5 s clip |
  |---|---|---:|---:|---:|---:|---:|
  | Coffee Highlands | 512x288 | 11 | 49.75 | 19.6 min | 23.7 s | 116 s |
  | Coffee, realistic rerun | 640x352 | 11 | 47.75 | 31.3 min | 39.3 s | 192 s |
  | Khalid | 640x352 | 16 | 77.00 | 44.9 min | 35.0 s | 175 s |
  | Lion's Whisker 16:9 | 640x352 | 16 | 71.75 | 45.5 min | 38.0 s | 190 s |
  | Lion's Whisker 9:16 | 352x640 | 15 timed | 67.25 | 41.8 min | 37.3 s | 190 s |

  Both sizes were stable on the 8 GB card. The 9:16 row leaves out one clip that
  returned in 1.7 s after a restart (see FAILURES.md).
- **Decision:** 640x352 for films. Portrait costs about the same as landscape.
  832x480 video is untested on this card.

### 10. ACE-Step 1.5 for the score (ticket 13)

- **Hypothesis:** an open music model can score a 90 s film in 8 GB.
- **Change:** ACE-Step 1.5 Turbo through ComfyUI, instrumental only.
- **Result:** 90 s of stereo 48 kHz audio rendered in 22.78 s, peaking at
  6,231 MiB of VRAM. An 11 s score for the sample project took 6.75 s. In the film
  runs, scores of 48 to 81 s took 20.0 to 25.2 s (ledgers).
- **Decision:** ACE-Step for instrumental music. The song contract (lyrics and
  vocals) exists with a stub provider only.

### 11. Text through signed-in CLIs, with a fallback chain

- **Hypothesis:** vendor CLIs the author already pays for can replace per-call APIs,
  if replies are validated and a quota on one does not stop a run.
- **Change:** Gemini, Claude and Codex CLI adapters (tools disabled, empty temporary
  directory, schema validation, up to two re-prompts) and an ordered fallback chain.
- **Result:** Claude CLI passed the real text conformance suite. Gemini was never
  logged in, so its adapter has only been tested against a fake executable. In the
  first demo Claude hit its five-hour limit and Codex answered both the script and
  the storyboard; the ledger records each fallback with the error text. Changing
  only the storyboard model in YAML (`gpt-6.2-sol` to `gpt-6.2-astra`, and later
  `codex-cli` to `claude-cli`) regenerated only the storyboard.
- **Decision:** keep CLI providers with fallback chains. The first demo used Claude
  Code and Codex, with Codex as the fallback.

### 12. Catching translation drift with a back-translation by a second model

- **Hypothesis:** with no one reading every Amharic line, a different model
  translating it back blind will flag lines whose meaning moved.
- **Change:** after translating, a second model back-translates without seeing the
  English, then compares line by line. First demo: Codex `gpt-6.2-astra`
  translating, `gpt-6.2-sol` checking. Later films: Claude Opus 5.5 translating,
  Claude Sonnet 5.5 checking.
- **Result:**

  | Film | Flagged | What it said | Action |
  |---|---|---|---|
  | Coffee Highlands | lines 3 and 4 | berries became unspecified fruits, a path became a road | corrected by hand before narration; the updated review still records smaller differences on lines 3, 4, 5 and 7 |
  | Khalid | line 12 | "fruits" roasting instead of "seeds" | kept: ፍሬ covers both in Amharic |
  | Lion's Whisker | line 7 | the verb ራሳቸውን ነቀነቁ ("nodded") can also mean "shook his head" | rewritten as ተስማሙ ("agreed"); the re-check passed |
  | Lion's Whisker | line 10 | "resting" read back as "asleep" | kept |

  Hand edits to the Lion's Whisker translation and storyboard were kept by the
  ledger, and only the dependent artifacts regenerated.
- **Decision:** keep the check, with two distinct models, since one model checking
  itself says little. Show flags on stderr and in the UI and never block the run on
  them. It is a prompt to a human, not a substitute for a native speaker, and no
  native speaker has reviewed these films.

### 13. Narration voices: Edge TTS and Addis Voices 2

- **Hypothesis:** a free voice with no key is good enough to build on, and a
  dedicated Amharic service can be swapped in by config.
- **Change:** Edge TTS (`am-ET-AmehaNeural`, `am-ET-MekdesNeural`), then
  `addis-ai` (voice `am-hamen`, key from `ADDIS_API_KEY`) for Amharic.
- **Result:** both produced valid audio. The 25 Nov ledgers for the coffee projects
  have the same Amharic translation file (identical SHA-256). The ten MP3 durations
  and mean wall time per line were:

  | Project | Amharic provider in the ledger | Total audio | Wall time per line |
  |---|---|---:|---:|
  | `coffee-origin`, `coffee-origin-realistic-en` | Edge TTS | 49.61 s | 7.4 s |
  | `coffee-origin-live-action`, `coffee-origin-realistic` | Addis AI (`am-hamen`) | 47.49 s | 5.3 s |

  The projects in each row share the same narration records. Durations come from
  the MP3s and call times depend on the network. The architecture audit found that
  `doctor` checked only Edge and missed a missing Addis key.
- **Decision:** keep Edge as the default. All three radio-cut viewers found the
  Google voice robotic, so Lion's Whisker moved to Addis for Amharic (see
  [DESIGN.md §8–9](DESIGN.md#8-user-test-1-the-radio-cut)). The landscape fit plan
  dropped from 70.46 to 62.85 s before the end card. Nine of 16 shared clips became
  shorter and all nine were regenerated, as recorded in `final-run.log` and
  `runs.jsonl` (24.01 GPU-min for video). The portrait fit plan independently
  measured 64.57 s before the card. Seven shared clips became shorter and all
  seven were regenerated (18.45 GPU-min for video). The projects made separate
  Addis calls, so the timing changed by a different amount in each format.
  See [COSTS.md](COSTS.md#final-addis-rerender).

### 14. A full real-provider run, then resume and re-roll (ticket 15)

- **Hypothesis:** content-hashed artifacts let an interrupted run resume, an
  unchanged rerun do nothing, and one shot be re-rolled alone.
- **Change:** rendered *The Coffee Highlands* in two languages at 512x288 from 10
  FLUX.2 keyframes, 11 Wan clips (one a continuation) and one ACE-Step score.
- **Result:** both renders assembled, 41.58 s in English and 49.63 s in Amharic.
  Both decoded cleanly, and a sampled Amharic frame showed real Ethiopic subtitles.
  An interrupted Edge TTS run kept all six finished clips. An unchanged full rerun
  skipped every stage and kept both MP4 hashes. `redo shot 2` changed only that
  shot's keyframe and video plus the two assemblies.
- **Decision:** keep the ledger design. It is what makes every later entry cheap.

### 15. Style text leaking into unrelated shots

- **Hypothesis:** the bible's style description affects only the look.
- **Change:** a style description that described coffee brewing was sent with every
  storyboard and keyframe prompt; then it was rewritten.
- **Result:** unrelated keyframes gained inset brewing images. A full-frame style
  description cleared the insets.
- **Decision:** keep only the look (lighting, lens, treatment) in the style, and
  describe actions in each shot. Stills are reviewed at the keyframe gate before
  animation, since that is the cheapest point to catch a bad shot.

### 16. Live-action by default (26 Nov)

- **Hypothesis:** the video model animates photographic footage better than
  stylised art.
- **Change:** when the bible sets no style, every keyframe prompt ends with a
  default look: "Photorealistic live-action film footage… No illustration, painting
  or animation." A bible style replaces it. The coffee-origin example was switched
  to live-action and its protagonist reference image removed.
- **Result:** the video model animates photographic footage far better than stylised
  art; in stylised trials it smeared and warped. This is a judgement from watching
  the output. No number was recorded.
- **Decision:** live-action is the pipeline default.

### 17. Storyboard rules for what the models get wrong (26 Nov)

- **Hypothesis:** telling the storyboard model the image and video models' weak
  points will prevent the worst frames.
- **Change:** the live-action rerun showed goats rearing up like people and
  secondary characters copying the protagonist's face and clothes. A fixed set of
  rules now goes with every storyboard request:
  - animals stay on four legs, never rearing or posed like people;
  - objects keep their real-world arrangement;
  - anyone other than the shot's character looks clearly different, and the visual
    says so;
  - hands stay simple;
  - at most four people per shot.

  Each keyframe prompt also says that anyone else in the shot looks unlike the main
  character.
- **Result:** goats natural and no cloned protagonists. One problem remained: shot 7
  drew the fire inside the roasting pan. That is a keyframe-model limit, not a
  storyboard one, and it was left for a re-roll.
- **Decision:** keep the rules in the prompts the pipeline sends, not only in a
  document, so they apply on every run.

### 18. Script length cap (26 Nov)

- **Hypothesis:** the script stage follows the brief's requested length.
- **Change:** the first Khalid script was 12 lines and 54 s, although the brief
  asked for 16 lines and about 70 s. The prompt had a hard-coded "6 to 12 lines,
  under 60 seconds". Replaced it with a cap derived from the render limit: 6 to 18
  lines (90 s at 5 s per line), under 90 s, following the brief's own line count
  when it gives one in that range.
- **Result:** the rerun wrote 16 lines.
- **Decision:** keep the derived cap.

### 19. A brief the pipeline had never seen: *Khalid and the First Coffee* (26 Nov)

- **Hypothesis:** the pipeline can turn an unseen brief into a film of at least 60 s,
  with characters described only in text.
- **Change:** 16 lines of about 11 words, 640x352 at 24 fps, two characters and
  three locations with no reference pictures, a photorealistic highlands look, music
  at 84 BPM in D major. Translation moved from Codex (quota) to Claude Opus 5.5 with
  Sonnet 5.5 as fallback.
- **Result:** exit 0. English 70.9 s, Amharic 75.8 s. 16 keyframes, 16 clips, no
  continuations, speeds 0.82 to 1.25x. 46.5 min of GPU time (ledger), nearly all
  video (about 3 min per clip). Frame sheets showed natural goats, a consistent
  Khalid and monk, distinct villagers, and correct English and Ge'ez subtitles.
  Weak spots: unnaturally wide eyes in shot 8, an over-tight push-in in shot 9,
  interiors coming out as exteriors in shots 11 to 14, long Amharic subtitle lines.
- **Decision:** text-only characters are enough for a short with a small cast. The
  weak shots were left for `redo shot N` or a subtitle tweak.

### 20. AI disclosure as a pipeline feature (26 Nov)

- **Hypothesis:** an end card built into the pipeline survives every re-render and
  costs little to add.
- **Change:** an optional `end_card:` block adds a closing card: white on black, a
  bold headline and smaller lines, with a fade. It says the video is AI-generated
  and that any resemblance is coincidental, with default wording in English and
  Amharic (the Amharic card repeats the message in English). The music is generated
  long enough to play under it and fades over its last 3 s. The 90 s limit counts
  the card.
- **Result:** adding it to Khalid regenerated only the music (24 s of GPU) and the
  two assemblies. English went to 75.9 s and Amharic to 80.8 s.
- **Decision:** off unless configured, because switching it on by default would
  change every existing render's length. On for the Khalid and Lion's Whisker films.
  `DESIGN.md` and `ETHICS.md` were written next to the Khalid cut; the ethics
  write-up flags what is still needed before a commercial release: a licensed TTS
  service, a check of model licences, and a native speaker's review.

### 21. Exact 16:9 and a native 9:16 (26 Nov)

- **Hypothesis:** the model's multiple-of-32 sizes can be turned into exact delivery
  frames in assembly, and portrait is better generated than cropped.
- **Change:** the Khalid cut was 640x352, which is 1.82:1, not 16:9. Added
  `output_size`: each clip is scaled to cover the frame and cropped to its shape.
  The Wan mapping capped height at 480, which ruled out portrait; replaced the cap
  with a pixel budget (832x480 worth, either orientation) and turned the
  out-of-memory step-down sizes for portrait (352x640 steps down to 288x512).
- **Result:** 640x352 becomes exact 1280x720 with a 2% side crop, and changing it
  re-runs only assembly. The workflow digest leaves out limits, so existing clips
  stayed valid. A 9:16 crop of a 16:9 frame would keep only about 30% of the picture
  and lose a person from every two-person shot. `ffprobe` on the v1 files
  shows 1280x720 and 720x1280 at 24 fps.
- **Decision:** generate the vertical cut fresh from the same storyboard at 352x640.
  Text, narration, timing and music are reused by copying the project's `build/`
  folder, so only keyframes and clips cost GPU time.

### 22. Choosing a story for the models' strengths: *The Lion's Whisker* (26 Nov)

- **Hypothesis:** a tale with few characters, an animal that barely moves and an arc
  about patience will survive generation better than an action story.
- **Change:** five Ethiopian tales were considered (The Lion's Whisker, Saint Yared
  and the caterpillar, Fire on the Mountain, Lalibela and the bees, the Meskel
  smoke). Retold in our own words with our own names (Almaz, Dawit). 16 lines of
  about 10 words, one fewer than Khalid because Amharic runs longer. The brief says
  the lion is always calm. Music at 76 BPM in A minor.
- **Result:** both cuts are 75.5 s (70.5 s of narration plus the 5 s card), at
  1280x720 and 720x1280, and both decode cleanly. Amharic speeds 0.90 to 1.08x, no
  continuation clips. GPU time 47.8 min for 16:9 and 43.6 min for 9:16 (ledgers).
  The 9:16 run was interrupted by a server restart after 2 clips; the resumed run
  kept them. Weak spots: two green streak artefacts (shots 4 and 13 in 16:9),
  Almaz's costume changes in shot 16, the elder's skin tone still varies a little,
  portrait subtitles wrap to 2 to 4 lines.
- **Decision:** deliver this film, in Amharic. The pipeline writes the script in
  English, its working language, so an English cut is rendered as a by-product.

### 23. The keyframe gate before animation (26 Nov)

- **Hypothesis:** most defects are visible in the still, so reviewing every keyframe
  saves video GPU time.
- **Change:** reviewed all Lion's Whisker keyframes before running the video stage,
  and edited the storyboard and bible where a still was wrong.
- **Result:** in 16:9: the lion lost its mane in shots where Almaz was the main
  character; the elder came out lighter-skinned in two shots; stray figures appeared
  behind Almaz and the elder appeared twice in one shot; the storyboard dressed
  Dawit differently from the bible. Fixed by naming the mane in those shots, adding
  the elder's skin tone to the bible, adding "alone, the only person in the shot",
  and editing Dawit's clothes. That took 12 re-rolls at about 7 s each, before any
  video GPU time. Portrait needed the same fix in two more shots (an extra man, and
  a second woman).
- **Decision:** keep the gate. Three pipeline gaps it exposed are each worth a
  prompt change: the storyboard model sees character names but not their
  descriptions, so it invents clothing; a shot passes only its main character's
  description to the keyframer, so a second character (the lion) drifts; the image
  model fills empty space with people, so solo shots need to say so. Subtitle size
  should also scale with the frame's shorter side, not its height.

### 24. A local UI, run state and a one-writer lock (26 Nov, [spec](.scratch/vidpipe-ui/spec.md))

- **Hypothesis:** runs that take up to an hour, with a terminal that showed nothing
  until a stage finished, can be watched and controlled safely if the runner itself
  publishes its state and only one process may write.
- **Change:** designed in an interview and built as 12 tickets.
  - One local web app per project (`vidpipe ui <project>`): a stage rail with live
    status, each stage's outputs, run controls, gate approval and a config view. The
    aim was visibility without clutter.
  - Starlette and uvicorn, a no-build vanilla front end, one SSE stream. There is no
    build step to maintain, and one event stream is enough for run state and config
    changes.
  - Localhost by default; `--host` requires a random token printed at startup, so
    that control of runs is never open to the network by accident.
  - The runner publishes `build/run_state.json`, rewritten atomically after every
    artifact, so the UI and the CLI see the same runs.
  - A one-writer lock with `filelock`. The open question was whether an OS file lock
    ties the tool to one platform. It does not: filelock is cross-platform, and the
    OS releases the lock if the process dies. The GPU wrapper uses the same
    mechanism. Projects on network drives are unsupported.
  - Stop requests are checked between artifacts; "stop now" also cancels the running
    ComfyUI job. A stopped run exits with code 4.
  - Config changes made during a run apply to the next run
    ([ADR 0002](docs/adr/0002-config-changes-apply-next-run.md)), because a run that
    changes config halfway produces a video no config describes.
  - Look: a "studio console", following modern-web-guidance, with Mona Sans and
    JetBrains Mono bundled under the OFL. English only; Amharic content uses the
    system font.
- **Result:** all 12 tickets merged. 346 tests passed and 2 were skipped, plus 7
  Playwright browser tests. At the time of logging, a code review and the cleanup of
  stale worktrees were still to do.
- **Decision:** ship it as an optional `ui` extra.

### 25. Give each model the details it needs (26 Nov)

- **Hypothesis:** explicit cast descriptions and counts will cut bad keyframes.
  One small movement and one camera instruction will make the clips easier to animate.
- **Change:** the storyboard model now sees the bible's character descriptions.
  Keyframe prompts describe the secondary bible characters the visual names
  (`others`) and state the shot's `people` count (at most four). Wan gets the
  `visual`, a separate `movement` line and one camera sentence. Its longer negative
  prompt includes the official Chinese list plus artefact and camera terms.
  See [model strengths and the shot 10 A/B](docs/research/model-strengths.md).
- **Result:** in the shot 10 A/B, the movement-only prompt and the sentence asking
  shapes to stay steady each produced coloured bars. Keeping the scene description
  and removing that sentence gave a clean sample with the new negative prompt.
  The landscape comparison used v1's `keyframe-review.jpg` and `frames-am.jpg`,
  and v2 sheets from `build/keyframes/shot_*.png` and the Amharic MP4, with one
  middle and one late sample per shot.

  | Check | What the sheets show |
  |---|---|
  | Mane | The v2 lion has a dark mane in shots 10 to 13. The reviewed v1 sheet already shows manes after the manual prompt fixes. |
  | Stray or duplicate people | V1's gate sheet has a figure behind Almaz in shot 5 and extra figures around the elder in shot 15. In the v2 sheet Almaz is alone in both. Shot 15 now shows her listening by the fire. Earlier v2 trials still drew duplicate lions and elders. |
  | Skin tone | The v2 husband is darker than in v1. The elder's skin tone still varies between shots. |
  | Costume | Almaz keeps the red-trimmed white shawl in shot 16, and Dawit is in blue in shots 3 and 16. Almaz's head covering still changes between shots. |
  | Artefacts | The v1 green streaks in shots 4 and 13 did not show up in the sampled v2 frames. Shot 4 still has a strong shift in light. Some faces soften late in a shot, and Almaz is partly cropped in shot 5. The later Addis landscape rerender has red blocks in shot 12. |

  V1 landscape needed 12 gate re-rolls. The v2 ledgers retain 16 keyframes per
  format and record four explicit re-rolls per format: landscape shot 11 three
  times and shot 15 once, portrait shot 11 twice and shots 15 and 16 once each.
  The landscape `kf-run.log` and `kf-run2.log` also each report 16 generated
  keyframes. Whole passes and prompt edits are outside the manual re-roll count.
- **Decision:** keep the cast and motion rules and the keyframe gate. Test motion
  on two or three shots before rendering a full cut. The sheets sample still
  frames, so they cannot establish how often the clips flicker.

### 26. Normalise the final mix (26 Nov)

- **Hypothesis:** normalising after ducking will raise the mix to the brief's
  loudness guide.
- **Change:** added two-pass FFmpeg `loudnorm` controlled by `mix.loudness_lufs`,
  with a -14 LUFS default and a -1 dBTP true-peak target.
- **Result:** the earlier Lion's Whisker and Khalid mixes measured -20.6 to
  -24.4 LUFS. FFmpeg `ebur128=peak=true` measured both final Amharic MP4s at
  -14.0 LUFS. Encoded true peaks were -1.0 dBTP in landscape and -0.6 dBTP in
  portrait. See [FAILURES.md](FAILURES.md#34-the-mix-is-much-quieter-than-platforms-expect).
- **Decision:** keep the target in the project config and measure the encoded mix.

### 27. English subtitles on the Amharic cut (26 Nov)

- **Hypothesis:** English captions can follow the Amharic shot timing while
  keeping the Amharic voice.
- **Change:** set `subtitles.text_language: en`. Assembly uses the English
  source lines and times them to each shot of the Amharic fit plan.
- **Result:** the final sidecars contain 16 English cues in landscape and 23
  in portrait. The cue boundaries at each shot change match the Amharic fit plan
  to within 1 ms in both cuts. The captions are visible in sampled frames across
  all 16 shots of each cut.
- **Decision:** use English burned-in captions and keep the matching sidecar for
  the Amharic cut.

## Planning decisions (25 Nov, before any code)

These came out of the design interview. They are decisions, not experiments.

- **Local first, ComfyUI as an external service.** Hosted APIs stay possible through
  the same provider contracts. Why: local runs cost nothing per call, and keeping
  ComfyUI outside the pipeline avoids managing its install.
- **Typed contract per stage, workflow JSON plus a mapping file per model.** Why:
  adding a local model should need no new Python.
- **Content-hashed project directory, no database.** Why: skip unchanged work, resume
  after a crash, and re-roll one shot cheaply.
- **Approval gates after script, storyboard and keyframes.** Why: catch problems
  before the expensive stages.
- **Narration before video, with a fit planner in between.** Why: real voice lengths
  decide how much video each shot needs, before any GPU time is spent.
- **Amharic as the second language, with a back-translation check by a different
  model.** Why: no one on the project reads every line, so drift needs flagging.
- **Testing at two seams only:** a full pipeline run on fake providers, and a shared
  conformance suite every provider must pass. Why: the fakes keep tests fast without
  a GPU, and conformance proves providers are swappable.

## Environment notes

- The Python on PATH was the Microsoft Store stub. Python 3.12 and uv were installed
  with winget.
- SSH push to GitHub failed on this machine. The remote was switched to HTTPS,
  authenticated through `gh auth setup-git`.
- The PowerShell GPU wrapper aborted mid-run on harmless stderr warnings. GPU work
  runs through `run_gpu.py`, or straight through `uv run vidpipe run` when nothing
  else is using the GPU.
- Usage limits interrupted work twice. Claude and Codex agents stopped at their
  quotas partway through tickets, and committed but unmerged work was merged by hand.
  Codex's quota also stopped a translation run (entry 19).

## Open questions and trials not yet run

- Real GPU out-of-memory recovery for keyframes, video and music is untested.
- 832x480 video output is untested on 8 GB.
- Gemini and Codex tool-disabling flags are unverified against the real CLIs (Codex
  has since run real storyboard and translation jobs).
- The FLUX.2 VAE repack carries a non-commercial licence tag. Check it before any
  commercial use (see [ETHICS.md](ETHICS.md)).
- The radio-cut and picture-cut user tests are recorded in [DESIGN.md](DESIGN.md).
  No viewer test of the final Addis cuts is recorded.
- No comparison with a frontier model: there was no paid access.
- There is no trial here for generating several music candidates and recording
  a choice (`music.candidates`, `music.choice`), or for the pipeline's
  `vidpipe radio-cut` command. The user test used a radio cut made separately.
