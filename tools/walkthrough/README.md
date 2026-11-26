# Walkthrough video generator

The generator builds the vidpipe walkthrough from recorded CLI output, model logs, ledger
snapshots, the final films, and an AI-voiced narration. It keeps the proof and all video
work local.

## Capture the storyboard edit

Run from the repository root with `ffmpeg` and `ffprobe` on `PATH` or
`VIDPIPE_FFMPEG_DIR` set. The capture checks that the landscape project finished, copies
it into a fresh scratch folder, and omits run state, locks, prior `runs.jsonl` files and
`.env` files. The CLI runs with ComfyUI transport disabled and `ADDIS_API_KEY` removed
from its environment. The English voice still uses Edge TTS through the configured
`addis-ai` provider.

```sh
uv sync --locked --all-extras
uv run --locked python tools/walkthrough/capture.py --work SCRATCH/first --out SCRATCH/first/capture --line "Be patient with the boy as you were with the lion."
uv run --locked python tools/walkthrough/capture.py --work SCRATCH/retry --out SCRATCH/retry/capture
```

Each capture first runs the project unchanged, then edits the English narration of shot
15 in the root `storyboard.json` and runs again. Both runs use the same CLI entry point
as `uv run --locked vidpipe run . --auto`. The evidence includes the unified diff, the
full CLI output, a before/after ledger and fit plan, per-file SHA-256 hashes, and the
model-call lines from each run.

The first capture is expected to exit nonzero after writing its evidence. On
26 November 2026 the shorter line reduced the measured narration from 3.528 to 3.336
seconds and changed the requested shared video from 3.75 to 3.50 seconds. The guard
blocked the resulting ComfyUI upload before any network request.

The second capture swapped “boy” for “child.” The measured narration was 3.600 seconds
and the video stayed at 3.75 seconds. The unchanged rerun skipped all ten stages, and the
edit made one successful Edge TTS call and took 49.4 seconds. Five of 73 ledger records
changed, namely `script`, `narration/en/shot_15`, `fit_plan`, `assembly/en` and
`assembly/am`. The runner materializes the primary-language script from the storyboard.
Both outputs use English subtitles, so this text change affected both assemblies.
Keyframes, motion clips, the score and all Amharic voice clips kept their file hashes.
Edge timing may vary between runs, so check the evidence before reusing the spoken claims.

## Build

```sh
uv run --with playwright playwright install chromium
uv run --locked --with playwright python tools/walkthrough/build.py --capture SCRATCH/retry/capture --first-attempt SCRATCH/first/capture --out OUT
```

The generator renders the standalone beats first. For the film beat it reads the Amharic
cuts in `~/.t3/vidpipe-demos/lions-whisker-final-{16x9,9x16}/out/`. It checks for both
files and finished run state every minute for up to 90 minutes.

`build.py` writes a 1920×1080 H.264/AAC walkthrough at 30 fps, a sidecar SRT matching its
burned-in captions, and a 6×5 JPEG frame sheet. It uses two-pass loudness normalization
to target −16 LUFS and caps the walkthrough at five minutes. Speech and rendered frames
are cached in `OUT/work` or the path passed to `--work`. The title identifies the
narration as an AI voice. Pass `--cached-speech` to rebuild from an existing speech
cache without contacting Edge TTS. Change the spoken text in `narration.md` and update
any matching frame cues in `build.py`.
