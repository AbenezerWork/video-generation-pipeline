# The Coffee Highlands

This project tells a coffee-origin legend in English and Amharic. The two renders
share FLUX.2 keyframes, Wan 2.2 motion and an ACE-Step instrumental score. Edge TTS
supplies the two narrations. Vidpipe mixes each narration with the score and burns
in the matching subtitles. It also writes an SRT sidecar for each language.

## Run on Windows

Use the pinned ComfyUI workflows and model files in the [setup guide](../../docs/setup.md).
The project uses Claude Code and Codex CLI for script and storyboard, with fallback
to Codex if Claude is rate limited. Translation uses Codex with `gpt-6.2-astra` and
the back-translation check uses `gpt-6.2-sol`. Use existing sessions with access to
these models, or set `providers` to the available text CLI models. Use two distinct
models for translation and review. The demo uses 512×288 at 24 fps for the 8 GB GPU.

From the repository root in PowerShell, prepare the project outside the checkout.
Copy the source files once so the same project can resume across terminals and checkouts.

```powershell
uv sync --locked
$demo = Join-Path $env:USERPROFILE '.t3\vidpipe-demos\coffee-origin'
$env:VIDPIPE_FFMPEG_DIR = Join-Path $env:USERPROFILE '.t3\vidpipe-deps\ffmpeg\ffmpeg-9.1-essentials_build\bin'
New-Item -ItemType Directory -Force $demo | Out-Null
Copy-Item examples/coffee-origin/brief.md,examples/coffee-origin/vidpipe.yaml,examples/coffee-origin/bible.yaml $demo
uv run --locked vidpipe doctor $demo
```

The shared download tracker is at `%USERPROFILE%\.t3\vidpipe-deps\status.json`.
If ACE-Step is still downloading there, continue through video with the installed
models. `doctor` will report the music checkpoint as missing until it is visible
to ComfyUI. Reuse the tracked download. The `run-gpu.ps1` commands below wait for
the machine-wide GPU lock (`%USERPROFILE%\.t3\vidpipe-deps\integration-gpu.lock`,
shared with the other integration runs and with other projects) and for ComfyUI's
queue to be idle before starting. The GPU lock is the same OS file lock vidpipe
takes per project (`filelock`, see `run_gpu.py`), so a killed run releases both.
Invoke them from the repository root. A second command on the same project while
one is running is refused with `a run is in progress`. Keep the project on a local
disk; network drives are unsupported. If Windows PowerShell blocks the local script,
run `Set-ExecutionPolicy -Scope Process RemoteSigned -Force` in that session.

Generate the text first and inspect `build/translation/am.review.json`. If the
review flags a mistranslation, edit the corresponding `text` in
`build/translation/am.json` before generating narration. Keep the line IDs. The
next run preserves the edit and updates the review.

```powershell
uv run --locked vidpipe run $demo --until storyboard --auto
```

```powershell
uv run --locked vidpipe run $demo --until fit-planning --auto
uv run --locked vidpipe plan $demo --until video
& ./examples/coffee-origin/run-gpu.ps1 -VidpipeArgs @('run', $demo, '--until', 'video', '--auto')
```

`build/ledger.json` records each completed artifact as it becomes available. If the
video run stops early, repeat the same command with the same project. Wait for the
ACE-Step checkpoint to be verified and visible to `doctor` before starting the full
run. The GPU lock is free between these commands, including while the download runs.

```powershell
uv run --locked vidpipe doctor $demo
& ./examples/coffee-origin/run-gpu.ps1 -VidpipeArgs @('run', $demo, '--auto')
```

The deliverables are `$demo\out\demo_en.mp4`, `$demo\out\demo_am.mp4` and their
matching `.srt` files. The first full run should reuse the video, then generate the
instrumental score and assemble both exports.

## Verify

Use the following checks after assembly. Each MP4 should report H.264 video and a
mixed AAC soundtrack, be at most 90 seconds and decode without errors. Play both
files to check the motion, narration, instrumental music and burned-in subtitles.
Check that the SRTs contain cues in the matching language and that the Amharic
burn-in shows Ethiopic glyphs.

```powershell
foreach ($language in 'en', 'am') {
    $mp4 = Join-Path $demo "out\demo_$language.mp4"
    & "$env:VIDPIPE_FFMPEG_DIR\ffprobe.exe" -v error -show_streams -show_format -of json $mp4
    & "$env:VIDPIPE_FFMPEG_DIR\ffmpeg.exe" -v error -xerror -i $mp4 -f null NUL
}
```

On another run of the same full command, compare the hash of `build/ledger.json`
and both exports before and after. Every stage should report `skipped`. To verify
a re-roll, keep a copy of the ledger and run the command below. Compare the seed
and output hash for shot 2's keyframe and video with their previous values. Check
that other shots, narration and music retain their hashes, and that both assemblies
run again. Repeat the media checks on the new exports.

```powershell
& ./examples/coffee-origin/run-gpu.ps1 -VidpipeArgs @('redo', 'shot', '2', $demo, '--auto')
```

To verify a text provider swap, make a sibling project with a copy of the text
artifacts. In the sibling's `vidpipe.yaml`, change only `providers.storyboard` to
an available real CLI that differs from the one that answered the original. Run
the storyboard stage against the copy. Check that the ledger records the new
provider for the regenerated storyboard and that the script and translation input
and output hashes match the original.

```powershell
$swap = "$demo-provider-swap"
New-Item -ItemType Directory -Force $swap, "$swap/build" | Out-Null
Copy-Item $demo/brief.md,$demo/vidpipe.yaml,$demo/bible.yaml $swap
Copy-Item $demo/build/brief.json,$demo/build/script.json,$demo/build/translation,$demo/build/storyboard.json,$demo/build/ledger.json "$swap/build" -Recurse
# Edit $swap/vidpipe.yaml here, then run:
uv run --locked vidpipe run $swap --until storyboard --auto
```
