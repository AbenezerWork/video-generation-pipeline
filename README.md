<img src="assets/icon.svg" width="64" height="64" alt="">

# vidpipe

A provider-pluggable studio pipeline for short video. See `.scratch/vidpipe/spec.md`.

```
uv sync
uv run vidpipe plan examples/sample          # resolve providers, check capabilities
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
  `fingerprint()` (name and options), parameters and seed. A regenerated upstream file that comes out
  identical invalidates nothing downstream.
- Hand edits work: edit `build/script.json` (or a translation) and only the artifacts that read it are
  redone. An artifact whose own inputs are unchanged is never overwritten.
- A stage declares its inputs where it produces an artifact:
  `ctx.produce(key, inputs=Inputs(files=[...], values={...}), parameters={...}, seed=..., make=fn)`
  (`vidpipe.artifacts`). Keys are `<stage>` or `<stage>/<unit>`, e.g. `narration/en/shot_03`.
  `ArtifactStore.forget(key_prefix)` drops records so the next run regenerates them (re-roll).
- `vidpipe run` prints `skipped` or `ran (n generated)` per stage.

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
3. Select it per stage in `vidpipe.yaml` (`providers: {narration: my-tts}`, or
   `{name: my-tts, options: {...}}` to pass constructor options).
4. It is picked up by `tests/conformance/test_providers.py` automatically and must pass the shared suite.
