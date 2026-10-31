$ErrorActionPreference = 'Stop'
$dubRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$stateFile = Join-Path $dubRoot 'data\servers.json'
if (-not (Test-Path -LiteralPath $stateFile)) { Write-Host 'Chưa có tiến trình do start.ps1 lưu lại.'; return }
foreach ($saved in @(Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json)) {
    $process = Get-Process -Id $saved.id -ErrorAction SilentlyContinue
    if (-not $process) { continue }
    $expected = if ($null -ne $saved.started_epoch) { [long]$saved.started_epoch } elseif ($saved.started -is [datetime]) { ([DateTimeOffset]$saved.started).ToUnixTimeSeconds() } else { ([DateTimeOffset]::Parse($saved.started)).ToUnixTimeSeconds() }
    if ([math]::Abs(([DateTimeOffset]$process.StartTime).ToUnixTimeSeconds() - $expected) -gt 2) { continue }
    $details = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)"
    $owned = ($saved.kind -eq 'api' -and $details.CommandLine -like '*dubflow.app:app*') -or ($saved.kind -eq 'frontend' -and $details.CommandLine -like "*$dubRoot*frontend*vite*")
    if ($owned) {
        # Kill only the verified launcher process and its owned model subprocess tree.
        & taskkill.exe /PID $process.Id /T /F | Out-Null
        Write-Host "Đã dừng $($saved.kind). Tác vụ chưa hoàn tất sẽ trở lại hàng đợi khi mở lại."
    }
}
'[]' | Set-Content -LiteralPath $stateFile -Encoding utf8
