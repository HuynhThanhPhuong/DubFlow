param(
    [ValidateSet('start', 'build', 'build-start', 'stop')]
    [string]$Action = 'start',
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$dubRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'local-test-env.ps1')
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$OutputEncoding = [Console]::OutputEncoding
Set-Location -LiteralPath $dubRoot

function Get-DubHealth {
    try { Invoke-RestMethod 'http://127.0.0.1:8765/api/health' -TimeoutSec 2 } catch { return $null }
}

try {
    if ($Action -eq 'stop') {
        & (Join-Path $PSScriptRoot 'stop.ps1')
        exit 0
    }
    if ($Action -eq 'start' -and
        (-not (Test-Path -LiteralPath (Join-Path $dubRoot 'frontend\dist\index.html')) -or
         -not (Test-Path -LiteralPath (Join-Path $dubRoot 'backend\.venv\Scripts\python.exe')))) {
        $Action = 'build-start'
    }
    if ($Action -in @('build', 'build-start')) {
        if (-not (Get-Command node.exe -ErrorAction SilentlyContinue) -or
            -not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
            throw 'Chưa tìm thấy Node.js/npm. Cài Node.js LTS rồi bấm lại file BUILD.'
        }
        if ($Action -eq 'build-start' -and (Get-DubHealth)) {
            $dubJobs = Invoke-RestMethod 'http://127.0.0.1:8765/api/jobs' -TimeoutSec 5
            foreach ($dubJob in $dubJobs) {
                if ($dubJob.status -in @('queued','processing','separating','transcribing','synthesizing','rendering')) {
                    throw 'Đang xử lý video. Hãy chờ hoàn tất trước khi build và khởi động lại. Dùng START-DUBFLOW.cmd để mở web hiện tại.'
                }
            }
        }
        $dubPython = Join-Path $dubRoot 'backend\.venv\Scripts\python.exe'
        $dubVite = Join-Path $dubRoot 'frontend\node_modules\vite\bin\vite.js'
        if (-not (Test-Path -LiteralPath $dubPython) -or -not (Test-Path -LiteralPath $dubVite)) {
            Write-Host 'Đang chuẩn bị thư viện web... Không tải model AI.'
            & (Join-Path $PSScriptRoot 'setup.ps1')
        } else {
            Write-Host 'Đang build DubFlow...'
            Push-Location (Join-Path $dubRoot 'frontend')
            try {
                & npm.cmd run build
                if ($LASTEXITCODE -ne 0) { throw 'Build thất bại. Xem thông báo phía trên rồi thử lại.' }
            } finally { Pop-Location }
        }
        if (-not (Test-Path -LiteralPath (Join-Path $dubRoot 'frontend\dist\index.html'))) {
            throw 'Chưa tạo được bản build. Không khởi động web.'
        }
        Write-Host 'Build hoàn tất.' -ForegroundColor Green
    }
    if ($Action -eq 'build') { exit 0 }
    if ($Action -eq 'build-start' -and (Get-DubHealth)) {
        # Reattach the verified launcher so stop.ps1 can safely restart it.
        & (Join-Path $PSScriptRoot 'start.ps1') -NoBrowser
        & (Join-Path $PSScriptRoot 'stop.ps1')
        if (Get-DubHealth) { throw 'Web cũ chưa dừng được. Không chạy thêm tiến trình. Hãy dùng STOP-DUBFLOW.cmd rồi thử lại.' }
    }
    & (Join-Path $PSScriptRoot 'start.ps1') -NoBrowser:$NoBrowser
    exit 0
} catch {
    Write-Host ''
    Write-Host ('Không thực hiện được: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'Log máy chủ: data\logs\api.err.log'
    exit 1
}
