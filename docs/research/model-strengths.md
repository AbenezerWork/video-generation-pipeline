# What the models do well and badly, and how to prompt them

Research for the prompt rules the pipeline ships (`STORYBOARD_RULES`, `bible.keyframe_brief`,
`MOTION_DESCRIPTIONS` and the Wan image-to-video prompt). Gathered on 26 Nov 2026 from official
model cards, vendor docs and practitioner write-ups, then checked against what our own runs showed
([experiments.md](../../experiments.md)). Where a claim comes only from a third-party blog, it is
marked as such. Our own observations are marked **(ours)**.

Models covered:

- **Keyframes:** FLUX.2 [klein] 4B, fp8, distilled, 4 steps, CFG 1.0 (our workflow zeroes the
  negative conditioning).
- **Video:** Wan 2.2 TI2V 5B, GGUF Q5_K_M, image-to-video, 20 steps, CFG 5, shift 8, at most
  5 s at 24 fps.

## FLUX.2 [klein] 4B (keyframes)

### Documented

- **Prompt as written.** klein "does not include prompt upsampling. Write detailed, descriptive
  prompts for best results." ([BFL FLUX.2 overview](https://docs.bfl.ai/flux_2/flux2_overview))
- **Prose, not keyword lists.** "Write in prose, not keyword lists: describe scenes like a
  novelist." ([BFL unified prompting reference, klein section](https://docs.bfl.ml/guides/prompting_unified_reference.md))
- **Word order matters: the start of the prompt weighs most.** "FLUX.2 pays more attention to what
  comes first." Priority: main subject, key action, critical style, essential context, secondary
  details. ([BFL FLUX.2 prompting guide](https://docs.bfl.ai/guides/prompting_guide_flux2); written
  for [pro]/[max], same family.) fal's klein guide gives the same order: "subject first, environment
  second, style third, technical specifications last", and notes that nouns carry more weight than
  modifiers. ([fal klein prompt guide](https://fal.ai/learn/devs/flux-2-klein-prompt-guide))
- **No negative prompts.** "FLUX.2 does not support negative prompts"; describe what you want
  instead ("sharp focus throughout", not "no blur").
  ([BFL FLUX.2 prompting guide](https://docs.bfl.ai/guides/prompting_guide_flux2)) The distilled
  klein runs at guidance 1.0 ([model card](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B)),
  so a negative prompt has no effect in our workflow either. Every constraint must be stated in the
  positive prompt.
- **Length.** BFL: 30–80 words is "usually ideal", 80+ for complex scenes. fal (third party):
  "Prompts exceeding 100 words create confusion."
- **Light and lens wording helps realism.** "Describe the light source, direction, and softness."
  ([BFL unified reference](https://docs.bfl.ml/guides/prompting_unified_reference.md)) Camera and
  lens names ("shot on … 35mm") give "more authentic results than 'professional photo'".
  ([BFL FLUX.2 guide](https://docs.bfl.ai/guides/prompting_guide_flux2))
- **Multiple subjects need explicit placement.** The guides show adding a second object by stating
  its position ("right side of the black mug"), and fal says many prompts "omit spatial
  relationships". ([BFL](https://docs.bfl.ai/guides/prompting_guide_flux2),
  [fal](https://fal.ai/learn/devs/flux-2-klein-prompt-guide))
- **Consistency across images means repeating the description.** For a character across panels,
  "define your character in detail and maintain that description across panels".
  ([BFL FLUX.2 guide](https://docs.bfl.ai/guides/prompting_guide_flux2)) Up to 4 reference images
  for klein; say how each one is used ("subject from image 1").
  ([BFL overview](https://docs.bfl.ai/flux_2/flux2_overview))
- **Limitations (model card):** text "may be inaccurate or subject to distortion"; the model "may
  represent or amplify biases observed in the training data"; "prompt following is heavily
  influenced by the prompting style".
  ([FLUX.2-klein-4B model card](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B))
- **Distilled = less diverse.** The base (non-distilled) variants have "higher output diversity than
  the distilled models". ([BFL klein announcement](https://bfl.ai/blog/flux2-klein-towards-interactive-visual-intelligence))
- **Anatomy is hit and miss** (third party): good hands in some tests, "classic anatomy fails
  (extra fingers, weird hands)" in others.
  ([community blind-spots set](https://huggingface.co/datasets/itsazza/flux2-klein-4B-blind-spots),
  [Towards AI stress test](https://pub.towardsai.net/best-image-generation-model-for-small-gpus-18f83da22ef4))

Not documented anywhere we found: people counts, single-subject control, skin-tone fidelity.

### Observed in our runs (ours)

- **Fills empty space with people.** Stray figures behind a lone character, a duplicate of the same
  elder in one shot (Lion's Whisker v1, shots 5 and 15). "Alone, the only person in the shot" in
  the visual fixed it.
- **A secondary character without its description drifts.** The lion lost its mane in shots where
  Almaz was the main character, because only the main character's description was sent.
- **Skin tone drifts towards lighter** for an elderly man unless the skin tone is stated (the elder,
  v1). Stating it early in his description helped; it still varies a little. This matches the model
  card's bias warning.
- **The description is applied to everyone.** Secondary people copied the protagonist's face and
  clothes until the prompt said others look different (coffee-origin).
- **Setting cues are needed in every shot.** Without highland cues, shots drifted to a modern
  rooftop or a European market (ADR 0001 spike). Interiors came out as exteriors when the visual did
  not describe the room (Khalid, shots 11–14).
- **Physically wrong arrangements:** fire drawn inside a roasting pan (coffee-origin, shot 7).
- **Style text leaks into every shot.** A coffee-brewing style description added brewing insets to
  unrelated shots.

## Wan 2.2 TI2V 5B (image-to-video)

### Documented

- **The prompt should describe motion, not the picture** (official advice; see our A/B below,
  which found the opposite for the 5B at our size). The official image-to-video
  prompt-rewriting system prompt says: "Focus on dynamic content in the video description and avoid
  adding static scene descriptions. If the user's input already describes elements visible in the
  image, remove those static descriptions." It keeps camera movements ("the camera pans up", "the
  camera moves from left to right"), emphasises and simplifies the main subject ("a girl is
  dancing"), and caps the prompt at 100 words.
  ([Wan2.2 `system_prompt.py`](https://raw.githubusercontent.com/Wan-Video/Wan2.2/main/wan/utils/system_prompt.py))
- **Alibaba's formula for image-to-video:** "Prompt = Motion + Camera movement"; the image defines
  the subject, so "your prompt should focus on motion and camera movements". Camera wording it uses:
  "camera pushes in", "camera moves left", "fixed camera", "camera pulls out", "camera tilts up".
  ([Alibaba Model Studio video prompt guide](https://help.aliyun.com/en/model-studio/text-to-video-prompt))
- **One camera move per shot.** Contradictory motion instructions "create unpredictable results";
  "choose one primary motion type and define pacing separately". "Only animate elements visible in
  your uploaded image." ([VEED Wan 2.2 guide](https://www.veed.io/learn/wan-2-2-prompting-guide),
  third party)
- **Official default negative prompt** (Chinese, used by all Wan 2.2 configs including TI2V-5B):
  `色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走`
  — garish colour, overexposed, static, blurred detail, subtitles, style, artwork, painting, still
  image, greyish, worst/low quality, JPEG artefacts, ugly, mutilated, extra fingers, badly drawn
  hands, badly drawn face, deformed, disfigured, malformed limbs, fused fingers, motionless frame,
  cluttered background, three legs, many people in the background, walking backwards.
  ([Wan2.2 `shared_config.py`](https://raw.githubusercontent.com/Wan-Video/Wan2.2/main/wan/configs/shared_config.py))
  The list itself is a map of the model's known failure modes: hands and fingers, faces, extra
  legs, crowds appearing in the background, people walking backwards, static output.
- **TI2V-5B settings:** 720P is 1280x704 or 704x1280 (not 1280x720), 24 fps, 121 frames by default,
  50 steps, shift 5.0, guidance 5.0
  ([`wan_ti2v_5B.py`](https://raw.githubusercontent.com/Wan-Video/Wan2.2/main/wan/configs/wan_ti2v_5B.py),
  [model card](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B)). ComfyUI: the 5B "should fit well on
  8GB vram with the ComfyUI native offloading", and is positioned as the fast option, with the 14B
  models as the high-quality one. ([ComfyUI Wan 2.2 docs](https://docs.comfy.org/tutorials/video/wan/wan2_2))
- **What it does well** (third party): "hair blowing, water flowing, or fabric draping", "subtle head
  turns and natural breathing" for portraits, landscapes, slow zooms, pans and orbits; it "maintains
  subject identity and environmental details". **What it does badly:** "complex multi-subject
  interactions where multiple people need coordinated movements" and big transformations
  (day to night). For portraits, lock the face: "Face and eyes remain still, only hair moves".
  ([VEED](https://www.veed.io/learn/wan-2-2-prompting-guide))
- **Hands and faces are the weak spot across the Wan 2.2 family** (third party): fingers merge,
  multiply or dissolve, worse with fast arm movement; faces drift and morph, especially in medium
  shots. ([getimg.ai](https://getimg.ai/blog/what-is-wan-2-2-and-should-you-use-it-for-ai-videos),
  [MindStudio](https://www.mindstudio.ai/blog/what-is-wan-2-2-video-open-source))
- **The 5B is twitchier than the 14B** (one forum report: "unstable and twitchy"), and camera control
  is harder in image-to-video than in text-to-video.
  ([ComfyUI forum](https://forum.comfy.org/t/wan-2-2-5b/3665),
  [Stable Diffusion Art](https://stable-diffusion-art.com/wan-2-2-image-to-video/))

### Observed in our runs (ours)

- **Photographic keyframes animate far better than stylised ones**, which smeared and warped.
- **A pan prompt also pushed in.** Naming a fixed focal length, a steady subject size and adding
  zoom terms to the negative gave a clean sideways pan.
- **A push-in on a close-up ends too tight** (Khalid, shot 9).
- **Green streak artefacts** appeared in two clips (Lion's Whisker v1, shots 4 and 13). Both had a
  bright point light or a hand close to the camera. Cause unconfirmed.
- **Goats and the lion stayed natural** when they were standing, lying or grazing; rearing animals
  only came from the storyboard asking for it.
- **Continuation clips from the last frame join almost seamlessly** (mean 4.1/255 grey-level
  difference).
- **The official "motion only" advice does not hold for the 5B at 640x352.** Lion's Whisker v2,
  shot 10 (a lion lying in grass, ambient camera), same keyframe and seed 10, 4.25 s, varying only
  the prompt:

  | Positive prompt | Negative | Result |
  |---|---|---|
  | movement + camera + "faces, hands and bodies keep their shape, and nothing appears or disappears" | new | coloured bars across the bottom |
  | the same | old English list | coloured bars |
  | movement + camera + that sentence, no picture description | new | bars and red blobs |
  | movement + camera, no picture description | new | bars |
  | visual + movement + camera + that sentence | new | bars |
  | visual + movement + camera | new | **clean** |
  | visual + old camera sentence (v1 prompt) | new | **clean** |

  Two causes, either enough on its own: without the scene described the model invents objects
  in the lower frame (it looks like hallucinated subtitles or book spines), and a sentence about
  what must *not* happen ("nothing appears", "hands keep their shape") makes it happen. The
  umT5 encoder does not read negation; prohibitions belong in the negative prompt. The new
  negative prompt (Wan's official one) did not cause the bars.
- **The same render showed a pan turning into a walk towards the camera, and a woman floating up
  past the hut** (shots 9 and 5) when the keyframe showed her facing the camera on a path and the
  movement asked her to walk "across the frame". Walking only works when the picture already shows
  the person side-on.

### More from the Lion's Whisker v2 keyframes (ours)

- **Naming a character twice draws them twice.** "Also in the shot: the lion. A large lion…"
  after a visual that already placed the lion gave two lions in one shot (and two elders when the
  storyboard listed the elder in a shot whose visual did not show him). Wording the description
  as the one already in the picture ("The lion appears exactly once in the picture: …") and
  rejecting `others` the visual does not name fixed both, though one shot still needed its visual
  rewritten to place the lion "far behind her, small in the distance".
- **People outside the cast default to light skin and Western clothes.** A husband described only
  by age, hair and a gabi came out as a light-skinned man in a blazer; adding "Ethiopian, dark
  brown skin" fixed it.
- **Close-ups without a reference picture drift in age.** Almaz (about thirty) came out about
  forty in two close-up draws; a medium shot kept her consistent.
- **Two people side by side get matched in size.** Dawit (about eight) came out as a teenager
  or an adult when sitting beside Almaz on a bench, until the visual said "a small eight-year-old
  boy whose head reaches only her shoulder".

## What this means for the prompts

| Finding | Rule |
|---|---|
| klein weighs the start of the prompt most | Storyboard visuals start with shot size and subject; the keyframe prompt puts the shot, then the cast, then the setting, then the look |
| klein has no negative prompt | Solo shots and people counts are stated positively ("exactly one person… nobody else") |
| Stray and duplicated people (klein, and Wan's own negative lists "many people in the background") | The storyboard records how many people are in each shot; every keyframe prompt states it |
| A description is needed in every image for consistency | Every bible character in a shot gets their description in the keyframe prompt, not just the main one |
| The storyboard invents clothes | The storyboard sees each character's description and refers to cast members by name instead of re-describing them |
| Skin tone and anatomy drift, bias warning | Bible descriptions should lead with age, skin tone and build; the README says so |
| Wan should hear what moves and how the camera moves; but the 5B invents objects without the scene described, and acts out prohibitions (our A/B) | The storyboard writes a separate `movement` for each shot; the Wan prompt is the visual, then the movement, then one camera sentence, with no "nothing appears" sentence |
| Wan is weak at hands, faces in motion, multi-person interaction, walking | Movement rules: one slow movement, no hand work, no talking, no two people touching, walking only across the frame |
| One camera move per clip; a pan drifts into a push-in | One camera sentence per motion type, with motion-specific negative terms (no zoom for a pan, no camera movement for ambient) |
| Official Wan negative prompt | Shipped as the workflow default, plus morphing and flicker terms |
| A push-in on a close-up ends too tight | Push-in only on medium and wide shots |
| A character named twice is drawn twice | The other characters' descriptions say each "appears exactly once in the picture"; a shot may list in `others` only characters its visual names |
| People outside the cast come out light-skinned in Western clothes | The storyboard describes them in full: age, skin tone, hair, period clothes |
