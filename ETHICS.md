# Ethics, consent and licences

Covers the pipeline and the submitted film, *The Lion's Whisker* (Amharic, 16:9 and
9:16). Terms and licence tags were read on **26 November 2026** unless noted. This is
a good-faith record, not legal advice.

**AI provenance.** vidpipe makes films from a written brief and project files.
Depending on the providers chosen, AI generates the script, translations, storyboard,
voice, images, motion and score. An edited `storyboard.json` can supply the text and
picture prompts instead. The sample project uses deterministic fake providers. The
project config names the providers, and the build ledger and `runs.jsonl` record the
calls, seeds and settings. <!-- verify after merge: storyboard.json, runs.jsonl -->

## 1. Consent record

| Question | Answer |
|---|---|
| Does a real person's face appear? | No |
| Is a real person's likeness used as a reference? | No. No reference pictures: the keyframe records for both cuts list none |
| Is a real person's voice used or cloned? | No. Stock synthetic voices only |
| Is a real person named in the script or prompts? | No |
| Does the film tell a private family story? | No. It retells a traditional folk tale |
| Consent forms required | None, because no real person is shown or voiced |

All characters (Almaz, her husband, Dawit, the wise elder, the lion) are fictional.
They exist as short written descriptions in the project bible. No prompt asked for a
celebrity, a public figure or "in the style of" anyone.

A generated face can still resemble someone by chance. The frames were reviewed and no
recognisable person was seen. Anyone who believes a character closely resembles them
can ask for the shot to be redrawn.

Owner's confirmation of this record: Abenezer Workineh, 26 November 2026.

## 2. The story and its culture

- *The Lion's Whisker* is a traditional Ethiopian folk tale told in many versions. Our
  script was written fresh from its outline, with our own character names. No published
  text was adapted, and we do not claim the tale as invented.
- It is presented as folklore ("long ago"), not history.
- The stepmother is the patient, loving figure, and the boy's distance is treated as
  grief, not malice.
- The wise elder refuses to sell a potion. He is not a caricature of a healer.
- Dawit is a fictional child, shown only in ordinary family scenes.
- No real animal was involved. The lion stays calm and on four legs. A woman
  hand-feeding a wild lion is the tale's image, not advice.
- Clothing, houses and the hermitage are plausible, not authoritative. The image model
  knows Ethiopian detail only approximately, and Almaz's top changes in the last shot.
- No native speaker has reviewed the Amharic narration, subtitles or end card.

## 3. Models, voices and outputs: licences

| Component | Used for | Licence or terms | What it means for the output |
|---|---|---|---|
| [FLUX.2 klein 4B fp8](https://huggingface.co/black-forest-labs/FLUX.2-klein-4b-fp8) | keyframes | Apache 2.0 (model card) | commercial use allowed; the card's acceptable-use limits apply |
| FLUX.2 VAE, `flux2-vae.safetensors` from the [Comfy-Org repack](https://huggingface.co/Comfy-Org/flux2-dev) | keyframes | that repository is tagged **`flux-1-dev-non-commercial-license`** | **unresolved**: see below |
| [Qwen3-4B](https://huggingface.co/Qwen/Qwen3-4B) text encoder (ComfyUI repack) | keyframes | Apache 2.0 | none beyond the licence |
| [Wan 2.2 TI2V 5B](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B), [QuantStack GGUF](https://huggingface.co/QuantStack/Wan2.2-TI2V-5B-GGUF) | video | Apache 2.0 | the card claims no rights over generated content; users answer for lawful use |
| Wan 2.2 VAE and [umt5-xxl](https://huggingface.co/google/umt5-xxl) encoder | video | Apache 2.0 (the VAE tag is from our dependency notes of 25 November) | none beyond the licence |
| [ACE-Step 1.5](https://huggingface.co/ACE-Step/Ace-Step1.5) Turbo | music | MIT; the [ComfyUI repack](https://huggingface.co/Comfy-Org/ace_step_1.5_ComfyUI_files) we load is tagged Apache 2.0 | the model card allows commercial use of generated music; the project asks users to disclose AI involvement and check originality |
| Microsoft Edge TTS via [`edge-tts`](https://github.com/rany2/edge-tts) | narration | library: LGPLv3 (one file MIT). The voice is Microsoft's online service, reached through an **unofficial** library | no licence to reuse the audio was found; see below |
| Addis Voices 2 | narration in one coffee test run only, not the film | service terms; the docs page states a price and no licence for audio | do not publish that audio commercially without checking |
| Claude, through Claude Code CLI | script, translation, back-check, storyboard | [Anthropic Consumer Terms](https://www.anthropic.com/legal/consumer-terms) (effective 8 October 2025) | outputs are assigned to the user; see below |
| Codex CLI | text in the coffee demos only, not the film | [OpenAI Terms of Use](https://openai.com/policies/terms-of-use/) (effective 1 January 2026) | user owns the output; see below |
| Gemini CLI | never run for real | | |

### Open licence points

1. **FLUX.2 VAE.** The klein 4B model is Apache 2.0, but the VAE file we load comes from
   a repackaged repository tagged non-commercial. The klein 4B card says nothing about
   that file. The klein 4B repository also holds its own
   [VAE folder](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B/tree/main/vae)
   under its Apache 2.0 tag, in another format that we have not tested. **Treat
   commercial use of the keyframes as unsettled until this is resolved.** The film is
   non-commercial.
2. **Edge TTS.** It uses Microsoft Edge's read-aloud service outside Edge. We found no
   clause in the [Microsoft Services Agreement](https://www.microsoft.com/en-us/servicesagreement)
   (effective 30 September 2026) that grants this use or the reuse of the audio, and we
   did not read the whole agreement word for word. Fine for a personal demo; for
   anything commercial, re-voice with a licensed service. The pipeline supports Addis
   Voices 2 today (after checking its terms). It has no Azure Speech provider, although
   an earlier note on a demo film suggested one.
3. **Automated CLI use.** vidpipe calls these CLIs non-interactively. Anthropic's
   consumer terms bar access "through automated or non-human means" except with an API
   key or where explicitly permitted. OpenAI's bar automatically or programmatically
   extracting output. Both vendors ship a non-interactive mode, but we have not
   confirmed that it counts as permission under these terms. **The owner should check
   before wider use**, or switch to an API key.

## 4. Fonts and software

| Item | Licence | Shipped in this repo |
|---|---|---|
| Noto Sans Ethiopic (subtitles, end card) | SIL OFL 1.1 | yes, with [`OFL.txt`](assets/fonts/OFL.txt) |
| Mona Sans (UI) | SIL OFL 1.1 | yes, with its licence |
| JetBrains Mono (UI) | SIL OFL 1.1 | yes, with its licence |
| ComfyUI, ComfyUI-GGUF, FFmpeg (Gyan essentials build) | their own open-source licences, not re-checked for this record | no; installed separately |

This repository has no licence file of its own. Choosing one is the owner's decision.

## 5. Labelling plan

| Layer | What | Status |
|---|---|---|
| In the picture | a 5 s end card: Amharic text saying the video is AI-generated and any resemblance is coincidental, with "AI-generated video" in English | in both delivered cuts |
| On the platform | switch on the AI or "altered content" label when posting, on every platform used | not posted yet |
| In the text of the video | the end card states in Amharic and English that the film is AI-generated, so the disclosure travels with the file wherever it is shared, whatever the post says | in both delivered cuts |
| In the file | MP4 metadata: the film's title, and a comment and description reading `AI-generated with vidpipe; see ETHICS.md` | written by assembly in new renders **Not present** in the delivered files checked on 26 November: re-run assembly and check with `ffprobe -show_format` |

We remove no watermark or provenance mark. The pipeline adds none of its own, and we
have not checked whether the local models' outputs carry any.

## 6. Private data

| Goes to | What is sent | When |
|---|---|---|
| Anthropic (Claude CLI) | the brief, script, translation and storyboard text | script, translation, storyboard |
| Microsoft (Edge TTS) | narration lines | narration |
| OpenAI (Codex CLI) | the coffee story's text | coffee demos only |
| Addis AI | Amharic coffee narration lines | one coffee test run |
| Nobody | images, video, music, the final edit | generated and assembled on the local GPU and machine |

- Only the folk tale was sent. No family details or personal data went into any prompt.
- Anthropic's consumer terms allow training on content unless you opt out in account
  settings, and OpenAI's have a similar opt-out. Owner's settings: model
  training is switched off in both the Anthropic and the OpenAI account.
- Keys are read from the environment (`ADDIS_API_KEY`). `.env` files are ignored by git,
  and the call log leaves out options that look like secrets.
 
- vidpipe never stores or handles CLI credentials. The UI listens on this machine only
  unless asked otherwise, and then requires a token.

## 7. Environmental cost

Both cuts took about 1.5 hours of consumer-GPU time on one 8 GB card
([COSTS.md](COSTS.md)).

## 8. Before any commercial release

1. Resolve the FLUX.2 VAE licence.
2. Re-voice through a licensed speech service.
3. Check the CLI terms, or use API keys.
4. Have a native speaker review the Amharic.
5. Re-read every licence above; they change.
