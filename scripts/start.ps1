param([switch]$Development, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$dubRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'local-test-env.ps1')
$apiPython = Join-Path $dubRoot 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $apiPython)) { throw 'Chạy scripts\setup.ps1 trước.' }
$env:PYTHONPATH = Join-Path $dubRoot 'backend'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
$logDir = Join-Path $dubRoot 'data\logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
if (-not $Development -and -not (Test-Path -LiteralPath (Join-Path $dubRoot 'frontend\dist\index.html'))) {
    Push-Location (Join-Path $dubRoot 'frontend')
    try { & npm.cmd run build; if ($LASTEXITCODE -ne 0) { throw 'Không build được frontend.' } } finally { Pop-Location }
}
$processes = @()
try { $existing = Invoke-RestMethod 'http://127.0.0.1:8765/api/health' -TimeoutSec 2 } catch { $existing = $null }
if (-not $existing) {
    $p = Start-Process -FilePath $apiPython -ArgumentList '-m','uvicorn','dubflow.app:app','--host','127.0.0.1','--port','8765' -WorkingDirectory $dubRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'api.out.log') -RedirectStandardError (Join-Path $logDir 'api.err.log') -PassThru
    $processes += @{ id=$p.Id; started_epoch=([DateTimeOffset]$p.StartTime).ToUnixTimeSeconds(); kind='api' }
    $ready = $false
    for ($attempt=0; $attempt -lt 40; $attempt++) {
        try { $null = Invoke-RestMethod 'http://127.0.0.1:8765/api/health' -TimeoutSec 1; $ready=$true; break } catch { Start-Sleep -Milliseconds 250 }
    }
    if (-not $ready) { throw "API chưa mở được. Xem $logDir\api.err.log." }
} else {
    # Reattach only a Python launcher whose command identifies this workspace.
    $listener = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
        $server = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($server.ParentProcessId)"
        $owner = if ($parent.CommandLine -like "*$dubRoot*" -and $parent.CommandLine -like '*dubflow.app:app*') { $parent } elseif ($server.CommandLine -like "*$dubRoot*" -and $server.CommandLine -like '*dubflow.app:app*') { $server } else { $null }
        if ($owner) {
            $p = Get-Process -Id $owner.ProcessId
            $processes += @{ id=$p.Id; started_epoch=([DateTimeOffset]$p.StartTime).ToUnixTimeSeconds(); kind='api' }
        }
    }
}
$url = 'http://127.0.0.1:8765'
if ($Development) {
    $vite = Join-Path $dubRoot 'frontend\node_modules\vite\bin\vite.js'
    $nodeExe = (Get-Command node.exe).Source
    $p = Start-Process -FilePath $nodeExe -ArgumentList "`"$vite`"",'--host','127.0.0.1','--port','5173','--strictPort' -WorkingDirectory (Join-Path $dubRoot 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'frontend.out.log') -RedirectStandardError (Join-Path $logDir 'frontend.err.log') -PassThru
    $processes += @{ id=$p.Id; started_epoch=([DateTimeOffset]$p.StartTime).ToUnixTimeSeconds(); kind='frontend' }
    $url = 'http://127.0.0.1:5173'
}
$stateFile = Join-Path $dubRoot 'data\servers.json'
if (Test-Path -LiteralPath $stateFile) { $processes += @((Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json) | ForEach-Object { $_ } | Where-Object { $null -ne $_.id }) }
ConvertTo-Json -InputObject @($processes) | Set-Content -LiteralPath $stateFile -Encoding utf8
Write-Host "DubFlow: $url"
Write-Host "Log: $logDir"
if (-not $NoBrowser) { Start-Process $url }
