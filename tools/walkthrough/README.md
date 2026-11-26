# Walkthrough video generator

The project walkthrough video (about 4 minutes, 1920x1080) is made from code here. Nothing is
recorded by hand: the terminal output, ledger records and UI screenshots come from a real run, and
the slides, narration, captions and edit are generated.

| File | What it does |
|---|---|
| `capture.py` | Runs the live regeneration demo on a scratch copy of a finished project and saves the evidence |
| `narration.md` | The narration script, one `## beat` per visual |
| `build.py` | Speaks the narration, renders the slides, times them to the words, and assembles the video |

## The demo `capture.py` runs

1. Copies `~/.t3/vidpipe-demos/lions-whisker-16x9` (or `--source`) to `--work`, without its
   `run.lock` and `run_state.json`. The source project is never written to.
2. Re-runs up to fit planning to refresh ledger records whose declared inputs changed with the code
   since the original run. It stops if the fit plan does not come out byte-identical, because the
   full run would then regenerate video on the GPU.
3. Runs `vidpipe run . --auto` unchanged. Every stage must report `skipped`.
4. Rewords Amharic line 15 in `build/translation/am.json`, the elder's advice, to a shorter phrasing
   with the same meaning, then runs `vidpipe run . --auto` again.
5. Saves the terminal output, the diff, `vidpipe plan`, the ledger records and the sha-256 of
   every artifact before and after (`evidence.json`), plus screenshots of `vidpipe ui` taken with
   Playwright on port 8777.

Measured on 26 Nov 2026: 4 of 73 ledger records changed (`translation/am/review`,
`narration/am/shot_15`, `fit_plan`, `assembly/am`) and the run took 45 s with 0 GPU seconds.
Keyframes, clips, the score and the English cut kept their hashes.

The edit needs network (Edge TTS, plus two Claude CLI calls for the back-translation check) but no
GPU. It works without a GPU only because the new line (3.31 s) still fits the shot's existing
3.75 s clip and keeps the render under the score's rounded-up length. A longer line would also
regenerate that shot's clip, and possibly the music.

## Build

From the repository root, with `ffmpeg` and `ffprobe` on `PATH` or `VIDPIPE_FFMPEG_DIR` set:

```
uv sync --locked --all-extras
uv run --with playwright python tools/walkthrough/capture.py --work SCRATCH/demo --out SCRATCH/capture
uv run --with playwright python tools/walkthrough/build.py --capture SCRATCH/capture --out OUT
```

Playwright needs a Chromium build (`uv run --with playwright playwright install chromium`).

`build.py` writes `OUT/walkthrough.mp4` (H.264/AAC, 30 fps, loudness normalised in two passes to
-16 LUFS with a -1.5 dBTP true peak), `OUT/walkthrough.srt` (the burned-in captions) and
`OUT/walkthrough_frames.jpg` (a 6x5 frame sheet). It fails if the video runs over five minutes.
Intermediate files go to `OUT/work` (or `--work`). Speech and rendered frames are cached there by
content, so a rebuild after a small change is quick.

The film clips come from the finished renders `lions-whisker-16x9/out/lions-whisker-16x9_am.mp4`
and `lions-whisker-9x16/out/lions-whisker-9x16_am.mp4` under `~/.t3/vidpipe-demos/`.

## How it works

- **Narration.** Each beat is spoken by Edge TTS (`en-US-AndrewNeural`, rate +10%) with word
  boundaries, so the build knows when each word is said. The title slide says the narration is an
  AI voice.
- **Visuals.** Slides are HTML and CSS screenshotted at 1920x1080 by Chromium. They use the UI's
  colour tokens and its bundled fonts (Mona Sans, JetBrains Mono), plus Noto Sans Ethiopic for
  Amharic. Terminal frames, code and ledger JSON are read from the captured files and the source
  tree, not typed in by hand.
- **Timing.** A beat's frames change on cue phrases in its narration (`Frame(png, cue="Make the
  pictures")`), timed by the word boundaries. A cue that is missing from the narration stops the
  build.
- **Captions.** Each beat is split at sentence and clause ends, wrapped at about 62 characters
  without ending a line on a short function word, and timed by matching written words to spoken
  ones. Captions are rendered as transparent PNGs and overlaid with ffmpeg.
- **Assembly.** Each beat becomes one MP4. Then come a stream-copy concat and a two-pass `loudnorm`.

To change the script, edit `narration.md`. If you remove a phrase that a frame cues on, update that
cue in `build.py`. The demo numbers spoken in `narration.md` (four of seventy-three, under a minute,
3.31 instead of 3.50) come from the capture. Check them against `evidence.json` after re-capturing.
