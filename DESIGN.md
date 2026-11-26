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

**Intent: retell Ethiopian folk tales in a new medium, so they stay in the public's
mind.** Tales like this one were passed on aloud, from parents to children. Fewer
people hear them that way now, and they don't travel well into the feeds where people
spend their attention. This film carries an oral tale into that space: short, vertical
first, in Amharic, and cheap enough to repeat for other tales.

- **Who it is for:** Amharic speakers at home and in the diaspora, especially younger
  viewers who scroll short-video feeds and may never have heard the tale told aloud,
  and parents who want to share it with their children. English subtitles let
  non-Amharic speakers and second-generation viewers follow it too.
- **Where they watch:** on a phone, in a short-video feed (9:16) first; YouTube or a
  larger screen (16:9) second.
- **What they should feel:** the warmth of a story being told to them, quiet suspense
  around the lion, then relief.
- **What they should take away:** the tale itself, clearly enough to retell it, and
  its lesson: trust is earned by patience, a little at a time.
- **Why this story matters to me:** it is a tale my parents told me. Retelling it in a
  form people share today is a way of passing it on the way it was passed to me.

This statement was written up on 26 November 2026, during production. It records the
intent behind the choices below; it was not written down before the first generation.

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
project's `storyboard.json`. Each reason serves the intent in section 1: tell the tale
clearly enough to be retold, and give it a few images that stay with the viewer.

| # | s | Narration (English source) | Picture | Motion | Why this shot exists |
|---:|---:|---|---|---|---|
| 1 | 5.6 | Long ago, Almaz married a widower in the green highlands. | Medium wide: Almaz beside her new husband on a highland meadow, morning | push_in | Opens like a told tale ("Long ago"), so the viewer knows this is folklore being passed on. Introduces the heroine and the marriage that starts the problem; the push-in draws the viewer in. |
| 2 | 4.8 | She moved into his stone farmhouse beneath the misty hills. | Wide: Almaz alone walking to the farmhouse in mist | pan | Shows the first place and that she arrives as an outsider. A pan carries the journey. |
| 3 | 4.5 | His young son, Dawit, would not look at her or speak. | Medium at a child's height: Dawit on the doorstep, face turned away | push_in | Introduces the second lead and the conflict. His eye level puts us with him; the push-in marks the emotional beat. |
| 4 | 4.0 | Each evening, the bowl she filled for him sat untouched. | Close-up from above: a full bowl and injera, nobody | ambient | Shows rejection through an object. The untouched bowl is one of the film's two memorable images; it returns, shared, in shot 16. |
| 5 | 5.4 | Heartbroken, Almaz climbed the mountain path to a wise elder. | Wide from below: Almaz alone climbing in mist | pan | Her decision to act. Low angle and climb show effort; mist separates this world from home. |
| 6 | 4.2 | She begged him for a potion to make the boy love her. | Medium: Almaz kneeling before the elder in the hermitage | push_in | States what she wants. Kneeling shows how much; the push-in tightens on the plea. |
| 7 | 4.7 | The elder nodded slowly and said he could make one. | Close-up: the elder's lined face in firelight | push_in | Introduces the elder's authority. The close-up asks us to read his face: help is coming, with a condition. |
| 8 | 4.5 | But he needed one whisker from a living lion. | Medium: the elder alone by the hearth, looking to the doorway | ambient | The turn of the story. A still frame and a glance outward let the danger sink in. |
| 9 | 4.3 | At dawn, Almaz carried meat down to the rocky ravine. | Wide: Almaz alone descending into the ravine with a bundle | pan | Third place and the start of the trial. Going down mirrors the climb of shot 5. |
| 10 | 4.1 | There a great lion lay resting in the shade. | Wide: the black-maned lion lying under an overhang | ambient | The tale's central image: the lion. Shown calm and still, so suspense comes from its size, not from violence, which keeps the film suitable for children watching with parents. |
| 11 | 4.2 | She set the meat down and waited, very still and quiet. | Wide: Almaz sitting still, meat before her, lion far off | ambient | Fixes the starting distance between them. Stillness is the patience the tale is about. |
| 12 | 3.9 | Each day she sat a little closer than the day before. | Medium wide: Almaz a few paces from the watching lion | push_in | The distance has shrunk. The push-in does the closing in. |
| 13 | 4.8 | At last the lion ate calmly beside her, and she plucked one whisker. | Medium close-up: Almaz beside the eating lion, a whisker in her fingers | push_in | The climax and the image the tale is named for: the whisker. The closest framing of the pair, held on the gentle gesture. |
| 14 | 3.7 | The elder dropped the whisker into his fire and smiled. | Close-up: the elder holding the whisker over the fire | ambient | The surprise: the prize is thrown away. Only flame and smoke move. |
| 15 | 3.5 | Be as patient with the boy as you were with the lion. | Medium close-up: the elder alone, looking kindly at the camera | push_in | The moral, spoken almost to the viewer, the way a parent telling the tale would turn to the listener. This is the line to remember and retell. |
| 16 | 4.4 | At dusk, Dawit sat beside Almaz and shared her meal. | Medium: Dawit and Almaz sharing from one bowl at dusk | ambient | Pays off shots 3 and 4. The shared bowl and warm light show the change without saying it, and end the tale where a family would hear it: together, at a meal. |

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

**Who:** three friends: two technical and one non-technical viewer.

**What was shown:** a radio cut, the narration over music with no pictures, voiced
with a Google text-to-speech voice. That cut was made outside vidpipe and isn't saved
in this repository, so this record rests on the author's account.

| Tester | Background | What they said |
|---|---|---|
| Viewer A | Technical | The voice sounded robotic |
| Viewer B | Technical | The voice sounded robotic |
| Viewer C | Non-technical | More positive overall, but also found the voice robotic |

**What we changed because of it:** the narration voice. All three viewers raised it,
so Amharic narration moved to Addis AI (`addis-ai`, voice `am-hamen`), a dedicated
Amharic voice service. It was trialled in the coffee-origin projects (EXPERIMENTS.md),
where it sounded more natural than the Google voice. The Lion's Whisker renders made
so far used Edge TTS; the final cuts are re-voiced with Addis.

**What we decided not to change, and why:** the story and the script. Nobody had
trouble following the tale.

## 9. User test 2: the cut with pictures

**Who:** the same three viewers: two technical, one non-technical.

**What was shown:** the Amharic cut with pictures, narration, score and subtitles.

| Tester | Background | What they said about the pictures |
|---|---|---|
| Viewer A | Technical | Recognised it as AI-generated at once: weak motion and frequent artefacts |
| Viewer B | Technical | Same: no notes on story or look, only the artefacts |
| Viewer C | Non-technical | The most positive; no notes on the visuals beyond the artefacts |

**What we heard:** nobody had notes on the story, characters or look. The one
consistent visual note was the frequent artefacts, such as flicker, warping and a
stray glow.

**What we changed because of it: measures to minimise artefacts.** Some were already
in place; the feedback made them a priority and led to the v2 rules.
- **Live-action look by default.** The video model smears and warps stylised images;
  photographic keyframes animate far more cleanly.
- **Three gentle camera moves only** (push-in, pan, ambient), with motion prompts tuned
  per move. Fast or complex motion is where Wan 2.2 breaks down.
- **Short clips:** at most 5 s each, and speed changes capped at 1.3×.
- **Storyboard rules aimed at known failure modes:**
  - animals stay on four legs;
  - at most four people per shot, and solo shots say "alone, the only person in the
    shot";
  - hands stay simple;
  - secondary characters are described so they don't mutate.
- **Keyframe review before animation.** Every still is checked on a contact sheet
  before GPU time goes on video. Bad stills are fixed in the storyboard or re-rolled
  with `vidpipe redo shot N` (12 rerolls for this film).
- **Single-shot re-rolls afterwards:** a clip with a visible artefact can be redone
  alone, with a new seed, for about 3 minutes of GPU.
- **v2 prompt rules:** rewritten from the documented strengths and weaknesses of Wan
  2.2 and FLUX.2 klein (`docs/research/model-strengths.md`).

**What we decided not to change, and why:** the story, structure and visual style.
None of the viewers raised them.

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
