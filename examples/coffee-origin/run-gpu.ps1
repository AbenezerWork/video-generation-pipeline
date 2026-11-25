param(
    [Parameter(Mandatory)]
    [string[]] $VidpipeArgs,
    [string] $ComfyUrl = 'http://127.0.0.1:8188',
    [string] $LockPath = "$env:USERPROFILE\.t3\vidpipe-deps\integration-gpu.lock"
)

$ErrorActionPreference = 'Stop'

# The GPU lock is the same cross-platform OS file lock (filelock) vidpipe takes per project;
# run_gpu.py waits for it and for an idle ComfyUI queue, then runs the command. On another OS,
# run `uv run --locked python examples/coffee-origin/run_gpu.py -- <vidpipe arguments>`.
$guard = Join-Path $PSScriptRoot 'run_gpu.py'
uv run --locked python $guard --comfy-url $ComfyUrl --lock $LockPath -- @VidpipeArgs
exit $LASTEXITCODE
