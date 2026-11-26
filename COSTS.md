# Costs

Measured time and GPU minutes per stage, and what the same work would cost at list
price.

## In short

| | Lion's Whisker v1 16:9 | Lion's Whisker v1 9:16 | Both v1 cuts |
|---|---:|---:|---:|
| GPU time (measured) | 47.8 min | 43.6 min | 91.4 min |
| Cash paid per call | $0 | $0 | $0 |
| Rented GPU, same minutes (estimate) | $0.27 to $0.71 | $0.25 to $0.65 | $0.52 to $1.36 |
| Hosted media APIs, list price (estimate, without text) | $2.68 | $2.62 | $5.30 |

Video is 95% of the v1 GPU time. The v2 ledgers retain 91.72 GPU-min for both
formats. The final Addis rerenders added 24.39 GPU-min in landscape and 18.84
in portrait, including their replacement scores. See the [v2 totals](#v2-retained-artifacts)
and [Addis rerender](#final-addis-rerender). There was no paid access to a
frontier image, video or music model for comparison.

## Where the numbers come from

- **Machine:** RTX 4060 Laptop GPU (8 GB VRAM), 31 GB RAM, Windows 11, ComfyUI
  Desktop 0.46.3.
- **Source:** each project's `build/ledger.json`, which records `gpu_seconds` (ComfyUI
  execution time) and `wall_seconds` (time around the provider call) per artifact.
  The projects live outside the repository in `%USERPROFILE%\.t3\vidpipe-demos\`.
- **Limit of the ledger:** it keeps only the latest record per artifact. Replaced
  keyframes and clips drop out of its totals. New runs record generation attempts
  in `<project>/runs.jsonl`, with latency and GPU seconds. The v1 and v2 runs
  predate those logs. The Addis rerender has them.
- All run figures are from 25 and 26 November 2026.

## Per stage, Lion's Whisker v1

"Calls" are artifacts in the ledger. Wall time is the sum over calls, in seconds.
GPU time is zero for hosted and CPU stages.

| Stage | Provider | Lion 16:9 calls | wall s | GPU s | Lion 9:16 calls | wall s | GPU s |
|---|---|---:|---:|---:|---:|---:|---:|
| script | Claude CLI | 1 | 8.7 | 0 | reused | 0 | 0 |
| translation | Claude CLI (Opus 5.5) | 1 | 17.5 | 0 | reused | 0 | 0 |
| translation review | Claude CLI | 1 record (2 calls) | 17.9 | 0 | reused | 0 | 0 |
| storyboard | Claude CLI | 1 | 24.0 | 0 | reused | 0 | 0 |
| narration | Edge TTS | 32 | 128.2 | 0 | reused | 0 | 0 |
| fit planning | local | 1 | <0.1 | 0 | 1 | <0.1 | 0 |
| keyframes | FLUX.2 klein 4B | 16 | 120.6 | 112.4 | 16 | 118.6 | 110.8 |
| video | Wan 2.2 TI2V 5B | 16 | 2,743.9 | 2,729.3 | 16 | 2,521.0 | 2,506.8 |
| music | ACE-Step 1.5 | 1 | 28.6 | 25.2 | reused | 0 | 0 |
| assembly | FFmpeg | 2 | 31.8 | 0 | 2 | 28.9 | 0 |
| **Total** | | | **3,121 (52.0 min)** | **2,866.8 (47.8 min)** | | **2,669 (44.5 min)** | **2,617.6 (43.6 min)** |

The 9:16 project was made by copying the 16:9 project's `build/` folder, so its
ledger also holds the shared text, voice and music records. They are shown as reused
and not counted twice.

Elapsed time from first to last artifact was 55 min for 16:9, including keyframe
review and edits, and 52 min for 9:16, including a gap of about 7 min around a server
restart.

## V2 retained artifacts

Sum of `gpu_seconds` by stage from `lions-whisker-v2-16x9/build/ledger.json` and
`lions-whisker-v2-9x16/build/ledger.json`. Each ledger holds 16 keyframes and
16 clips. Text, narration, fit planning and assembly account for zero GPU seconds.

| Stage | 16:9 GPU s | 9:16 GPU s | Both GPU s |
|---|---:|---:|---:|
| Keyframes | 144.061 | 113.686 | 257.747 |
| Video | 2,624.642 | 2,594.420 | 5,219.062 |
| Music | 26.249 | reused | 26.249 |
| **Total** | **2,794.952 (46.58 min)** | **2,708.106 (45.14 min)** | **5,503.058 (91.72 min)** |

The portrait ledger also contains the copied 26.249 s music record. Its raw sum is
2,734.355 s. The table counts the score once. The v2 video records average
163.1 s per clip (2.72 min). V1 averaged 163.6 s including a 1.7 s result after a
restart, or 168.9 s across the other 31 clips.

## V2 render time

The v2 work ran from about **15:49 to 19:06 local** on 26 Nov (about 3 h 17 min).
The first landscape keyframe transcript was last written at 15:49 and the
portrait `build/run_state.json` records completion at 19:06:27.

| Source | Recorded work |
|---|---|
| Landscape `full-run.log`, `full-run2.log` and portrait `full-run.log` | 16 generated clips in each pass (48 across the three logs). The ledgers retain 32 clips. |
| Comfy Desktop `logs/app.log` | 111 completed prompts, totalling 176.87 min of reported execution, from the first retained landscape still (10.79 s) through the last portrait clip (160.21 s). |
| Ledger and server log comparison | 65 retained jobs (32 keyframes, 32 clips, one score), matched in time order by duration. About 85.15 min of the logged execution is outside those retained records. |
| Archived first landscape pass | 16 consecutive video completions before the 26.26 s score, totalling 44.42 min. The archive at `lions-whisker-v2-16x9/render1/` holds the first render and A/B samples. |

The roughly 46-minute gap in the retained ledger between the landscape stills and
the score includes that first video pass. The next roughly 21-minute gap, between
portrait stills and the resumed landscape video, contains seven more completions
totalling 16.87 min in the server log. Their position fits the shot 10 A/B work.
The server lines give durations and order, with no per-prompt timestamps or shot
IDs. From the first ledger anchor (15:51:40) to portrait completion, about 18 min
of elapsed time remains after subtracting logged prompt execution. This includes
assembly and time between prompts. Exact GPU idle time, the full set of overwritten
shot IDs and seeds, and the GPU cost caused solely by the prompt change cannot
be recovered. There was no per-attempt `runs.jsonl` for this v2 run.

## Final Addis rerender

| Cut | Amharic story time in fit plan | Shared clips planned shorter | Verified new GPU work |
|---|---|---:|---|
| 16:9 | 70.46 s → 62.85 s | 9 of 16 | 9 clips (1,440.751 s) plus one score (22.877 s) |
| 9:16 | 70.46 s → 64.57 s | 7 of 16 | 7 clips (1,107.005 s) plus one score (23.528 s) |

Each project's `final-run.log` records two assemblies and agrees with
`runs.jsonl` on the new clip count. Landscape regenerated shots 2, 3, 5, 6, 7,
8, 9, 10 and 12. Portrait regenerated shots 2, 3, 6, 7, 8, 9 and 12. The
new clips and score took **24.39 GPU-min** in landscape and **18.84 GPU-min**
in portrait. Assembly finished at 19:54:04 and 20:15:32 local respectively
in `build/run_state.json`.

Final retained totals are **2,727.170 s (45.45 min)** in
`lions-whisker-final-16x9/build/ledger.json` and **2,700.729 s (45.01 min)** in
`lions-whisker-final-9x16/build/ledger.json`. These totals include reused
keyframes and clips and one newly generated score per cut.

## Per stage, the other films

| Stage | Khalid (640x352) calls | wall s | GPU s | Coffee Highlands (512x288) calls | wall s | GPU s |
|---|---:|---:|---:|---:|---:|---:|
| script | 1 | 12.0 | 0 | 1 | 16.2 | 0 |
| translation | 1 | 18.3 | 0 | 1 | 25.0 | 0 |
| translation review | 1 record | 16.3 | 0 | 1 record | 44.2 | 0 |
| storyboard | 1 | 25.5 | 0 | 1 | 29.3 | 0 |
| narration | 32 | 87.3 | 0 | 20 | 123.7 | 0 |
| keyframes | 16 | 76.9 | 70.2 | 10 | 58.7 | 53.4 |
| video | 16 | 2,705.4 | 2,692.9 | 11 | 1,188.1 | 1,177.5 |
| music | 1 | 24.8 | 24.1 | 1 | 23.2 | 22.2 |
| assembly | 2 | 17.4 | 0 | 2 | 9.4 | 0 |
| **Total** | | **2,984 (49.7 min)** | **2,787.3 (46.5 min)** | | **1,518 (25.3 min)** | **1,253.2 (20.9 min)** |

The coffee story was rendered again at 640x352 with a realistic look: keyframes
82.3 s, video 1,875.2 s (31.3 min), music 20.0 s of GPU.

## Per unit

| Unit | Size | Measured | Samples |
|---|---|---|---|
| Keyframe, no reference | 640x352 | median 4.0 s (3.8 to 10.6) | Khalid, 16 |
| Keyframe, no reference | 640x352 | median 6.6 s (6.4 to 9.6) | Lion 16:9, 16 |
| Keyframe, no reference | 352x640 | median 6.6 s (6.5 to 9.1) | Lion 9:16, 16 |
| Keyframe, 0 / 1 / 2 references | 832x480 | about 4.5 / 6.5 / 9 s | [ADR 0001](docs/adr/0001-keyframe-model.md) |
| 5 s clip (121 frames, 20 steps) | 640x352 or 352x640 | mean 184 s, **3.1 min** (173 to 200) | 19 clips, 4 runs |
| 5 s clip | 512x288 | mean 116 s, 1.9 min (113 to 125) | 5 clips |
| Video per output second | 640x352 | 35.0 to 39.3 s | 4 runs |
| Video per output second | 512x288 | 23.7 s | 1 run |
| Music track, 48 to 81 s | | 20.0 to 25.2 s | 4 tracks |
| Music track, 90 s | | 22.8 s, peak 6,231 MiB | ticket 13 |
| Narration line | | run means 2.7 to 6.2 s (network) | |
| Text call | | 9 to 44 s per record | |
| Assembly, one language | 1280x720 or 720x1280 | 13.7 to 16.6 s, CPU | 4 renders |
| Assembly, one language | 640x352 or 512x288 | 4.5 to 9.1 s, CPU | |

The first keyframe of a run is the slow one, because models load.

## What a change costs

| Change | What regenerates | Rough time |
|---|---|---|
| `redo shot N` | one keyframe, one clip (more if the shot has continuations), assembly | about 4 min |
| Edit one shot's visual in the storyboard | that keyframe and clip, assembly | about 4 min |
| Edit one narration line (in `storyboard.json`, or in a translation file) | that narration line, the fit plan, assembly, and the back-translation check for a translation file; the shot's clip too if its planned length changes | about 1 min, or about 4 min with the clip |
| Change `output_size` or subtitle settings | assembly only | about 30 s for two languages |
| Add the end card | music and assembly | measured: 24 s of GPU for the music, then assembly |
| Ask for three music candidates | the extra scores and assembly | about 25 s of GPU per candidate |
| Change `music.choice` | assembly only | about 30 s |
| `radio-cut` | a black-screen render, no GPU | not measured |

With a `storyboard.json`, no text model is called at all. Without one, editing
`build/script.json` is the expensive edit: the translation and the storyboard both
read it. Loudness normalisation adds a second FFmpeg pass over the audio, whose cost
has not been measured. See [ARCHITECTURE.md](ARCHITECTURE.md).

For a walkthrough that regenerates one shot live, change one shot's `visual` (one new
keyframe, then one clip) or one narration line (one new voice call).

## V1 call counts per film

| Kind | Per film, two languages | Notes |
|---|---|---|
| Text model calls | at least 5: script, translation, back-translation, comparison, storyboard | Lion's Whisker re-ran the check after line 7 was rewritten, so at least 7. Re-prompts after invalid replies are not in the ledger. |
| TTS calls | 32 (16 lines x 2 languages) | Lion's Whisker line 7 was spoken again after the rewrite. |
| TTS characters | Lion: 1,481 (868 English, 613 Amharic). Khalid: 1,688 | counted from the script files |
| Narration audio | Lion: 134 s. Khalid: 147 s | from the fit plans |
| Image calls | 16 per format, plus re-rolls | Lion: 12 re-rolls in 16:9, 2 in 9:16 |
| Video calls | 16 per format | |
| Music calls | 1 | |

Token counts were not recorded.

## V1 re-rolls outside the retained totals

The 14 Lion's Whisker keyframe re-rolls were overwritten in the ledger. At about 7 s
each that is about **1.6 min** of extra GPU time (estimate). Work lost in the
interrupted 9:16 run is unknown. An earlier design note reads "112 s GPU (16 shots +
12 rerolls)"; the 112 s is the 16 surviving keyframes only.

## Planner estimates against measurements

`vidpipe plan` prices work from figures in the workflow mapping files.

| Stage | Planner assumes | Measured | Verdict |
|---|---|---|---|
| Video | 0.62 GPU min per output second (37 s) | 35 to 39 s at 640x352 | within about 6% |
| Video at 512x288 | same | 24 s | planner about 57% high |
| Keyframes | 0.11 GPU min each (6.6 s) | run means 4.4 to 8.2 s | close |
| Music | 0.01 GPU min per second (46 s for a 76 s score) | 25 s | planner about 80% high |

The video figure takes no account of frame size. The music figure is marked in its
mapping file as an estimate pending a benchmark.

## List-price equivalent

Prices were read on **26 November 2026** from the pages linked below. They change
often.

### The same GPU minutes on a rented GPU

**Assumption:** a rented card needs the same minutes as the laptop 4060. A faster card
should need fewer, but we have not measured one. Boot time, downloading about 34 GB
of models, storage and idle time are **not** included; one extra hour would add $0.34
to $0.89.

[RunPod pricing](https://www.runpod.io/pricing) (page dated 12 November 2026): RTX
4090 $0.34/h community, $0.89/h secure; serverless 16 GB class $0.58/h.

| Film | GPU hours | 4090 community | 4090 secure | Serverless 16 GB |
|---|---:|---:|---:|---:|
| Lion 16:9 | 0.80 | $0.27 | $0.71 | $0.46 |
| Lion 9:16 | 0.73 | $0.25 | $0.65 | $0.42 |
| Lion, both | 1.52 | $0.52 | $1.36 | $0.88 |
| Khalid | 0.77 | $0.26 | $0.69 | $0.45 |
| Coffee Highlands (512x288) | 0.35 | $0.12 | $0.31 | $0.20 |

### Hosted APIs instead of local models

| Work | Price used | Source |
|---|---|---|
| Keyframe | $0.014 per image (FLUX.2 klein 4B, first megapixel) | [Black Forest Labs](https://bfl.ai/pricing) |
| Video clip | $0.15 per video (Wan 2.2 5B image-to-video). The page says the model will be removed on 4 January 2027 and gives no resolution breakdown | [fal](https://fal.ai/models/fal-ai/wan/v2.2-5b/image-to-video) |
| Music | $0.0003 per output second (ACE-Step 1.5) | [fal](https://fal.ai/models/fal-ai/ace-step-1.5/llms.txt) |
| Narration | $9.00 per million audio tokens, 25 tokens per second (Gemini 3.8 Flash TTS, until 31 December 2026; text input $0.50 per million is negligible) | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| Narration, alternative | $15 per million characters (Azure neural, US East) | [Azure retail prices API](https://prices.azure.com/api/retail/prices) |

| Film | Keyframes | Video | Music | Narration | Total |
|---|---:|---:|---:|---:|---:|
| Lion 16:9 | $0.22 | $2.40 | $0.02 | $0.03 | **$2.68** |
| Lion 9:16 (pictures only) | $0.22 | $2.40 | reused | reused | **$2.62** |
| Lion, both | $0.45 | $4.80 | $0.02 | $0.03 | **$5.30** |
| Khalid | $0.22 | $2.40 | $0.02 | $0.03 | **$2.68** |

The 14 re-rolls would add about $0.20. These are not like-for-like: a hosted clip has
its own resolution and length, and hosted narration has different voices.

### Text

We used the Claude CLI under an existing subscription, so no per-call bill exists.
**Assumption:** five calls per film of at most 4,000 input and 3,000 output tokens
each, not counting any system prompt the CLI adds. At
[Anthropic's list price](https://platform.claude.com/docs/en/about-claude/pricing)
that is at most about **$0.38 per film on Claude Opus 5.5** ($4 / $20 per million
tokens) or $0.19 on Sonnet 5.5 ($2 / $10). This is a rough figure, not a
measurement.

### Free tiers the brief suggests

| Service | What we found on 26 November 2026 | Did we use it |
|---|---|---|
| [Cloudflare Workers AI](https://developers.cloudflare.com/workers-ai/platform/pricing/) | 10,000 neurons a day free. FLUX.2 klein 4B costs $0.000287 per 512x512 output tile, about 26 neurons. If one 640x352 image bills as one tile (assumption), that is about 380 images a day, and 32 images would cost under $0.01 paid | no |
| [Gemini API](https://ai.google.dev/gemini-api/docs/pricing) | free tier listed for Gemini 3.8 Flash and Flash TTS; free-tier content is used to improve Google's products | no |
| Kaggle GPUs | about 30 GPU hours a week according to third-party guides; Kaggle's own page did not load for us, so this is unverified | no |

We did not run any of these, so we have no latency, quality or rate-limit
measurements for them.

## What is not measured

- Electricity. If the whole laptop drew 150 W (assumption), both Lion's Whisker cuts
  used about 0.23 kWh.
- The cost of the coding agents (Claude Code, Codex) that wrote the pipeline.
- Model downloads and setup time.
- Cost of any frontier model: no paid access, so no frontier comparison.
