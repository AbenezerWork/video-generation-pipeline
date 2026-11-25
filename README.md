<img src="assets/icon.svg" width="64" height="64" alt="">

# vidpipe

A provider-pluggable studio pipeline for short video. See `.scratch/vidpipe/spec.md`.

```
uv sync
uv run vidpipe plan examples/sample          # resolve providers, fit plan and GPU/cost estimate; generates nothing
uv run vidpipe run examples/sample --until music   # everything except the ffmpeg render
uv run vidpipe run examples/sample           # full render (needs ffmpeg + ffprobe on PATH)
```

A project is a directory with `brief.md` and `vidpipe.yaml`; artifacts go to `build/`, renders to `out/`.

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

**ffmpeg.** Assembly needs `ffmpeg` and `ffprobe` on `PATH`, built with libass (the `subtitles`
filter) and with `sidechaincompress`; `vidpipe plan` says which is missing
(`FfmpegAssembler.problems()`, which the future `doctor` can call too). The assembler interface is
`Assembler.problems()` and `Assembler.assemble(AssemblyJob)` (`vidpipe.assembly`): the job carries per
language the shots (`ShotSegment`: narration, length, `ClipPlay` list), the music, a `SubtitleTrack`
and the `MixSettings`.

## Development

- `uv run pytest` runs the fast suite on fake providers. Two seams only: the pipeline run through
  the CLI/library (`tests/test_pipeline.py`, `tests/test_resume.py`) and the per-contract provider conformance suite
  (`tests/conformance/`).
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
   GPU work); a TTS provider also sets `capabilities.seconds_per_char`.
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
