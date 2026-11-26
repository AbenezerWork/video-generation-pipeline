# Design: *The Lion's Whisker*

The submitted film: an Ethiopian folk tale narrated in Amharic, in 16:9 and 9:16.

| Cut | Frame | Length | File in the demo project |
|---|---|---|---|
| Horizontal | 1280x720 | 75.5 s (70.5 s of story, 5 s end card) | `lions-whisker-16x9/out/lions-whisker-16x9_am.mp4` |
| Vertical | 720x1280 | 75.5 s | `lions-whisker-9x16/out/lions-whisker-9x16_am.mp4` |

Both are H.264 at 24 fps with AAC audio, burned-in subtitles, a sidecar `.srt` and an
AI end card. They share one script, narration and score; only the pictures differ.
The demo projects live outside this repository, in
`%USERPROFILE%\.t3\vidpipe-demos\`.
The cuts described here have Amharic subtitles. English subtitles on the Amharic
render come from `subtitles.text_language: en`, and the mix is normalised to
-14 LUFS by `mix.loudness_lufs`; both need a re-assembly of the delivered files.

**Before re-running the film's existing projects with the new code,** run
`vidpipe export-storyboard <project>`. The storyboard prompt now also asks for a shot
reason, so without a `storyboard.json` a run would write a new storyboard over the
hand-edited one and redraw every shot. Check `vidpipe plan` before running.


## 1. Audience and intent

> **DRAFT. The owner must confirm or rewrite this.** It was written on 26 November
> 2026, after the film was generated, from the choices recorded in the project. No
> audience statement written before generation is recorded, and this section must not
> be read as one.

- **Who it is for (draft):** Amharic-speaking family members and followers, at home
  and abroad, who may already know a version of this tale.
- **Where they watch (draft):** on a phone, in a short-video feed (9:16) first; on a
  larger screen or YouTube (16:9) second.
- **What they should feel (draft):** warmth and quiet suspense, then relief.
- **What they should understand (draft):** trust is earned by patience, a little at a
  time. A stepparent can be the one who waits and loves.
- **Why this person or place matters to the author:** TO BE FILLED BY THE AUTHOR.

## 2. Why this story

Chosen from five Ethiopian candidates (The Lion's Whisker, Saint Yared and the
caterpillar, Fire on the Mountain, Lalibela and the bees, the Meskel smoke) because it
suits what the models do well:

- few characters: Almaz, the boy Dawit, the wise elder and one lion;
- an animal that barely needs to move;
- an arc about patience, which suits slow push-ins and still shots;
- three distinct places, which gives variety without crowds.

The retelling is our own, with our own names. No published text was adapted.

## 3. Structure

| Movement | Shots | Beat |
|---|---|---|
| A new family | 1 to 4 | Almaz marries a widower; his son will not speak to her or eat her food |
| The request | 5 to 8 | She asks an elder for a potion; he needs a whisker from a living lion |
| The lion | 9 to 13 | Day by day she brings meat and sits closer, until she plucks a whisker |
| The lesson | 14 and 15 | The elder burns the whisker: be as patient with the boy |
| Resolution | 16 | At dusk Dawit shares her meal |

Sixteen lines of about ten words, one shot each. The brief asked for one word fewer
per line than the previous film because Amharic runs longer.

## 4. Every shot and its reason

From the 16:9 `build/storyboard.json`, fit plan and script. "Picture" summarises the
storyboard's `visual`. The reasons were written up from the storyboard and the design
notes after the render. Seconds are the Amharic render. The film's build predates the
`reason` field, so an export fills it with a placeholder: copy these reasons into the
project's `storyboard.json`.The author should check them: TO BE CONFIRMED BY THE AUTHOR.

| # | s | Narration (English source) | Picture | Motion | Why this shot exists |
|---:|---:|---|---|---|---|
| 1 | 5.6 | Long ago, Almaz married a widower in the green highlands. | Medium wide: Almaz beside her new husband on a highland meadow, morning | push_in | Establishes folklore, the heroine and the marriage that starts the problem. The push-in draws the viewer into the tale. |
| 2 | 4.8 | She moved into his stone farmhouse beneath the misty hills. | Wide: Almaz alone walking to the farmhouse in mist | pan | Shows the first place and that she arrives as an outsider. A pan carries the journey. |
| 3 | 4.5 | His young son, Dawit, would not look at her or speak. | Medium at a child's height: Dawit on the doorstep, face turned away | push_in | Introduces the second lead and the conflict. His eye level puts us with him; the push-in marks the emotional beat. |
| 4 | 4.0 | Each evening, the bowl she filled for him sat untouched. | Close-up from above: a full bowl and injera, nobody | ambient | Shows rejection through an object. An empty frame and stillness make the loneliness felt; the bowl returns in shot 16. |
| 5 | 5.4 | Heartbroken, Almaz climbed the mountain path to a wise elder. | Wide from below: Almaz alone climbing in mist | pan | Her decision to act. Low angle and climb show effort; mist separates this world from home. |
| 6 | 4.2 | She begged him for a potion to make the boy love her. | Medium: Almaz kneeling before the elder in the hermitage | push_in | States what she wants. Kneeling shows how much; the push-in tightens on the plea. |
| 7 | 4.7 | The elder nodded slowly and said he could make one. | Close-up: the elder's lined face in firelight | push_in | Introduces the elder's authority. The close-up asks us to read his face: help is coming, with a condition. |
| 8 | 4.5 | But he needed one whisker from a living lion. | Medium: the elder alone by the hearth, looking to the doorway | ambient | The turn of the story. A still frame and a glance outward let the danger sink in. |
| 9 | 4.3 | At dawn, Almaz carried meat down to the rocky ravine. | Wide: Almaz alone descending into the ravine with a bundle | pan | Third place and the start of the trial. Going down mirrors the climb of shot 5. |
| 10 | 4.1 | There a great lion lay resting in the shade. | Wide: the black-maned lion lying under an overhang | ambient | The first sight of the threat, calm and still. Suspense comes from its size, not its movement. |
| 11 | 4.2 | She set the meat down and waited, very still and quiet. | Wide: Almaz sitting still, meat before her, lion far off | ambient | Fixes the starting distance between them. Stillness is the patience the tale is about. |
| 12 | 3.9 | Each day she sat a little closer than the day before. | Medium wide: Almaz a few paces from the watching lion | push_in | The distance has shrunk. The push-in does the closing in. |
| 13 | 4.8 | At last the lion ate calmly beside her, and she plucked one whisker. | Medium close-up: Almaz beside the eating lion, a whisker in her fingers | push_in | The climax. The closest framing of the pair, held on the gentle gesture. |
| 14 | 3.7 | The elder dropped the whisker into his fire and smiled. | Close-up: the elder holding the whisker over the fire | ambient | The surprise: the prize is thrown away. Only flame and smoke move. |
| 15 | 3.5 | Be as patient with the boy as you were with the lion. | Medium close-up: the elder alone, looking kindly at the camera | push_in | The lesson, spoken almost to the viewer. |
| 16 | 4.4 | At dusk, Dawit sat beside Almaz and shared her meal. | Medium: Dawit and Almaz sharing from one bowl at dusk | ambient | Pays off shots 3 and 4. The shared bowl and warm light show the change without saying it. |

Known mismatches between plan and picture: the narration of shot 7 was rewritten in
Amharic from "nodded" to "agreed", while the storyboard still says the elder nods; in
shot 16 Almaz wears a different top.

## 5. Visual rules

**One look**, from the bible:

> Photorealistic live-action documentary footage set in the Ethiopian highlands.
> Natural skin, cotton, fur, earth and stone texture, subdued warm colours and
> physically plausible light. Every shot depicts a single simple moment with clear
> foreground subjects and restrained camera movement. One full-frame film still with a
> single composition.

Live-action because the video model animates photographic footage best; a restrained
palette hides small artefacts.

**A palette per place:**

| Place | Palette |
|---|---|
| Farmhouse | green terraces, grey stone, soft overcast light; amber lamplight at night |
| Hermitage | cool mountain mist outside, orange firelight inside |
| Ravine | golden grass, dust and a lone acacia in warm dawn and afternoon light |

The film starts cool and ends in warm dusk at the farmhouse.

**Characters, described in text only (no reference photos):**

| Character | Anchor |
|---|---|
| Almaz | braided black hair, white netela with a thin red border, long white dress |
| Dawit | about eight, close-cropped hair, faded blue shirt, brown shorts; blue stands out against earth tones |
| The wise elder | very old, deep brown skin, short white beard, dark brown wool blanket, carved stick |
| The lion | large calm male, thick dark mane, always on four legs |

**Rules every shot follows** (the first five are sent to the storyboard model on every
run):

1. Animals stand, walk or graze on four legs; never rearing or posed like people.
2. Objects sit as they would in life.
3. Anyone other than the shot's character looks clearly different.
4. Hands stay simple.
5. At most four people.
6. One simple moment per shot; no text inside the picture.
7. The lion is always calm: lying, walking slowly or eating.
8. A shot meant for one person says "alone, the only person in the shot".

**Camera:** three motions only.

| Motion | Count | Shots | Used for |
|---|---:|---|---|
| `push_in` | 7 | 1, 3, 6, 7, 12, 13, 15 | emotional beats |
| `ambient` | 6 | 4, 8, 10, 11, 14, 16 | stillness and waiting |
| `pan` | 3 | 2, 5, 9 | journeys |

The camera never pans past the lion.

**Two aspect ratios:** generated at 640x352 and 352x640 and cropped by 2% to exact
16:9 and 9:16. The vertical cut was drawn again from the same storyboard, because
cropping a 16:9 frame would keep only about 30% of it.

## 6. Sound, subtitles and end card

- **Voice:** `am-ET-AmehaNeural` (Edge TTS) in the cut the viewers saw. All three
  testers found it robotic, so the narration moves to Addis AI (`am-hamen`); see section 9. Amharic speeds on screen were 0.90 to
  1.08x with no continuation clips.
- **Translation:** Claude Opus 5.5, checked by back-translation. Line 7 was rewritten;
  line 10 ("resting" read back as "asleep") was kept.
- **Score:** ACE-Step 1.5, instrumental, 76 BPM in A minor, slower and darker than the
  previous film to carry the ravine. Music at 40%, ducked under the voice, fading over
  the card.
- **Score candidates and choice:** one score was generated for the delivered cut. If
  candidates are generated with `music.candidates`, record the choice and reason here:
  TO BE FILLED BY THE AUTHOR.
- **Subtitles:** Noto Sans Ethiopic. In the vertical cut long lines wrap to 2 to 4
  lines.
- **End card:** 5 s in Amharic, with "AI-generated video" repeated in English.

## 7. Known weak spots

Judged from still frames; each can be redrawn with `vidpipe redo shot N`.

- Green streaks in the 16:9 cut: shot 4 (beside the bowl) and shot 13 (near the
  whisker).
- Almaz's top changes in shot 16, in both cuts.
- The elder's skin tone still varies a little.
- Large portrait subtitles.
- No native Amharic speaker has reviewed narration, subtitles or end card.

## 8. User test 1: the radio cut

> **TO BE FILLED BY THE AUTHOR.** No radio-cut test is recorded. Do not write
> anything here that a real person did not say or do. The pictures already exist, so
> if this test is run now, say that it came after generation.

Build the cut with `uv run vidpipe radio-cut <project>`: narration and subtitles over
a black screen, written to `out/<name>_<lang>_radio.mp4`. It plays the score if the
project already has one, as this film's does, and a placeholder tone otherwise.

**Date and method (in person, call, Slack):** TO BE FILLED BY THE AUTHOR

**What was shown (file, length):** TO BE FILLED BY THE AUTHOR

| Tester (initials or role, with permission) | Why they are in the audience | What they said or did | Where they lost interest or got confused |
|---|---|---|---|
| TO BE FILLED BY THE AUTHOR | TO BE FILLED BY THE AUTHOR | TO BE FILLED BY THE AUTHOR | TO BE FILLED BY THE AUTHOR |
| TO BE FILLED BY THE AUTHOR | TO BE FILLED BY THE AUTHOR | TO BE FILLED BY THE AUTHOR | TO BE FILLED BY THE AUTHOR |
| TO BE FILLED BY THE AUTHOR | TO BE FILLED BY THE AUTHOR | TO BE FILLED BY THE AUTHOR | TO BE FILLED BY THE AUTHOR |

Questions to ask, without leading: What happened in the story? What did you feel at the
end? Was any word or name hard to follow? Where did your attention drift?

**What we changed because of it** (shot or line, before, after, who prompted it):
TO BE FILLED BY THE AUTHOR

**What we decided not to change, and why:** TO BE FILLED BY THE AUTHOR

## 9. User test 2: the near-final cut

Three people watched a cut with pictures, narration, score and subtitles: two
technical viewers and one non-technical viewer.

**What was shown:** the Amharic cut of *The Lion's Whisker*, narrated with Edge TTS
(`am-ET-AmehaNeural`).

| Tester | Background | What they said | What they noticed in the pictures |
|---|---|---|---|
| Viewer A | Technical | The narration voice sounded robotic | No notes, except the recurring artefacts |
| Viewer B | Technical | The narration voice sounded robotic | No notes, except the recurring artefacts |
| Viewer C | Non-technical | The most positive of the three, but also found the voice robotic | No notes, except the recurring artefacts |

**What we heard:** every viewer, technical or not, flagged the same thing: the
synthetic voice. Nobody had notes on the story, the characters or the look. The only
visual comment was the occasional model artefact, such as flicker or a stray glow.

**What we changed because of it:**

1. **The narration voice: Edge TTS → Addis AI.** The voice was the one thing all three
   viewers raised, so the Amharic narration moves to Addis AI (`addis-ai`, voice
   `am-hamen`), a dedicated Amharic voice service the pipeline already supports. English
   stays on Edge TTS. In `vidpipe.yaml`:

   ```yaml
   narration:
     name: addis-ai
     options: {amharic_voice: am-hamen}   # needs ADDIS_API_KEY in the environment
   ```

   Re-voicing re-runs only narration, fit planning and assembly. Keyframes and clips
   are reused, unless a new line runs longer than its shot's clip.

2. **Artefacts: what was already in place, and what was tightened.** The pipeline
   already did these to keep artefacts down:
   - **Live-action look by default.** The video model smears and warps stylised
     images; photographic keyframes animate far more cleanly (EXPERIMENTS.md).
   - **Three gentle camera moves only** (push-in, pan, ambient), with motion prompts
     tuned per move. Fast or complex motion is where Wan 2.2 breaks down.
   - **Short clips.** At most 5 s per clip, and speed changes capped at 1.3×, so no
     clip is stretched far from how it was generated.
   - **Storyboard rules aimed at known failure modes:**
     - animals stay on four legs;
     - at most four people per shot, and solo shots say "alone, the only person in
       the shot";
     - hands stay simple;
     - secondary characters are described so they don't mutate.
   - **Keyframe review before animation.** Every still is checked on a contact sheet
     before any GPU time goes on video. Bad stills are fixed in the storyboard or
     re-rolled with `vidpipe redo shot N`. The second film needed 12 rerolls here.
   - **Single-shot re-rolls afterwards.** A clip with a visible artefact can be redone
     on its own with a new seed, at about 3 minutes of GPU, without touching the rest.

   In response to this feedback, the v2 render goes further: it rewrites the prompt
   rules from documented strengths and weaknesses of Wan 2.2 and FLUX.2 klein (see
   `docs/research/model-strengths.md` and the rules comparison in EXPERIMENTS.md).

**What we decided not to change, and why:** the story, structure and visual style.
None of the three viewers raised them.

## 10. Changes made during production (not from user tests)

These came from reviewing keyframes and the translation check, before any audience saw
the film:

| Change | Why |
|---|---|
| Named "the large black-maned male lion" in shots 11 to 13 | the lion lost its mane |
| Added "deep brown skin" to the elder | his skin tone shifted between shots |
| "Alone, the only person in the shot" in solo shots (two more in portrait) | extra people appeared |
| Edited Dawit's clothes in the storyboard | they differed from the bible |
| Rewrote Amharic line 7 | "nodded" could be heard as refusal |

There were 12 keyframe re-rolls in 16:9 and 2 more in portrait. Details in
[EXPERIMENTS.md](EXPERIMENTS.md), entry 23.
