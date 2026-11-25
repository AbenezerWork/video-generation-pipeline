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
  prints each one (with the English, Amharic and back-translation) to stderr, and the ledger record's
  `data.drifted` lists their ids. `vidpipe.translate.drift_flags(project)` returns them as `DriftFlag`s
  for a gate or report to show.
- The check re-runs if the translated file is hand-edited, so fixing a flagged line clears its flag.
  Translation providers that are not text chains (`fake-translation`) are not back-checked.

**Unicode.** Every file vidpipe writes is UTF-8 (raw Ge'ez, not `\u12xx` escapes) and the CLI text
adapters pipe UTF-8 both ways. A Windows console prints Ge'ez natively (needs a font with Ethiopic
glyphs, e.g. Nirmala UI); *redirected* output used to fall back to cp1252 and crash, so `vidpipe`
now switches stdout/stderr to UTF-8 when they are not already. Windows PowerShell 5.1 decodes piped
native output with `[Console]::OutputEncoding`: set it to UTF-8 if you pipe vidpipe's output there.
