# 0001: Keyframes use FLUX.2 [klein] 4B fp8 with reference images

Status: accepted (spike, ticket 09). Date: 2026-11-25.

## Decision

Keyframes are generated with **FLUX.2 [klein] 4B, fp8, distilled**, through ComfyUI's native nodes, conditioned on bible reference images (`ReferenceLatent`).

- **Models:** `flux-2-klein-4b-fp8.safetensors` (4.07 GB), text encoder `qwen_3_4b.safetensors` (8.04 GB, `CLIPLoader` type `flux2`), VAE `flux2-vae.safetensors`. Licence per the dependency tracker: Apache-2.0 for the klein 4B model.
- **Workflow:** 4 steps, euler, `CFGGuider` cfg 1.0, negative conditioning is the positive zeroed out. No custom node. Files and field mapping: [`workflows/`](../../workflows/README.md).
- **Default output size:** 832x480 (matches the 480p-class video stage). 1024x576 and 1280x720 are available when a sharper keyframe is needed.
- **References:** the bible's character reference image goes in as `image 1`, an optional location/style reference as `image 2`, each scaled to 0.5 megapixels. Prompts are English and refer to "image 1", "image 2".
- **Cost per keyframe (measured, new prompt each time):** about 6–7 s at 832x480 with one reference, about 9 s with two. Peak GPU memory about 7.0 GB of 8.2 GB.

The reference-conditioned workflow ran reliably on this machine (RTX 4060 Laptop 8 GB, 31 GB RAM) and kept the character recognisable across every shot tried. No fallback model is needed for the demo.

## What was tested

Harness: a throwaway Python script that submitted API-format graphs to ComfyUI 0.46.3 (torch 2.12.1+cu130, built-in dynamic offload, no `--lowvram`), polled `nvidia-smi` and `/system_stats` every 0.3 s, and took the server's own execution timestamps. About 60 jobs, one at a time. GPU idle baseline was 0 MiB. Outputs were looked at one by one.

Not tested: Flux Kontext GGUF and SDXL + IP-Adapter (queued as fallbacks, never downloaded), the `qwen_3_4b_fp8_mixed` text encoder, a style LoRA, Amharic prompts, text rendered inside images, step counts other than 4, and ComfyUI restarts.

### Time and GPU memory

`exec` is ComfyUI's execution time (`execution_start` to `execution_success`) for a prompt not seen before, so it includes text encoding and model swaps. Peak memory is `nvidia-smi` memory used, which includes the allocator's cache; the true need is lower. All runs used 4 steps and succeeded. Host free RAM was 10 GB for this table.

| Size | No reference | 1 ref at 0.5 MP | 1 ref at 1.0 MP | Peak GPU memory |
|---|---|---|---|---|
| 640x352 | 4.1 s | 5.7 s | 7.8 s | 7.0 GB |
| **832x480** | **4.5 s** | **6.5 s** | **8.7 s** | 7.0–7.1 GB |
| 1024x576 | 5.2 s | 7.4 s | 9.8 s | 7.0–7.1 GB |
| 1280x720 | 6.6 s | 9.2 s | 11.7 s | 7.1–7.2 GB |

Other measurements:

- **Text encoding dominates small jobs.** With the same prompt as the previous job (ComfyUI reuses the cached conditioning) 832x480 took 2.0 s without a reference. The 8 GB bf16 text encoder cannot stay on the GPU next to the diffusion model, so each new prompt swaps it in.
- **Host RAM matters.** Earlier in the session other programs left only about 4 GB of RAM free; the same jobs then took 3–5 s longer (832x480 with a 1.0 MP reference: 10.8–11.9 s; no reference: 7.4 s). A single run after the server had been idle took 14.3 s.
- **Cold reload.** After `POST /free` (unload models) the next job took 8.9 s instead of 6.4 s. The disk cache was warm, so a truly cold start will be slower.
- **More references cost more.** 1280x720, two 1.0 MP references: 18.9 s. Three 1.0 MP references: 28.1 s. Two 2.0 MP references: 37.4 s, 7.5 GB peak. All succeeded.
- **Text encoder on CPU is not viable.** `CLIPLoader` device `cpu` took 25–48 s per prompt and drove free RAM to 0.0 GB.
- **Height must be a multiple of 16.** 640x360 was silently produced as 640x352. 832x480, 1024x576 and 1280x720 are fine.

### Stability

- **Same seed reproduces.** Identical inputs gave bit-identical pixels in four pairs: three resolutions without a reference, and one with a reference. The PNG files differ in metadata only. Not checked across a ComfyUI restart.
- **Prompt whitespace changes the image.** Adding trailing spaces changed the output (different image, same seed). The provider must strip prompts to keep re-rolls and cache keys deterministic.
- **No OOM, hang, crash or ComfyUI restart** in about 60 jobs, including a 10-shot sequence with a new prompt each (6.1–6.2 s each after the first, flat, no drift) and the 3-reference and 2 MP stress runs.
- **The fallback ladder was never triggered**, so it is untested as a recovery path.

### Character consistency

Reference: a painterly character sheet of a placeholder protagonist (a ten-year-old girl in a highland village, indigo dress, yellow shawl, braids with a red ribbon, satchel), generated from a text prompt with the same model at 1280x720 (4–10 s; three seeds tried, one kept). See `assets/01-character-reference-sheet.jpg`.

**Verdict: good enough to build on.** Looking at the images:

- **Five hand-written shots** (wide from behind on a path, doorstep medium shot, sunset profile close-up, firelit interior, market square): the same girl each time. Face shape, braids, red ribbon, indigo dress, yellow shawl and satchel carry over across framings, locations and lighting. `assets/02-five-shots-from-reference.jpg`.
- **Ten further shots** with new prompts at 0.5 MP: the same, with small drifts. `assets/03-ten-shot-soak-832x480.jpg`.
- **Resolution and reference size hold up.** 640x352 and a 0.25 MP reference still produced the same character.
- **Without the reference, it does not.** The same prompt with the outfit described in words gave a different girl: long skirt, dark shoes, a red bow at the collar, the shawl worn as a cape. `assets/05-text-only-vs-with-reference.jpg`. This is the case for passing the image and using the bible text only for providers that cannot take images.

Drifts and defects seen:

- **Duplicated character:** 1 of the 10 shots (the cave and lantern prompt) drew two girls. Nothing in the generation reports this, so it has to be caught at the keyframes gate and fixed with a per-shot re-roll (new seed).
- **Scene drift:** the rooftop-at-night shot became a modern town, and the market shot a European-looking square with tiled roofs. A highland village has to be in the prompt or in a location reference.
- **Small attribute drift:** the ribbon disappears when it faces away from the camera, the satchel strap switches shoulder, shawl fringe and pattern vary, and the close-up profile made her look a little older than in the wide shots.
- **Background style leakage:** the shots with painterly watercolour backgrounds matched the sheet. The 2-reference shots took on the location image's softer semi-realistic style.

### Second reference (location/style)

The workflow supports it (`ref2` file). In three shots the character stayed recognisable and the location was reproduced faithfully, close to verbatim: the composition and the houses came across too, so the new shot looks like the character was pasted into the reference scene. `assets/04-second-reference-location.jpg`. Use it for place continuity; a different camera angle on the same place was not tested and will probably need more prompt steering or a second reference image per angle. The style of the location image dominates the style of the character sheet.

### English prompts

English prompts of 60–100 words worked well, including references to "image 1" and "image 2" for the reference slots. There is no negative prompt in this distilled setup (cfg 1.0, zeroed negative), so "no X" phrasing does not work; describe what should be there. Amharic prompts were not tested; the plan is English-only prompts.

## Alternatives considered

| Option | Status |
|---|---|
| FLUX.2 klein 4B fp8 multi-reference edit | **Chosen.** Tested as above. |
| Flux.1 Kontext dev Q4_K_M GGUF (ComfyUI-GGUF) | Queued as a fallback, not downloaded, **not tested**. Single-reference editing, 6.9 GB weights, FLUX.1-dev non-commercial licence; expected (not measured) to be slower than klein on 8 GB. Revisit only if klein regresses. |
| SDXL + IP-Adapter | Queued as a fallback, not downloaded, **not tested**. Expected (not measured) to be the smallest and fastest option but weaker at carrying a stylised character's identity across shots. |

## Risks and known failure modes

- **Licence:** klein 4B is Apache-2.0 per the dependency tracker (not re-verified here). The FLUX.2 VAE comes from a Comfy-Org repack that carries a FLUX non-commercial repo tag; check this before any commercial use. The Kontext fallback is non-commercial.
- **Host RAM:** the text encoder and diffusion model are cached in system RAM (about 12 GB). With about 4 GB free, jobs were 3–5 s slower, and moving the encoder to CPU exhausted RAM. The pipeline should not run other heavy programs, and `doctor` can warn when free RAM is low.
- **GPU memory headroom is small:** 7.0–7.5 GB of 8.2 GB reserved. Keep to one model resident (spec): call `POST /free` between the keyframe stage and the video stage. A cold reload then cost about 2.5 s extra.
- **Quality failure modes (1 in 10 shots had a visible one):** duplicated character, scene drift, minor attribute drift. These are not detected automatically; the keyframes gate and per-shot re-roll are the mitigation.
- **The fallback ladder in `workflows/README.md` is untested** because nothing failed.
- **Measurements are from one machine,** one session, with the disk cache warm.

## Consequences

- Ticket 10 builds the ComfyUI provider on `workflows/keyframe_flux2_klein_4b_*.json` and its field mapping. The `keyframer` contract takes a list of reference images (character first, then location) plus a size and seed, and strips and records the prompt.
- Sizes are multiples of 16; the provider validates this in `plan`.
- Per-shot artifacts should record the references, their megapixel setting, the size and the seed so re-rolls are reproducible.
- The character reference sheet is itself a keyframe-workflow output (no reference, 1280x720, about 6–10 s), so the bible can offer to generate it.

## Evidence

Downsized samples in [`assets/`](assets/). Full-size outputs are not in the repo.

1. `01-character-reference-sheet.jpg`: placeholder protagonist sheet.
2. `02-five-shots-from-reference.jpg`: five shots (and the sheet) side by side.
3. `03-ten-shot-soak-832x480.jpg`: ten consecutive shots, including the duplicate and the scene drifts.
4. `04-second-reference-location.jpg`: location reference and three two-reference shots.
5. `05-text-only-vs-with-reference.jpg`: same scene, left described in words only, right with the reference (same seed, size and style words).
