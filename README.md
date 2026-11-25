<img src="assets/icon.svg" width="64" height="64" alt="">

# vidpipe

A provider-pluggable studio pipeline for short video. See `.scratch/vidpipe/spec.md`.

```
uv sync
uv run vidpipe plan examples/sample          # resolve providers, fit plan and GPU/cost estimate; generates nothing
uv run vidpipe run examples/sample --until music   # everything except the ffmpeg render
uv run vidpipe doctor examples/sample        # check the dependencies for this project
uv run vidpipe run examples/sample            # full render (needs ffmpeg + ffprobe)
```

A project is a directory with `brief.md`, `vidpipe.yaml` and optionally `bible.yaml` (the
[project bible](#the-project-bible)); artifacts go to `build/`, renders to `out/`. The sample project
uses fake providers only; see [keyframes on ComfyUI](#keyframes-on-comfyui) to draw real ones.

## Artifacts, skip-unchanged and resume

Every generated artifact is recorded in `build/ledger.json` (key, input hash, provider and options,
parameters, seed, GPU seconds, wall time, output file hashes, any recorded fallback). `vidpipe run`
hashes what each artifact depends on and regenerates it only when that changed, so the same command
skips finished work and resumes a run that was killed (the ledger is saved after every artifact).

- Inputs are hashed by *content*: upstream files, plain values (prompts, text), the provider's
  `fingerprint()` and the options configured for it in `vidpipe.yaml`, parameters and seed. A regenerated upstream file that comes out
  identical invalidates nothing downstream.
- Hand edits work: edit `build/script.json` (or a translation) and only the artifacts that read it are
  redone. An artifact whose own inputs are unchanged is never overwritten.
- A stage declares its inputs where it produces an artifact:
  `ctx.produce(key, inputs=Inputs(files=[...], values={...}), parameters={...}, seed=..., make=fn)`
  (`vidpipe.artifacts`). Keys are `<stage>` or `<stage>/<unit>`, e.g. `narration/en/shot_03`.
  `ArtifactStore.forget(key_prefix)` drops records so the next run regenerates them (re-roll).
- `vidpipe run` prints `skipped` or `ran (n generated)` per stage.

## Gates, --auto and redo

The run pauses for approval after `script`, `storyboard` and `keyframes`. Change the set in
`vidpipe.yaml` (`gates: [storyboard]`, or `gates: []` for none; any stage name is valid).

- A pause is a normal outcome, not an error: `vidpipe run` prints the stages that ran and how to
  continue, and exits with code **3** (`0` = finished, `1` = error). In the library,
  `pipeline.run(...).paused_at` is the gate name.
- Approve with `vidpipe approve <project> <gate>` (no input needed: scripts and tests use this) and run
  again; or `vidpipe run --approve <gate>` (repeatable) to approve in advance; or answer the y/N
  question that appears when stdin and stdout are a terminal. `--auto` skips every gate.
- An approval (`build/approvals.json`) is bound to the *content* of the gated stage's output files. A
  hand edit, a regenerated stage or a `redo` that changes them asks again. A gate after the last stage
  of a `--until` run holds nothing back, so it does not pause.
- `vidpipe redo shot N [project]` re-rolls one shot: its keyframe and video get a new seed (the
  per-shot re-roll count is `rerolls` in `build/ledger.json`, the seed is recorded in each artifact),
  and the assemblies that use it are redone. Other shots, narration and music are untouched. Gates
  apply, so the new keyframe is shown at the keyframes gate before it is animated; `--auto` and
  `--approve` work as for `run`.

## Fit planning and `vidpipe plan`

Narration comes first, so its real length decides how much video is generated. For each shot the
fit planner (`vidpipe.fit`) writes `build/fit_plan.json`:

1. **One clip, speed first.** A clip is played at a speed between 1/1.3 and 1.3 so the shot lasts
   exactly as long as its narration (`speed` is a playback rate on the *video*: `0.88` is slower,
   so a 5.66 s line fits a 5 s clip; narration is never time-stretched). A clip that is clearly too
   long is sped up (up to 1.3x) and trimmed.
2. **Then continuation clips.** If one clip cannot cover the narration, it is cut into segments at
   natural boundaries (`vidpipe.segmentation`): sentence ends first, then clause marks (`, ; :`,
   Ethiopic `። ፣ ፤`), then a pause between words, each only where the coarser cut cannot make the
   pieces fit; fewest clips first, then the most natural cuts. Each segment is one clip; every clip
   after the first is a *continuation clip*, started from the previous clip's last frame. A run
   stops at fit-planning (before any GPU work) when a shot needs one: generating them is ticket 12.
3. **`visuals`** in `vidpipe.yaml`: `shared` (default: one clip set per shot, sized to the longer
   narration; the shorter language plays it slightly faster or trimmed), `per_language` (a clip set
   per language) or `primary_only` (the primary language's clips; another language that needs more
   than 1.3x slow-down is an error). Every render must stay within 90 s, else fit-planning fails and
   names the language.

`vidpipe plan PROJECT [--until STAGE] [--json]` is the dry run: it prints each shot's clips,
segments (with their time in the render), speed factors and continuation clips, and the estimated
GPU minutes (local providers) or dollars (hosted) per stage and overall. It calls no provider's
generation method and writes nothing. It needs a storyboard to know the shots
(`vidpipe run PROJECT --until storyboard`); narration durations are the real ones when narration
was generated for the current text, otherwise estimated from the script at the TTS provider's
declared `seconds_per_char` (marked `estimated`). Estimates are for a run from scratch.

Providers declare what their work costs as a `cost = CostModel(...)` class attribute: GPU minutes
(`gpu_minutes`, for providers with `uses_gpu = True`) or `dollars` (hosted), per `CALL` or per
`OUTPUT_SECOND`. The default is free. Conformance checks the declaration is consistent.

`fit_plan.json` per shot: `visual_sets` (`shared`, or one per language) each with `clips`
(`index`, `seconds` to generate, `continues` = index of the clip whose last frame it starts from,
`text` it covers) and `languages[lang]` with `visual_set`, `seconds` (shot length in that render =
narration length), `clips` (how that render plays each clip: `speed`, `source_s` used, `seconds`
shown) and `segments` (`text`, `start_s`/`end_s` in the render, `clip`: subtitle cues).
`render_seconds` has each language's total.

## The project bible

`bible.yaml` says who and where the story is about, and how it looks. Everything in it is optional.

```yaml
style:
  description: "Warm hand-painted storybook illustration, soft watercolour textures."
  reference: bible/style.png             # optional
characters:                              # the first one is the protagonist
  - id: aster
    name: Aster                          # how the prompt calls them (default: the id)
    description: "A ten-year-old girl: two black braids, indigo dress, yellow shawl."
    reference: bible/aster.png           # path relative to the project folder
locations:
  - id: village
    name: the highland village
    description: "Round stone houses with thatched roofs on green terraced slopes."
```

- Each entry needs a `description`, a `reference` picture (`.png`, `.jpg`, `.webp`), or both. Ids
  are lowercase letters, digits, `-` and `_`. Write descriptions in English.
- **Casting.** The storyboard stage tells its text provider the ids and names, and each shot gets
  `character` and `location` in `build/storyboard.json`. A shot with no `character` shows the
  protagonist; `"none"` means nobody (use it for object and scenery shots, or the model may draw the
  protagonist into them); no `location` means none. Hand-edit the storyboard to recast a shot.
  Adding, removing or renaming entries re-runs the storyboard (overwriting hand edits); rewording
  or replacing a picture redraws only the keyframes that use it.
- **What a keyframe receives** (`vidpipe.bible.keyframe_brief`): the pictures of the shot's
  character, then its location, then the style, as many as the keyframer accepts (two for the default
  model). The prompt is the shot's `visual` plus a sentence per entry: "image N" for an entry whose
  picture was passed, its description otherwise. A keyframer that takes no pictures gets
  descriptions only, so give every entry one. The style description is always included.
- Each keyframe's ledger record lists the prompt, the pictures (with content hashes), the seed and
  the settings it was drawn with.

**Making reference pictures.** Supply them as files; the pipeline does not generate them. A character
sheet or an empty view of a place can be drawn with the keyframer itself, about 10 s each (run this
in the project folder):

```python
from pathlib import Path

from vidpipe.contracts import KeyframeRequest
from vidpipe.providers.comfy_keyframer import ComfyKeyframer

keyframer = ComfyKeyframer()
keyframer.generate(
    KeyframeRequest(
        prompt="Character reference sheet of one girl ... front view, side view and face, plain "
        "light background. Warm hand-painted storybook illustration.",
        width=1280,
        height=720,
        seed=1,
        output_path=Path("bible/aster.png"),
    )
)
keyframer.release()  # free ComfyUI's memory
```

There is no negative prompt: describe what should be in the picture. The sample project ships a
placeholder protagonist (`examples/sample/bible/protagonist.jpg`) made this way.

## Keyframes on ComfyUI

`comfyui-keyframer` draws each shot with FLUX.2 [klein] 4B on a running ComfyUI
([ADR 0001](docs/adr/0001-keyframe-model.md)). vidpipe does not install or manage ComfyUI.

| Needed | Pinned |
|---|---|
| ComfyUI | 0.46.3 |
| Custom nodes | none |
| `diffusion_models/` | `flux-2-klein-4b-fp8.safetensors` |
| `text_encoders/` | `qwen_3_4b.safetensors` |
| `vae/` | `flux2-vae.safetensors` |

```yaml
width: 832          # multiples of 16, 256-1280 a side, at most 921600 pixels (1280x720)
height: 480
comfyui:
  url: http://127.0.0.1:8188     # the default
providers:
  keyframes: comfyui-keyframer
  # keyframes:
  #   name: comfyui-keyframer
  #   options: {settings: {reference_megapixels: 0.25}, retries: 2, timeout_s: 600}
```

- Options: `workflow` (a bundled model's name or a mapping file in the project), `settings` (the
  mapping's fields: `reference_megapixels` 0.5, `steps`), `url` (overrides `comfyui.url`), `retries`,
  `timeout_s`, `poll_s`. Changing `workflow` content or `settings` redraws; `url`, `retries`,
  `timeout_s` and `poll_s` do not.
- Jobs run one at a time. After the stage (also a failed one) ComfyUI is asked to unload its models.
- **Failures.** A job that errors, times out, disappears or saves nothing is retried up to twice with
  new seeds. After an out-of-memory error, memory is freed and one step-down from the mapping is
  applied (reference size 0.5 → 0.25 MP; without references, the next smaller size), with a new seed;
  running out of memory again fails the stage. A rejected workflow (missing model), an unreachable
  server or a job cancelled in ComfyUI fails at once. Finished shots are kept, so the next run
  resumes after them. Ctrl+C removes the running job from ComfyUI's queue.
- The artifact record says what happened: `fallback` (retries and step-down in words),
  `data.seed` (the seed that drew it), `data.attempts`, `data.settings`, `gpu_seconds`.
- On an RTX 4060 Laptop 8 GB an 832x480 keyframe takes about 4.5 s without a reference, 6.5 s with
  one and 9-12 s with two; `plan` assumes 0.11 GPU minutes each.
- Look at the keyframes at the gate: the model sometimes draws a character twice or drifts in small
  details. `vidpipe redo shot N` draws that shot again with a new seed.

Samples from real runs: [the sample project](docs/assets/keyframes-sample-project.jpg) (left: the
reference character in a place described in words; middle: `character: none`; right: a cup of coffee
that also received the protagonist's picture by default, which the model left out) and
[a two-reference run](docs/assets/keyframes-two-references.jpg) (top: the protagonist and location
pictures and a shot drawn from both; bottom: a shot before and after `redo`, and a two-reference
shot showing the duplicated-character defect).

## Music on ComfyUI

Set `providers.music` in `vidpipe.yaml` to generate an instrumental score with ACE-Step 1.5 Turbo.
The bundled workflow uses ComfyUI 0.46.3 core nodes and
`models/checkpoints/ace_step_1.5_turbo_aio.safetensors`. The project configuration selects the
provider and can override its tempo and key.

```yaml
providers:
  music:
    name: comfyui-music
    options:
      settings: {bpm: 90, keyscale: E minor}
```

`vidpipe run PROJECT --until music` writes `build/music/music.flac` and indexes it in
`build/music.json`. The soundtrack covers the longest language render, rounded up to a whole
second. Assembly trims the same score to each render and ducks it under the narration. The ledger
records the measured duration, ComfyUI execution time and any retry. On out-of-memory, the
bundled workflow retries with smaller decode tiles and the requested duration intact.

For a hosted ComfyUI instance with the same checkpoint, set `options.url` on the music provider to
the instance's address. This is a manual switch. To use another music backend, register a
`MusicProvider` and select it by name in the same YAML field. The sample selects `fake-music`
for GPU-free runs.

The separate `SongProvider.sing(SongRequest(...))` contract takes lyrics and a vocal language and
returns a mixed audio file. `fake-song` returns a deterministic WAV tone for conformance tests.
The project stage graph uses the instrumental music contract for assembly.

## Image-to-video on ComfyUI

Set `providers.video` to `comfyui-i2v` to animate each keyframe with Wan 2.2 TI2V 5B
Q5_K_M. The provider uses the fit plan's duration and the storyboard's motion
(`pan`, `push_in`, or `ambient`). It saves H.264 MP4 clips at 24 fps, rounded up
to the next whole frame, with a default size of 640x352. Set `VIDPIPE_FFMPEG_DIR` or put `ffprobe` on PATH
so vidpipe can verify each clip's duration before recording the artifact.

| Needed | Pinned |
|---|---|
| ComfyUI | 0.46.3 |
| ComfyUI-GGUF | `6ea2651e7df66d7585f6ffee804b20e92fb38b8a`, gguf 0.19.0 |
| `unet/` | `Wan2.2-TI2V-5B-Q5_K_M.gguf` |
| `text_encoders/` | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` |
| `vae/` | `wan2.2_vae.safetensors` |

```yaml
providers:
  video: comfyui-i2v
  # For a larger output:
  # video: {name: comfyui-i2v, options: {settings: {width: 832, height: 480}}}
```

The video size is set by the workflow, independently of the keyframe and
assembly dimensions. Jobs run sequentially. If ComfyUI runs out of memory at
the default size, the workflow retries once at 512x288 and keeps the planned
duration. The ledger records each clip's measured duration and ComfyUI
execution time, including failed attempts that preceded success. At 640x352
on an RTX 4060 Laptop GPU with 8 GB VRAM, the three-shot run took about 37
seconds of ComfyUI execution per second of video.

With the models installed and ComfyUI idle, run the video integration tests
with `uv run pytest -m integration -k "comfyui-i2v or wan_animates"`. The
pipeline test also uses the FLUX keyframe models listed above.

## Adding a ComfyUI model or provider

**Another model for an existing provider needs no Python:** export the workflow in API format, write
a mapping file next to it ([format](workflows/README.md#mapping-files)), and select it:

```yaml
providers:
  keyframes: {name: comfyui-keyframer, options: {workflow: workflows/my_model.mapping.yaml}}
```

`vidpipe plan` checks that every mapped node input exists, and takes capabilities and cost from the
mapping. A workflow shipped with vidpipe goes in `workflows/` and is selected by name.

**A new workflow-backed contract** needs a small provider class on
`vidpipe.comfy.provider.ComfyProvider`, which supplies options, URL handling, fingerprinting,
uploads, retries, the step-down, cancellation and memory release:

1. Subclass `ComfyProvider[<Capabilities>]` and the contract class; set `name`, `default_workflow`
   and `required_fields` (values every workflow variant must accept).
2. `declare_capabilities(model)`: usually `Capabilities.model_validate(model.spec.capabilities)`.
3. In the contract method: refuse what the capabilities do not allow (`UnsupportedRequest`), call
   `self.run_workflow(values, seed=..., images=[...], extras=request.extras)`, then
   `self.save_output(outcome, request.output_path)`, and return the result with
   `record=self.record(outcome, images=len(images))` (add a `record: GenerationRecord` field to the
   result model if it has none).
4. In the stage, call the provider through `_generate(...)` and return `_recorded(path,
   result.record, seed=seed)` (`vidpipe.stages`), so retries and GPU time reach the ledger.
5. Register it and give it a conformance test against the fake server (`tests/fake_comfyui.py`; add
   a writer to `WRITERS` for a new output node).

## Assembly, ducking and subtitles

`vidpipe run` ends with the assembly stage: for each language it writes `out/<output_name>_<lang>.mp4`
(`demo_en.mp4`, `demo_am.mp4`) and the sidecar `out/<output_name>_<lang>.srt`, and each render stays
within the 90 s limit (fit-planning refuses longer plans, and assembly checks again).

- **Video.** The clips of each shot play back to back at the speeds in `fit_plan.json`
  (`languages[lang].clips`: `speed`, `source_s`, `seconds`), then the shot is padded (last frame) or
  cut to exactly its narration's length. A shot with several clips (continuation clips, ticket 12) is
  handled the same way; today only clip 0 is generated.
- **Audio.** The shots' narration is joined, and the music sits under it at `mix.music_level` and is
  pushed down by a sidechain compressor keyed on the narration (`mix.duck_ratio`; threshold -30 dB,
  attack 20 ms, release 400 ms), so the music drops while someone speaks and swells back in the gaps.
- **Subtitles.** One cue per fit-plan segment (`segments[].text/start_s/end_s`, offset to the shot's
  place in the render). The SRT is written whether or not it is burned in; `subtitles.burn_in: false`
  keeps only the sidecar. Burning uses ffmpeg's `subtitles` filter (libass) with the fonts folder given
  as `fontsdir`; the filter text escapes Windows drive colons and any `' [ ] , ;` in paths
  (`vidpipe.subtitles.escape_filter_value`).

```yaml
subtitles:
  burn_in: true
  fonts_dir: fonts                   # relative to the project dir (or absolute). Default: ./fonts if
                                     # it exists, else the fonts bundled with vidpipe (assets/fonts)
  fonts: {am: Noto Sans Ethiopic}    # font family per language; others use the system default font
  font_size: 20                      # libass units: the video's height is 288, so it scales with it
mix:
  music_level: 0.4
  duck_ratio: 8
```

**Fonts.** Noto Sans Ethiopic (Regular and Bold, SIL OFL 1.1) is bundled in `assets/fonts/` with its
licence (`OFL.txt`); the licence allows redistributing the unmodified fonts. `vidpipe plan` (and so
`run`) reports a missing fonts folder, or a folder without the font a language needs, before anything
is generated; with `burn_in: false` no font is needed. Add a language by listing its font family
under `subtitles.fonts` and putting the font file in the fonts folder.

**ffmpeg.** Assembly needs `ffmpeg` and `ffprobe` with libass (the `subtitles` filter) and
`sidechaincompress`. Set `VIDPIPE_FFMPEG_DIR` for a portable build or use tools already on `PATH`.
See the [setup guide](docs/setup.md) for provider prerequisites and `vidpipe doctor`. The assembler
interface is `Assembler.problems()` and `Assembler.assemble(AssemblyJob)` (`vidpipe.assembly`). The
job carries the shots per language (`ShotSegment` with narration, length and `ClipPlay` list), the
music, a `SubtitleTrack` and the `MixSettings`.

## Development

- `uv run pytest` runs the fast suite on fake providers. Two seams only: the pipeline run through
  the CLI/library (`tests/test_pipeline.py`, `tests/test_resume.py`) and the per-contract provider conformance suite
  (`tests/conformance/`). ComfyUI providers are tested against an in-process fake server
  (`tests/fake_comfyui.py`, fixture `comfy`); `uv run pytest -m integration -k comfy` runs them on a
  real ComfyUI at 127.0.0.1:8188 with the models above. With the ACE-Step checkpoint installed,
  `uv run pytest -m integration -k 'comfyui_music or comfyui-music'` runs just the music tests,
  including a 90-second score.
- Tests that need real `ffmpeg`/`ffprobe` carry `@pytest.mark.needs_ffmpeg`: they skip cleanly when the
  binaries are absent and run automatically once they are on `PATH`.
- Real-provider tests (ComfyUI, CLIs, edge-tts) carry `@pytest.mark.integration` and only run with
  `uv run pytest -m integration`. A registered provider with `fake = False` is collected into the
  conformance suite with that marker automatically.
- `uv run ruff check . && uv run ruff format --check . && uv run pyright`

### Narration (edge-tts)

`edge-tts` needs network. Configure it per project, with per-language voices:

```yaml
providers:
  narration:
    name: edge-tts
    options:
      voices: {am: am-ET-MekdesNeural}   # defaults: en-US-AriaNeural, am-ET-AmehaNeural
    fallback: [mms-tts]                  # declared only; MMS-TTS is not implemented yet
```

Each narration clip's real length is `duration_s` in `build/narration.json`, read from the MP3.

### Adding a provider

1. Subclass the contract class for its kind in `vidpipe.contracts` (`TextProvider`,
   `TranslationProvider`, `TTSProvider`, `KeyframerProvider`, `ImageToVideoProvider`,
   `MusicProvider`, `SongProvider`), set `name` and `capabilities`, and implement the one method.
2. Register it with `@register` (`vidpipe.registry`), importing the module from
   `vidpipe/providers/__init__.py`, or expose the class through a `vidpipe.providers` entry point.
3. If it costs GPU time or money, declare `cost = CostModel(...)` (and `uses_gpu = True` for local
   GPU work); a TTS provider also sets `capabilities.seconds_per_char`. Optional hooks:
   `attach(ProjectContext)` (project folder, `comfyui.url`), `release()` (called after the stage),
   `unhashed_options` (options that must not regenerate artifacts). Raise `GenerationError` when an
   asset cannot be made.
4. Select it per stage in `vidpipe.yaml` (`providers: {narration: my-tts}`, or
   `{name: my-tts, options: {...}}` to pass constructor options).
5. It is picked up by `tests/conformance/test_providers.py` automatically and must pass the shared suite.

### Text providers (script, storyboard)

`script` and `storyboard` use CLI text providers: `gemini-cli`, `claude-cli`, `codex-cli` (each also
takes `options: {model:, timeout_s:, command:}`). Each CLI runs non-interactively in an empty
temporary directory with agent tools disabled; its reply is checked against the stage's Pydantic
model and re-prompted with the error up to twice. Check each vendor's current terms for automated
CLI use, and log in to each CLI yourself beforehand (vidpipe never handles credentials).

A stage can list a fallback chain; the next provider is tried on failure, rate limit or exhausted
re-prompts (default for `script` and `storyboard`: Gemini, then Claude):

```yaml
providers:
  script: [gemini-cli, claude-cli]          # or [{name: gemini-cli, options: {model: ...}}, codex-cli]
  storyboard: claude-cli
```

Tests drive the adapters through fake `gemini`/`claude`/`codex` executables on PATH
(`tests/fake_cli.py`, fixture `fake_clis`); `fake-text` keeps the offline pipeline fast. To run the
real CLIs through the conformance suite: `uv run pytest -m integration -k text`. When a chain falls back,
the artifact record in `build/ledger.json` says which provider failed and which answered.

### Translation (English to Amharic) and the back-translation check

`translation` is done by text providers through the same chain as `script` (default: Gemini CLI, then
Claude CLI), or by a registered translation provider such as `fake-translation`:

```yaml
languages: [en, am]          # the first language is the script's; the others are translated
providers:
  translation: [gemini-cli, claude-cli]    # default; `translation: claude-cli` also works
```

The script goes out as numbered lines and comes back as the same lines (ids preserved, so narration
and storyboard shots still line up). A reply that loses, invents or renumbers a line, or leaves a
line without Ge'ez script, is re-prompted. Output: `build/translation/<lang>.json`.

**Back-translation check.** After translating, a model translates the Amharic back to English
*without seeing the source*, then compares that with the source line by line. The result is
`build/translation/<lang>.review.json` (a `TranslationReview`) and the ledger artifact
`translation/<lang>/review`:

```json
{"language": "am", "source_language": "en", "translator": "gemini-cli", "checker": "claude-cli",
 "same_model": false,
 "lines": [{"id": 2, "status": "drift", "source": "...", "translation": "...",
            "back_translation": "...", "reason": "one-sentence reason"}]}
```

- The checker is never the translator when the chain has another provider: it is built from the other
  members only, and the check fails (the translation is kept; the next run resumes at the check) if
  they all fail. A chain with nobody else runs the check with the translator and records
  `"same_model": true`. Members are "the same model" when name and options are equal.
- Drifted lines are flagged `"status": "drift"` with a `reason`. They do not stop the run: `vidpipe run`
  prints each one (with the English, Amharic and back-translation) to stderr (also when the run pauses at a gate, and at the interactive prompt of any gate after `translation`), and the ledger record's
  `data.drifted` lists their ids. `vidpipe.translate.drift_flags(project)` returns them as `DriftFlag`s
  for a gate or report to show.
- The check re-runs if the translated file is hand-edited, so fixing a flagged line clears its flag.
  Translation providers that are not text chains (`fake-translation`) are not back-checked.

**Unicode.** Every file vidpipe writes is UTF-8 (raw Ge'ez, not `\u12xx` escapes) and the CLI text
adapters pipe UTF-8 both ways. A Windows console prints Ge'ez natively (needs a font with Ethiopic
glyphs, e.g. Nirmala UI); *redirected* output used to fall back to cp1252 and crash, so `vidpipe`
now switches stdout/stderr to UTF-8 when they are not already. Windows PowerShell 5.1 decodes piped
native output with `[Console]::OutputEncoding`: set it to UTF-8 if you pipe vidpipe's output there.
