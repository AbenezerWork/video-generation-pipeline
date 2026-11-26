# Failure journal

What broke, what we tried, and what fixed it or what we do instead. Everything here
comes from the project's logs: [EXPERIMENTS.md](EXPERIMENTS.md), the ticket comments
under [`.scratch/`](.scratch/), the architecture audit, and the demo projects'
ledgers (which live outside the repository).

Status: **fixed** (the cause is gone), **worked around** (we avoid it), **open**
(still true). Entries below are grouped by area, so numbers are not in reading order.

## Index

| # | Blocker | Kind | Status |
|---|---|---|---|
| 1 | ffmpeg install through winget stalled | setup | worked around |
| 2 | Python on PATH was the Microsoft Store stub | setup | fixed |
| 3 | SSH push to GitHub failed | setup | worked around |
| 4 | Gemini CLI never logged in | provider | open |
| 5 | Claude five-hour limit during the first demo | quota | worked around |
| 6 | Coding agents stopped at their quotas mid-ticket | quota | worked around |
| 7 | Codex quota stopped a translation run | quota | worked around |
| 8 | PowerShell GPU wrapper aborted on stderr | tooling | fixed |
| 9 | Gate prompt on Windows when input is closed | tooling | fixed |
| 10 | Ge'ez output crashed redirected consoles | language | fixed |
| 11 | Music checkpoint not downloaded when needed | setup | fixed |
| 12 | Low host RAM and CPU text encoding | memory | worked around |
| 13 | Narration longer than one clip | pipeline | fixed |
| 14 | Script capped at 60 s | pipeline | fixed |
| 15 | Two runs at once could lose work | pipeline | fixed |
| 16 | A killed run still looked like it was running | pipeline | fixed |
| 17 | Server restart in the middle of a render | pipeline | worked around by resume |
| 18 | 640x352 is not 16:9 | format | fixed |
| 19 | Wan height cap allowed landscape only | format | fixed |
| 20 | Character changed between shots without a reference | model | worked around |
| 21 | Style text leaked into unrelated keyframes | model | fixed |
| 22 | Stylised look smeared and warped in motion | model | worked around |
| 23 | Rearing goats and cloned characters | model | worked around |
| 24 | First pan pushed in | model | fixed |
| 25 | Lion lost its mane, elder changed skin tone, stray people | model | worked around |
| 26 | Weak shots left in the finished films | model | open |
| 27 | Amharic drift: Coffee, Khalid line 12, Lion's Whisker line 7 | language | handled per line |
| 28 | Long Amharic subtitles, large in portrait | language | caption layout updated |
| 29 | No native-speaker check of the Amharic | language | open |
| 30 | `doctor` missed a missing Addis key | pipeline | open |
| 31 | A changed output file can be reused | pipeline | open |
| 32 | A partial run checks providers it will not use | pipeline | open |
| 33 | Second characters and clothing are missing from prompts | pipeline | fixed in v2 |
| 34 | Final mix far below platform loudness | audio | loudness fixed, portrait peak above target |
| 35 | Ledger loses the cost of replaced attempts | measurement | fixed for new runs |
| 36 | No AI marker in the MP4 metadata | disclosure | fixed and checked in both cuts |
| 37 | Real GPU out-of-memory recovery never exercised | memory | open |
| 38 | V2 motion prompt changed during the full render | process | adjusted after pilot checks |
| 39 | Storyboard export dropped fields used by the prompts | pipeline | fixed |

## Setup and tools

### 1. ffmpeg install through winget stalled

- **Broke:** the 264 MB full build stalled at 0 MB, crawled at about 7 to 35 KB/s
  from GitHub, restarted from zero after a truncated download, and finally failed with
  a network read timeout at 37 MB.
- **Tried:** waiting; the ffmpeg 4.4.1 bundled with Stremio, read-only, so tests
  could run.
- **Workaround:** Gyan's 9.1 essentials build (36.7 MB, sha256-checked, has libass),
  fetched with a resumable downloader and found through `VIDPIPE_FFMPEG_DIR`.
  `vidpipe doctor` now checks ffmpeg, ffprobe and the filters it needs.

### 2. Microsoft Store Python stub

- **Broke:** the `python` on PATH was a Store placeholder, not an interpreter.
- **Fix:** installed Python 3.12 and uv with winget.

### 3. SSH push failed

- **Broke:** pushing to GitHub over SSH failed on this machine.
- **Workaround:** switched the remote to HTTPS and authenticated with
  `gh auth setup-git`.

### 4. Gemini CLI never logged in

- **Broke:** the default text chain starts with `gemini-cli`, but it was never signed
  in. The challenge brief also says Gemini CLI has stopped serving free personal
  accounts, which we have not checked ourselves.
- **Tried:** the adapter is tested against a fake executable only.
- **Workaround:** every real project names its chain in `vidpipe.yaml` (Claude, then
  Codex).
- **Still open:** change the default chain, or verify Gemini against a real account.

### 8. PowerShell GPU wrapper aborted mid-run

- **Broke:** `run-gpu.ps1` sets `$ErrorActionPreference = 'Stop'`. Harmless warnings
  that ffmpeg and ComfyUI print to stderr killed the run.
- **Fix:** GPU work runs through `examples/coffee-origin/run_gpu.py`, which waits for
  a machine-wide GPU lock and an idle ComfyUI queue, or through `uv run vidpipe run`
  when nothing else uses the GPU. `run-gpu.ps1` now calls the Python wrapper.

### 9. Gate prompt on Windows with closed input

- **Broke:** on Windows `NUL` reports itself as a terminal, so a run started with
  input on `NUL` showed the interactive gate prompt and failed at end of file. This
  was found while building the UI.
- **Fix:** the UI starts runs with a closed pipe for input.

### 10. Ge'ez text crashed redirected output

- **Broke:** redirected output on Windows fell back to cp1252 and crashed on Amharic.
- **Fix:** `vidpipe` switches stdout and stderr to UTF-8 when they are not already.
  Every file it writes is UTF-8. Windows PowerShell 5.1 still needs
  `[Console]::OutputEncoding` set to UTF-8 when piping.

### 11. Music checkpoint missing at verification time

- **Broke:** the ACE-Step checkpoint (10 GB) was still queued behind another model
  when the music ticket was written, so real generation could not be checked.
- **Tried:** CPU tests with portable ffmpeg, a simulated out-of-memory retry.
- **Fix:** verified once the download finished and matched its SHA-256: 90 s of audio
  in 22.78 s.

## Quotas and limits

### 5. Claude's five-hour limit in the first demo

- **Broke:** `claude-cli` answered "You've hit your 5-hour limit" for both the script
  and the storyboard.
- **Fix that already existed:** the fallback chain moved to `codex-cli`. The ledger
  records the failure text and who answered, under `fallback`. After the quota reset,
  a one-line config change to `claude-cli` regenerated only the storyboard.

### 6. Coding agents stopped at their quotas

- **Broke:** Claude and Codex agents hit usage limits partway through tickets.
- **Workaround:** merged the committed but unmerged work by hand.

### 7. Codex quota stopped a translation run

- **Broke:** the Khalid translation used Codex only, and Codex was out of quota.
- **Fix:** translation moved to Claude: Opus 5.5 first, Sonnet 5.5 as fallback and
  back-checker.
- **Lesson:** every text stage needs at least two providers in its chain.

## Memory, GPU and speed

### 12. Low host RAM and the text encoder

- **Broke:** with about 4 GB of RAM free, keyframe jobs took 3 to 5 s longer. Moving
  the 8 GB text encoder to the CPU took 25 to 48 s per prompt and drove free RAM to
  zero.
- **Workaround:** leave the encoder on ComfyUI's own offload, keep other heavy
  programs closed, and free ComfyUI's memory after each stage.

### 37. Real out-of-memory recovery is untested

- **Open:** the retry and step-down rules pass against a fake ComfyUI server. No real
  GPU job has run out of memory, so the recovery path has never worked for real. The
  keyframe spike ran about 60 jobs and never triggered it.

### 38. V2 motion prompt changed during the full render

- **Broke:** the first v2 landscape pass put coloured bars in some clips. Shot 10
  A/B tests found that omitting the scene and asking shapes to stay steady could
  each trigger the bars. Commit `31b01f5` at 17:18 local records the revised prompt.
- **Cost:** the 26 Nov work spanned about 15:49 to 19:06 local. The two v2 landscape
  logs each report 16 generated clips, and the portrait log reports 16. ComfyUI
  logged about 44.42 GPU-min for the first landscape video pass alone. Its
  earliest 16-clip batch is inside a roughly 46-minute gap between retained ledger
  entries. See [COSTS.md](COSTS.md#v2-render-time) for the measured seconds and the
  limits on attributing them. The exact idle time and the cost of the prompt
  change alone cannot be recovered.
- **Decision:** settle the rules on two or three pilot shots before a full render.
  Then run both formats back to back unattended. An 8 to 12 shot version is a
  shorter option. At 10 shots with similar clip lengths, video time would fall
  by roughly a third (estimate).

## Pipeline

### 13. Narration longer than one clip

- **Broke:** the first real English line was 5.66 s; the video model's limit is 5 s.
  The first planner errored on real narration.
- **Fix:** the fit planner changes speed by up to 1.3x, and otherwise cuts the line at
  natural boundaries and adds a continuation clip from the previous last frame.

### 14. A hidden 60 s script cap

- **Broke:** the first Khalid script was 12 lines and 54 s, though the brief asked for
  16 lines and about 70 s. The prompt hard-coded "6 to 12 lines, under 60 seconds".
- **Fix:** the cap comes from the render limit (6 to 18 lines, under 90 s), and the
  brief's own line count is followed. The rerun wrote 16 lines.

### 15. Two runs could overwrite each other

- **Broke:** the architecture audit ran two runs on one project; each saved a ledger
  record and only the second survived. Only the demo wrapper held a lock.
- **Fix:** `run`, `redo` and `approve` take an OS file lock on `build/run.lock`. A
  second writer exits with a message naming the holder. The OS releases the lock when
  the process dies. Projects on network drives are unsupported.

### 16. A killed run looked alive

- **Broke:** the UI's stage rail kept spinning for a run whose process had died.
- **Fix:** reading the run state reports a `running` record with a dead process as
  `failed`, including the stage it was in. Related: Windows briefly refuses reads and
  renames while the UI holds a file, so the ledger and run-state writes retry.

### 17. Server restart in the middle of a render

- **Broke:** the Lion's Whisker 9:16 run was interrupted by a server restart after 2
  of 16 clips.
- **Fix:** ran the same command again. The 2 finished clips were reused and 14 were
  generated. In the ledger the third clip's ComfyUI time is 1.7 s against 134 to
  200 s for the others, most likely because ComfyUI still had that job's result
  cached. That cause is our reading, not something logged.

### 30. `doctor` missed a missing Addis key

- **Open:** one narration adapter serves both languages, so `doctor` checked only
  Edge TTS and said nothing about `ADDIS_API_KEY` (architecture audit). Proposed fix:
  choose a voice provider per language and let each declare what it needs.

### 31. A changed output file can be reused

- **Open:** the ledger reuses an artifact when its inputs match and its output files
  exist. It records each output's SHA-256 but does not check it on reuse. In the
  audit, a file replaced by different bytes of the same size was still reused. Hand
  edits are intentional here, but corruption would pass too. Only files written from
  `storyboard.json` are now hash-checked; media is not.
 
### 32. A partial run checks every provider

- **Open:** `plan --until brief` failed because the music provider was misconfigured,
  although music was not part of the run (architecture audit).
 
### 35. The ledger forgets replaced attempts

- **Broke:** the ledger keeps one record per artifact. When a keyframe is redrawn, the
  earlier attempt's GPU time disappears. The 12 keyframe re-rolls of Lion's Whisker
  16:9 are not in its totals.
- **Fix:** `<project>/runs.jsonl` appends one line per generation attempt, failures
  included, so replaced attempts stay on record from now on.
- **Older runs:** the server log recovers execution totals for part of the v2 run.
  It lacks the per-attempt timestamps and artifact IDs needed for a full
  reconstruction. See [COSTS.md](COSTS.md#v2-render-time).

### 39. Storyboard export dropped fields used by the prompts

- **Broke:** exporting to `storyboard.json` dropped `others`, `people` and
  `movement`. Importing that file could change the keyframe and motion prompts
  and invalidate the corresponding renders.
- **Fix:** keep all three fields in the editable contract, JSON Schema, export and
  import. The storyboard contract test round-trips the count and movement through
  the CLI.

## Format

### 18. 640x352 is not 16:9

- **Broke:** the video model needs both sides to be multiples of 32, and 360 is not
  one, so the Khalid cut was 1.82:1.
- **Fix:** `output_size` scales each clip to cover the delivery frame and crops it
  (a 2% side crop to 1280x720). Only assembly re-runs.

### 19. Wan was capped to landscape

- **Broke:** the workflow mapping capped height at 480, so portrait frames were
  refused, and its out-of-memory step-down sizes were landscape-only.
- **Fix:** the limit is now a pixel budget (832x480 worth) in either orientation, and
  step-down sizes turn with the frame (352x640 to 288x512).

## What the models got wrong

### 20. Characters changing between shots

- **Broke:** described only in words, a character came out as a different girl. Even
  with a reference, 1 of 10 shots drew her twice and two drifted to the wrong setting.
- **Workaround:** reference pictures where possible, setting cues in every prompt, the
  keyframe gate and `redo shot N`.

### 21. Style text turned into scene content

- **Broke:** a style description that mentioned coffee brewing put inset brewing
  images into unrelated keyframes.
- **Fix:** the style holds only the look; actions belong to shots.

### 22. Stylised art animates badly

- **Broke:** in stylised trials the video model smeared and warped.
- **Workaround:** live-action is the default look.

### 23. Rearing goats and cloned characters

- **Broke:** in a live-action rerun, goats reared up like people and secondary
  characters copied the protagonist's face and clothes.
- **Fix:** storyboard rules sent with every request, plus a line in each keyframe
  prompt. Goats and extras came out right. One shot still drew the fire inside the
  roasting pan (**open**, a keyframe-model limit).

### 24. A pan that pushed in

- **Broke:** the first Wan pan also zoomed in strongly.
- **Fix:** tighter prompt wording; same keyframe and seed then gave a sideways move.

### 25. Lion's Whisker keyframe problems

Found at the keyframe gate, before any video GPU time:

| Problem | Likely cause | Fix |
|---|---|---|
| The lion lost its mane where Almaz is the main character | a shot passes only its main character's description | named "the large black-maned male lion" in shots 11 to 13 |
| The elder came out lighter-skinned in two shots | his description gave no skin tone | added "deep brown skin" to the bible |
| Stray figures behind Almaz, and the elder twice in one shot | the image model fills empty space with people | "alone, the only person in the shot" in solo shots |
| The storyboard dressed Dawit differently from the bible | the storyboard model sees names, not descriptions | edited the storyboard |

12 re-rolls at about 7 s each. Portrait needed the same fix in two more shots (an
extra man, and a second woman).

### 26. Weak shots that stayed in

- **Khalid:** unnaturally wide eyes (shot 8), an over-tight push-in (shot 9),
  interiors drawn as exteriors (shots 11 to 14).
- **Lion's Whisker:** green streaks beside the bowl (shot 4) and near the whisker
  (shot 13) in 16:9, Almaz in a different top in shot 16, small variation in the
  elder's skin tone.
- Each can be redrawn with `vidpipe redo shot N`. They were judged from still frames.

## Language

### 27. Amharic drift flags

| Film | Line | Problem | Outcome |
|---|---|---|---|
| Coffee Highlands | 3, 4 | berries read back as unspecified fruits; path as road | corrected by hand before narration; smaller differences still flagged afterwards |
| Khalid | 12 | seeds read back as fruits (ፍሬ) | kept: ፍሬ covers both |
| Lion's Whisker | 7 | "nodded" (ራሳቸውን ነቀነቁ) can mean "shook his head" | rewritten as "agreed" (ተስማሙ); re-check passed |
| Lion's Whisker | 10 | "resting" read back as "asleep" | kept |

### 28. Subtitle length and size

- **Broke:** Amharic lines run long. In the v1 9:16 cut the text is sized from
  the frame height and wraps to 2 to 4 lines over the lower half of the picture.
- **Fix:** size from the shorter side of the frame, at most two lines per cue with long
  lines split over time, and more bottom room in portrait.
- **Check:** the final portrait Amharic cut has paged English captions. A phone
  check is still open.

### 29. No native-speaker check

- **Open:** the Amharic narration, subtitles and end card were checked by a second
  model only.

### 33. The models are told too little about the cast

- **Broke:** the storyboard saw only character names, and the keyframe prompt
  described only the main character. This contributed to the wardrobe and mane
  problems above.
- **Fix:** v2 gives the storyboard the cast descriptions and repeats the relevant
  secondary descriptions in the keyframe prompt. The rule and remaining drift are
  recorded in [EXPERIMENTS.md](EXPERIMENTS.md#25-give-each-model-the-details-it-needs-26-nov).

## Delivery

### 34. The mix is much quieter than platforms expect

- **Broke:** measured with ffmpeg `ebur128` on 26 November on the earlier cuts:
  Lion's Whisker Amharic **-24.4 LUFS** (true peak -8.0 dBFS), English -20.9 LUFS;
  Khalid Amharic -24.2, English -20.6. The brief's guide is about -14 LUFS.
- **Cause:** assembly ducked and limited the mix but did not normalise loudness.
- **Fix:** a two-pass `loudnorm` to `mix.loudness_lufs` (default -14 LUFS, true peak
  -1 dBTP). Assembly uses no GPU.
- **Check:** `ebur128=peak=true` measured -14.0 LUFS on both final Amharic MP4s.
  Encoded true peak was -1.0 dBTP in landscape and -0.6 dBTP in portrait.
  Portrait is 0.4 dB above the target.

### 36. No AI marker inside the file

- **Broke:** `ffprobe` on the earlier MP4s showed only the container brand and the
  encoder tag. The end card carried the disclosure.
- **Fix:** assembly writes a title and an "AI-generated" comment into each MP4.
- **Check:** `ffprobe` found the title, comment and description on both final
  Amharic MP4s. See [ETHICS.md](ETHICS.md).
