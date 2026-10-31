$ErrorActionPreference = 'Stop'
$dubRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'local-test-env.ps1')
$basePython = 'D:\OmniVoice\venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $basePython)) { $basePython = (Get-Command python.exe).Source }
$venv = Join-Path $dubRoot 'backend\.venv'
if (-not (Test-Path -LiteralPath (Join-Path $venv 'Scripts\python.exe'))) { & $basePython -m venv $venv }
$dubPython = Join-Path $venv 'Scripts\python.exe'
$dubUv = 'D:\OmniVoice\tools\uv.exe'
if (Test-Path -LiteralPath $dubUv) {
    $env:UV_CACHE_DIR = Join-Path $dubRoot '.cache\uv-web'
    & $dubUv pip install --python $dubPython -r (Join-Path $dubRoot 'backend\requirements.txt')
} else {
    & $dubPython -m ensurepip --upgrade
    & $dubPython -m pip install -r (Join-Path $dubRoot 'backend\requirements.txt')
}
if ($LASTEXITCODE -ne 0) { throw 'Cài backend thất bại.' }
Push-Location (Join-Path $dubRoot 'frontend')
try {
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'Cài frontend thất bại.' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Build frontend thất bại.' }
} finally { Pop-Location }
Write-Host 'Sẵn sàng. Chạy scripts\start.ps1.'
