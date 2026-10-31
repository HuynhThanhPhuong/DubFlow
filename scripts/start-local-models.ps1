$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'local-test-env.ps1')
$dubModelsRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dubModelsLogs = Join-Path $dubModelsRoot 'data\logs\local-models'
New-Item -ItemType Directory -Force -Path $dubModelsLogs | Out-Null
$dubModelsState = Join-Path $dubModelsLogs 'server.json'
try { $dubModelsVersion = Invoke-RestMethod 'http://127.0.0.1:11439/api/version' -TimeoutSec 2 } catch { $dubModelsVersion = $null }
if ($dubModelsVersion) {
    if (-not (Test-Path -LiteralPath $dubModelsState)) { throw 'Port 11439 is already occupied by a server without a verified D-drive storage record.' }
    $dubModelsRecord = Get-Content -LiteralPath $dubModelsState -Raw | ConvertFrom-Json
    $dubModelsProcess = Get-Process -Id $dubModelsRecord.pid -ErrorAction SilentlyContinue
    if (-not $dubModelsProcess -or $dubModelsRecord.models -ne $env:OLLAMA_MODELS -or
        [Math]::Abs(([DateTimeOffset]$dubModelsProcess.StartTime).ToUnixTimeSeconds() - $dubModelsRecord.started_epoch) -gt 2) {
        throw 'Existing model server does not match the D-drive storage record.'
    }
    Write-Output "Local model server already running with storage: $env:OLLAMA_MODELS"
    return
}
$dubModelsExe = (Get-Command ollama.exe -ErrorAction Stop).Source
$dubModelsProcess = Start-Process -FilePath $dubModelsExe -ArgumentList 'serve' -WorkingDirectory $dubModelsRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $dubModelsLogs 'server.out.log') -RedirectStandardError (Join-Path $dubModelsLogs 'server.err.log')
for ($dubModelsAttempt = 0; $dubModelsAttempt -lt 40; $dubModelsAttempt++) {
    try {
        $null = Invoke-RestMethod 'http://127.0.0.1:11439/api/version' -TimeoutSec 1
        @{ pid = $dubModelsProcess.Id; started_epoch = ([DateTimeOffset]$dubModelsProcess.StartTime).ToUnixTimeSeconds(); models = $env:OLLAMA_MODELS; log_dir = $dubModelsLogs } |
            ConvertTo-Json | Set-Content -LiteralPath $dubModelsState -Encoding UTF8
        Write-Output "Local model server ready. Models: $env:OLLAMA_MODELS"
        return
    } catch { Start-Sleep -Milliseconds 250 }
    if ($dubModelsProcess.HasExited) { throw "Local model server exited; inspect $dubModelsLogs" }
}
throw "Local model server did not start; inspect $dubModelsLogs"
