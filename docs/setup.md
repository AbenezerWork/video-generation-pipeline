# Set up vidpipe

Use Python 3.12 or later and run `uv sync --locked` from the checkout. The sample project uses fake
providers. A project with real providers needs the dependencies for its selections in `vidpipe.yaml`.

```sh
uv run vidpipe doctor
uv run vidpipe doctor examples/sample
uv run vidpipe doctor path/to/project
```

Without a path, doctor uses the current directory's `vidpipe.yaml` when present. Outside a project it
checks the English/Amharic setup with Gemini and Claude, Edge TTS, and FLUX.2 keyframes. For a
project it checks the configured text executables (including text fallbacks), subtitle fonts, and
the workflow mappings and server URLs used by configured ComfyUI providers. Doctor reports
configuration and dependency failures with exit status 1, or exits 0 when every check passes.
It queries ComfyUI's version and catalogs over HTTP. Model checks confirm the listed files are
visible to the server. Sign-in, model contents, service quotas, and generation are outside these
checks.

## FFmpeg and fonts

Use a build of [FFmpeg](https://ffmpeg.org/download.html) that includes `ffprobe`, libass (the
`subtitles` filter), `sidechaincompress`, and the `libx264` encoder. Set `VIDPIPE_FFMPEG_DIR`
to the directory containing both binaries. The media tests use the same setting. If the variable
is unset, vidpipe looks on `PATH`.
On the Windows development machine the dependency tracker already provides the Gyan FFmpeg 9.1
essentials build. To use it in this PowerShell session:

```powershell
$env:VIDPIPE_FFMPEG_DIR = Join-Path $env:USERPROFILE '.t3\vidpipe-deps\ffmpeg\ffmpeg-9.1-essentials_build\bin'
uv run vidpipe doctor
```

Noto Sans Ethiopic Regular and Bold are bundled for Amharic subtitles. Vidpipe looks for fonts in
`subtitles.fonts_dir` if specified, then a project `fonts/` directory if present, otherwise the
bundled fonts. When using a custom folder, include each family named in `subtitles.fonts` for the
languages being rendered. `subtitles.burn_in: false` disables the font check and keeps the SRT
sidecar.

## Text and narration

Install and sign in to each CLI selected by the project. The default text chain uses Gemini CLI and
Claude Code. Codex CLI is also selectable. Use `options.command` on the provider entry to specify an
absolute executable path. Launch each CLI interactively once to complete its sign-in. Check the
vendor's terms for automated CLI use.

`uv sync --locked` installs `edge-tts`. Narration with this provider needs internet access.
English uses `en-US-AriaNeural` by default and Amharic uses `am-ET-AmehaNeural`. Set
`providers.narration.options.voices.am` to `am-ET-MekdesNeural` to choose the other Amharic voice.

## ComfyUI

The [Coffee Highlands example](../examples/coffee-origin/README.md) uses the pinned
workflows below to render a real-provider bilingual demo.

Start [ComfyUI v0.46.3](https://github.com/Comfy-Org/ComfyUI/releases/tag/v0.46.3) separately.
The reference installation uses ComfyUI frontend `1.59.6` and workflow templates `0.11.118`.
Vidpipe connects to `http://127.0.0.1:8188` by default. Set `comfyui.url` in the project or
`options.url` on a provider for a different server.

| Workflow | Nodes and pins |
| --- | --- |
| FLUX.2 [klein] 4B fp8 keyframes | Native ComfyUI 0.46.3 nodes, including `ReferenceLatent` and `Flux2Scheduler`. |
| Wan 2.2 TI2V 5B GGUF video (ticket 11) | Native ComfyUI 0.46.3 nodes including `Wan22ImageToVideoLatent`, plus [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF) at `6ea2651e7df66d7585f6ffee804b20e92fb38b8a` with `gguf==0.19.0`. |
| ACE-Step 1.5 turbo music (ticket 13) | Native ComfyUI 0.46.3 nodes including `TextEncodeAceStepAudio1.5` and `EmptyAceStep1.5LatentAudio`. |

For Wan, check out the pinned ComfyUI-GGUF revision under ComfyUI's `custom_nodes/ComfyUI-GGUF/`,
install `gguf==0.19.0` with ComfyUI's own Python, and restart it so `UnetLoaderGGUF` is loaded.

Place the files below under the server's `models/` directory or a matching
`extra_model_paths.yaml` location. On the Windows development machine the shared model folder is
`%LOCALAPPDATA%\Comfy-Desktop\ComfyUI-Shared\models`. Its download status and SHA-256 verification
are tracked in `%USERPROFILE%\.t3\vidpipe-deps\dependencies.md` and `status.json`.

| Workflow | File relative to `models/` | Download source |
| --- | --- | --- |
| Keyframes | `diffusion_models/flux-2-klein-4b-fp8.safetensors` | [Black Forest Labs FLUX.2 klein 4B fp8](https://huggingface.co/black-forest-labs/FLUX.2-klein-4b-fp8/blob/5b4408e5/flux-2-klein-4b-fp8.safetensors) |
| Keyframes | `text_encoders/qwen_3_4b.safetensors` | [Comfy-Org Z-Image Turbo](https://huggingface.co/Comfy-Org/z_image_turbo/blob/main/split_files/text_encoders/qwen_3_4b.safetensors) |
| Keyframes | `vae/flux2-vae.safetensors` | [Comfy-Org FLUX.2](https://huggingface.co/Comfy-Org/flux2-dev/blob/main/split_files/vae/flux2-vae.safetensors) |
| Video | `unet/Wan2.2-TI2V-5B-Q5_K_M.gguf` | [QuantStack Wan 2.2 TI2V](https://huggingface.co/QuantStack/Wan2.2-TI2V-5B-GGUF/blob/57437632/Wan2.2-TI2V-5B-Q5_K_M.gguf) |
| Video | `text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors` | [Comfy-Org Wan 2.1](https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/blob/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors) |
| Video | `vae/wan2.2_vae.safetensors` | [Comfy-Org Wan 2.2](https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/blob/main/split_files/vae/wan2.2_vae.safetensors) |
| Music | `checkpoints/ace_step_1.5_turbo_aio.safetensors` | [Comfy-Org ACE-Step 1.5](https://huggingface.co/Comfy-Org/ace_step_1.5_ComfyUI_files/blob/371bb168/checkpoints/ace_step_1.5_turbo_aio.safetensors) |

The video and music rows record the dependency tracker selections for those tickets. For any
configured workflow, doctor reads the required model files and version from its mapping and
verifies the node classes used by its graphs. Custom workflow mappings follow the same
[mapping format](../workflows/README.md#mapping-files).
