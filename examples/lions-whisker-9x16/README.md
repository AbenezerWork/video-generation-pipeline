# The Lion's Whisker (9x16)

The submitted film: an Ethiopian folk tale my parents told me, retold in our own words.
Almaz wins over her stepson Dawit the way she won over a lion: slowly. Sixteen shots,
Amharic narration (Addis AI, voice `am-hamen`), English subtitles burned in, an AI end
card, loudness normalised to -14 LUFS. Live-action look; four bible characters (Almaz,
Dawit, the elder, the lion) and three locations, described in words only.

Generated in portrait at 352x640 and rendered as exact 720x1280 (`output_size`): the
main submission. The landscape cut is [`../lions-whisker-16x9`](../lions-whisker-16x9),
from the same storyboard.

`storyboard.json` is the contract: every shot's narration (English and Amharic), keyframe
prompt, motion, cast, people count, movement and reason, plus the music settings. With it
present, no text model is called: the script, translation and storyboard come from it.
Edit one line or one visual and only that shot regenerates. The prompt rules come from
[`docs/research/model-strengths.md`](../../docs/research/model-strengths.md).

## Run it

Run from a copy outside the checkout, so `build/` and `out/` stay out of git:

```sh
cp -r examples/lions-whisker-9x16 ~/lions-whisker-9x16
export ADDIS_API_KEY=...        # Amharic voice; or set `narration: edge-tts` in vidpipe.yaml
uv run --locked vidpipe run ~/lions-whisker-9x16 --auto
```

Needs ComfyUI with the FLUX.2 klein, Wan 2.2 TI2V-5B and ACE-Step models (see the README),
and ffmpeg. About 2 GPU-minutes of keyframes and 40 to 45 of video on an RTX 4060 8 GB.
Without `ADDIS_API_KEY`, switch narration to `edge-tts`: the voice changes, and so may the
timing.
