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
