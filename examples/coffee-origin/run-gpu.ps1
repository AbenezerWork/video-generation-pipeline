param(
    [Parameter(Mandatory)]
    [string[]] $VidpipeArgs,
    [string] $ComfyUrl = 'http://127.0.0.1:8188',
    [string] $LockPath = "$env:USERPROFILE\.t3\vidpipe-deps\integration-gpu.lock"
)

$ErrorActionPreference = 'Stop'

# File existence is immaterial. Only an open, exclusive handle owns the lock.
while ($true) {
    try {
        $lock = [IO.File]::Open($LockPath, 'OpenOrCreate', 'ReadWrite', 'None')
        break
    } catch [IO.IOException] {
        $win32Code = $_.Exception.HResult -band 0xFFFF
        if ($win32Code -notin 32, 33) { throw }
        Start-Sleep -Seconds 2
    }
}

try {
    do {
        $queue = Invoke-RestMethod -Uri "$($ComfyUrl.TrimEnd('/'))/queue" -TimeoutSec 10
        $busy = ($queue.queue_running.Count + $queue.queue_pending.Count) -gt 0
        if ($busy) { Start-Sleep -Seconds 2 }
    } while ($busy)

    uv run --locked vidpipe @VidpipeArgs
    $status = $LASTEXITCODE
} finally {
    $lock.Dispose()
}
exit $status
