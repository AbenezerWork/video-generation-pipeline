# Design: *The Lion's Whisker*

An Ethiopian folk tale narrated in Amharic, designed for both 16:9 and 9:16.

| Cut | Frame | Length | File in the demo project |
|---|---|---|---|
| Landscape, final Addis cut | 1280x720 | 67.85 s (62.85 s of story, 5 s end card) | `lions-whisker-final-16x9/out/lions-whisker-16x9_am.mp4` |
| Portrait, final Addis cut | 720x1280 | 69.57 s (64.57 s of story, 5 s end card) | `lions-whisker-final-9x16/out/lions-whisker-9x16_am.mp4` |

Both MP4s are H.264 at 24 fps with AAC audio. Both have Addis AI Amharic
narration (`am-hamen`), burned-in English subtitles, a matching `.srt` and an
AI end card. Both encoded mixes measured -14.0 LUFS. True peaks were -1.0 dBTP
in landscape and -0.6 dBTP in portrait. The projects share the script and voice
settings. They generated their narration and scores separately.

The demo projects live outside this repository, in `%USERPROFILE%\.t3\vidpipe-demos\`.
The checked-in projects are in [16:9](examples/lions-whisker-16x9) and
[9:16](examples/lions-whisker-9x16).

For an older project with a hand-edited storyboard only under `build/`, run
`vidpipe export-storyboard <project>` before running the new code. The checked-in
examples already have the editable contract. Check `vidpipe plan` before running.


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

From the final landscape `storyboard.json` and `build/fit_plan.json`. "Picture"
summarises the storyboard's `visual`. Seconds are from the Amharic fit plan,
rounded to one decimal. The reasons draw on the storyboard and the design notes
written during production.

| # | s | Narration (English source) | Picture | Motion | Why this shot exists |
|---:|---:|---|---|---|---|
| 1 | 5.3 | Long ago, Almaz married a widower in the green highlands. | Wide: Almaz beside her new husband in the highlands, morning | push_in | Opens like a told tale ("Long ago"). Introduces the heroine and the marriage that starts the problem. |
| 2 | 3.7 | She moved into his stone farmhouse beneath the misty hills. | Wide: Almaz alone walking to the farmhouse in mist | pan | Shows the first place and that she arrives as an outsider. A pan carries the journey. |
| 3 | 4.2 | His young son, Dawit, would not look at her or speak. | Medium: Dawit on a low stone wall, face turned away | ambient | Introduces the second lead and the conflict. His eye level puts us with him. |
| 4 | 3.2 | Each evening, the bowl she filled for him sat untouched. | Close-up: a full bowl on a stool, nobody | ambient | Shows rejection through an object. The untouched bowl returns, shared, in shot 16. |
| 5 | 4.6 | Heartbroken, Almaz climbed the mountain path to a wise elder. | Wide from above: Almaz alone climbing in mist | pan | She decides to act. The climb shows effort and mist separates this world from home. |
| 6 | 4.0 | She begged him for a potion to make the boy love her. | Medium: Almaz kneeling before the elder outside his hut, fire between them | push_in | States what she wants. The push-in tightens on the plea. |
| 7 | 4.1 | The elder nodded slowly and said he could make one. | Close-up: the elder's lined face in firelight | ambient | Introduces the elder's authority. The close-up holds on his face as he agrees to help. |
| 8 | 4.1 | But he needed one whisker from a living lion. | Medium: the elder alone by the fire, holding his stick | push_in | The condition turns the story. The held gaze gives the danger time to sink in. |
| 9 | 3.8 | At dawn, Almaz carried meat down to the rocky ravine. | Wide: Almaz alone descending into the ravine with a bundle | pan | Third place and the start of the trial. Going down mirrors the climb of shot 5. |
| 10 | 3.7 | There a great lion lay resting in the shade. | Wide: the black-maned lion lying under an acacia | ambient | The tale's central image. Its size gives the scene suspense while it stays calm. |
| 11 | 3.7 | She set the meat down and waited, very still and quiet. | Wide: Almaz sitting still, meat before her, lion far off | ambient | Fixes the starting distance between them. Stillness shows Almaz's patience. |
| 12 | 3.5 | Each day she sat a little closer than the day before. | Medium: Almaz a few paces from the watching lion | ambient | The distance has shrunk. The tighter framing shows how near she can now sit. |
| 13 | 4.6 | At last the lion ate calmly beside her, and she plucked one whisker. | Medium: Almaz sits beside the eating lion | ambient | The closest view of the pair marks the climax. The narration carries the plucking. |
| 14 | 3.1 | The elder dropped the whisker into his fire and smiled. | Medium: the elder smiles at the fire as Almaz watches | push_in | The fire and the elder's expression carry the surprise of giving up the prize. |
| 15 | 3.3 | Be as patient with the boy as you were with the lion. | Medium: Almaz alone, listening by the fire | ambient | Holds on Almaz as she takes in the line the viewer can remember and retell. |
| 16 | 4.0 | At dusk, Dawit sat beside Almaz and shared her meal. | Medium: Dawit and Almaz on a bench, a bowl between them | push_in | Pays off shots 3 and 4. The shared bowl and warm light show the change. |

The Amharic for shot 7 was rewritten from "nodded" to "agreed". The English
source line and caption keep "nodded". The pictures in shots 13 and 14 leave the
small action with the whisker to the narration.

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

**Rules for the storyboard and prompts:**

1. Animals stand, walk or graze on four legs; never rearing or posed like people.
2. Objects sit as they would in life.
3. Anyone other than the shot's character looks clearly different.
4. Hands stay simple.
5. At most four people.
6. One simple moment per shot; no text inside the picture.
7. The lion is always calm: lying, walking slowly or eating.
8. A shot meant for one person says "alone, the only person in the shot".
9. Name secondary cast in the visual so the keyframe prompt can use their bible
   descriptions. Record the number of people and one small movement per shot.

**Camera:** three motions only.

| Motion | Count | Shots | Used for |
|---|---:|---|---|
| `push_in` | 5 | 1, 6, 8, 14, 16 | emotional beats |
| `ambient` | 8 | 3, 4, 7, 10, 11, 12, 13, 15 | stillness and waiting |
| `pan` | 3 | 2, 5, 9 | journeys |

The camera never pans past the lion.

**Two aspect ratios:** 640x352 landscape and 352x640 portrait, with about a 2%
crop to exact 16:9 and 9:16 at assembly. The portrait pictures were generated
at their own size. A crop from landscape would keep only about 30% of the frame.

## 6. Sound, subtitles and end card

- **Voice:** the earlier picture cut used Edge TTS (`am-ET-AmehaNeural`). The
  final cuts use Addis AI (`am-hamen`), following the feedback in section 8.
  The Amharic playback speeds are 0.95 to 1.30x in landscape and 0.91 to 1.30x
  in portrait, with no continuation clips.
- **Translation:** Claude Opus 5.5, checked by back-translation. Line 7 was rewritten;
  line 10 ("resting" read back as "asleep") was kept.
- **Score:** ACE-Step 1.5, instrumental, 76 BPM in A minor, slower and darker than the
  previous film to carry the ravine. Music at 40%, ducked under the voice, fading over
  the card.
- **Subtitles:** both final Amharic cuts burn in English captions using
  `subtitles.text_language: en`. The portrait cut splits seven longer lines
  across two cues. Each shot's captions follow its Amharic timing.
- **End card:** 5 s in Amharic, with "AI-generated video" repeated in English.

## 7. Known weak spots

From sampled frames. The v1 defects and the v2 comparison
are in [EXPERIMENTS.md](EXPERIMENTS.md#25-give-each-model-the-details-it-needs-26-nov).

- In the final landscape cut, shot 4 has a strong light shift and shot 12 has red
  blocks in the frame. Shots can be redrawn with `vidpipe redo shot N`.
- The elder's skin tone still varies between shots. Almaz's shawl stays
  recognisable, with changes in how it covers her hair.
- In portrait, shot 8 has a blue mark at the right edge. The English captions
  are visible in the samples, and the layout still needs a check on a phone.
- No native Amharic speaker review of the narration or end card is recorded.

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
where the author found it more natural than the Google voice. Both final cuts
use Addis. The feedback predates the Addis cuts.

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
  with `vidpipe redo shot N` (12 gate re-rolls for v1 landscape).
- **Single-shot re-rolls afterwards:** a clip with a visible artefact can be redone
  alone, with a new seed, for about 3 minutes of GPU.
- **v2 prompt rules:** rewritten from the documented strengths and weaknesses of Wan
  2.2 and FLUX.2 klein. See [the v2 comparison](EXPERIMENTS.md#25-give-each-model-the-details-it-needs-26-nov).

**What we decided not to change, and why:** the story, structure and visual style.
None of the viewers raised them.

## 10. Changes made during production (not from user tests)

These came from reviewing v1 keyframes and the translation check, before any audience
saw the film:

| Change | Why |
|---|---|
| Named "the large black-maned male lion" in shots 11 to 13 | the lion lost its mane |
| Added "deep brown skin" to the elder | his skin tone shifted between shots |
| "Alone, the only person in the shot" in solo shots (two more in portrait) | extra people appeared |
| Edited Dawit's clothes in the storyboard | they differed from the bible |
| Rewrote Amharic line 7 | "nodded" could be heard as refusal |

V1 had 12 keyframe re-rolls in 16:9 and 2 more in portrait. Details in
[EXPERIMENTS.md](EXPERIMENTS.md), entry 23.
