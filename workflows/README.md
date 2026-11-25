# Keyframe workflows (ComfyUI, API format)

Decision and measurements: [`docs/adr/0001-keyframe-model.md`](../docs/adr/0001-keyframe-model.md).

Three variants of one graph: FLUX.2 [klein] 4B fp8 (distilled, 4 steps) with native ComfyUI nodes, no custom node. They were built from ComfyUI's template `image_flux2_klein_image_edit_4b_distilled` (ComfyUI 0.46.3) with the subgraphs flattened, and with the output size set explicitly instead of inherited from the first reference. Each file was submitted to `POST /prompt` as saved and ran successfully.

| File | Reference images | Use |
|---|---|---|
| `keyframe_flux2_klein_4b_t2i.json` | 0 | Reference-free keyframe, and the character reference sheet itself |
| `keyframe_flux2_klein_4b_ref1.json` | 1 | Shot with one bible reference (the character) |
| `keyframe_flux2_klein_4b_ref2.json` | 2 | Shot with the character plus a location/style reference |

Load a file as JSON, set the fields below, and `POST` it as `{"prompt": <json>}`. The provider can strip the `_meta` keys; ComfyUI ignores them.

vidpipe does this from `keyframe_flux2_klein_4b.mapping.yaml`, the machine-readable form of the table below.

## Mapping files

`<name>.mapping.yaml` describes one model: which workflow to run, what to write into it, where the result comes out. `vidpipe.comfy.workflow` loads and checks it. A new model for an existing provider is a workflow plus a mapping, with no Python. Unknown keys are errors.

| Key | Meaning |
|---|---|
| `name` | The model's name. |
| `variants` | List of `{images: N, workflow: file.json}`: the API-format workflow for N input images (path relative to the mapping). |
| `images` | `<node>.inputs.<input>` for input image 1, 2, ...: gets the name `POST /upload/image` returned. |
| `fields` | Value name → list of node inputs it is written to. A node a variant lacks is skipped for that variant. Each listed input must exist in some variant, and the provider's required values in every variant. |
| `outputs` | `{node: save, key: images}`: where `/history` lists the result files (`key` defaults to `images`, which video saves use too; audio saves use `audio`). |
| `settings` | Default values for fields; a project overrides them with `options: {settings: {...}}`. |
| `oom_step_down` | Ordered list; each entry is `{set: {field: lower value, ...}}` or `{smaller_size: [[w, h], ...]}`. See below. |
| `timeout_s` | Limit per job, queueing included (default 600). |
| `capabilities` | The contract's capability fields (keyframer: `min_width`, `min_height`, `max_width`, `max_height`, `max_pixels`, `width_multiple`, `height_multiple`; the reference count comes from `variants`). |
| `cost` | `{unit: call or output_second, gpu_minutes: ...}`, used by `vidpipe plan`. |
| `requires` | `{comfyui: version, custom_nodes: [...], models: [folder/file, ...]}`: what must be installed. |

Values a provider writes: `seed`, `filename_prefix` (map it to the save node, so each job's output is a new file), and its own (keyframer: `prompt`, `width`, `height`).

Editing a workflow, `images`, `fields`, `outputs` or `settings` regenerates the artifacts made with the mapping; editing capabilities, cost, timeout or the ladder does not.

## Field mapping

Node ids are stable names. Fields are `<node id>.inputs.<input>`.

| Meaning | Field | Notes |
|---|---|---|
| Prompt (English) | `text.inputs.text` | Strip leading/trailing whitespace: trailing spaces change the output. Refer to references as "image 1", "image 2" (order of the reference slots). There is no negative prompt: `neg0` zeroes the positive, so describe wanted things only. |
| Seed | `noise.inputs.noise_seed` | Same inputs + same seed gives a bit-identical image. |
| Width | `latent.inputs.width` **and** `sched.inputs.width` | Set both to the same value. Must be a multiple of 16. |
| Height | `latent.inputs.height` **and** `sched.inputs.height` | Set both to the same value. Must be a multiple of 16 (360 is silently rounded down to 352). |
| Reference image 1 (character) | `ref1_load.inputs.image` | File name as returned by `POST /upload/image` (`name` field), or a file already in ComfyUI's input folder. Present in the `ref1` and `ref2` files. |
| Reference image 2 (location/style) | `ref2_load.inputs.image` | `ref2` file only. |
| Reference size | `ref1_scale.inputs.megapixels`, `ref2_scale.inputs.megapixels` | Default 0.5. Lower is faster and uses less memory; 0.25 still kept the character. |
| Steps | `sched.inputs.steps` | 4. The model is distilled; do not raise it. |
| Output | `save.inputs.filename_prefix` → node `save` | Fetch with `GET /history/{prompt_id}`: `outputs.save.images[0]` (`filename`, `subfolder`, `type`), then `GET /view?filename=...&subfolder=...&type=...`. |

Fixed inputs (leave alone): `unet` = `flux-2-klein-4b-fp8.safetensors`, `clip` = `qwen_3_4b.safetensors` with `type: flux2`, `vae` = `flux2-vae.safetensors`, `guider.cfg` = 1.0, `sampler` = `euler`. Do not set `clip.device` to `cpu` (25–48 s per prompt and RAM exhaustion).

Defaults in the files: 832x480, reference size 0.5 MP, seed 0, prompt `PROMPT`, placeholder reference names `character_ref.png` / `location_ref.png`.

More than two references: the graph is a chain, so add another `refN_load`, `refN_scale`, `refN_enc`, `refN_pos`, `refN_neg` group, wiring `refN_pos` from the previous `pos` and `refN_neg` from the previous `neg`, and point `guider.positive`/`guider.negative` at the last pair. Three references at 1280x720 and 1 MP ran in 28 s with no OOM.

## Resolution and OOM fallback list

Output sizes, in order (all multiples of 16, 16:9):

| Step | Size | Time with one 0.5 MP reference |
|---|---|---|
| default | 832x480 | ~6.5 s |
| sharper | 1024x576, then 1280x720 | ~7.4 s, ~9.2 s |
| smaller | 640x352 | ~5.7 s |

No OOM, hang or crash occurred in about 60 runs, up to 1280x720 with three 1 MP references. The ladder is precautionary: it has been exercised only against the fake ComfyUI server in the tests, **never** by a real out-of-memory error.

What vidpipe does when a job fails with an out-of-memory error (`vidpipe.comfy.jobs`):

1. `POST /free` with `{"unload_models": true, "free_memory": true}`.
2. Apply **one** step-down: the first `oom_step_down` entry that lowers something for this job (a `set` entry applies when it raises nothing and lowers at least one value; `smaller_size` picks the largest listed size that is no wider, no taller and smaller). For these mappings: reference size 0.5 → 0.25 MP; with no reference, or already at 0.25, the output size down one step (832x480 → 640x352).
3. Retry with a new seed (this attempt does not count against the 2 ordinary retries). A second out-of-memory error, or no applicable entry, fails the job. The step-down is recorded in the artifact's `fallback`.

Not implemented from the spike's suggested ladder: dropping the second reference (only one step is ever applied, so it would never be reached with the default settings). Flux Kontext GGUF and SDXL + IP-Adapter were queued as model fallbacks but were not downloaded or tested.
