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
