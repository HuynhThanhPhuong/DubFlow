$ErrorActionPreference = 'Stop'
$dubMoveRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dubMoveSource = (Resolve-Path -LiteralPath 'C:\Users\PC\.ollama\models').Path
$dubMoveTarget = [IO.Path]::GetFullPath((Join-Path $dubMoveRoot 'repo-tests\ollama-storage\models'))
$dubMoveAudit = Join-Path $dubMoveRoot 'bench\runs\20261030\storage-migration'
if ($dubMoveSource -ne 'C:\Users\PC\.ollama\models' -or
    -not $dubMoveTarget.StartsWith($dubMoveRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or
    -not $dubMoveTarget.StartsWith('D:\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected migration roots.' }
if (Get-ChildItem -LiteralPath $dubMoveSource -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) {
    throw 'Refusing migration through a reparse point.'
}
$dubMoveManifests = @(Get-ChildItem -LiteralPath (Join-Path $dubMoveSource 'manifests') -Recurse -File)
if ($dubMoveManifests.Count -ne 2 -or @($dubMoveManifests | Where-Object {
    $_.FullName -notmatch '\\(?:hf.co\\tencent\\Hy-MT2-1.8B-GGUF\\Q8_0|registry.ollama.ai\\library\\qwen3\\4b-instruct-2507-q4_K_M)$'
}).Count) { throw 'The source contains models outside the two task-owned models.' }
$dubMoveFiles = @(Get-ChildItem -LiteralPath $dubMoveSource -Recurse -File)
if (@($dubMoveFiles | Where-Object { $_.CreationTime.Date -ne [datetime]'2026-10-30' }).Count) {
    throw 'A file predates this task; stop for provenance review.'
}
if (Get-NetTCPConnection -LocalPort 11439 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Stop the verified task model server before migration.'
}
New-Item -ItemType Directory -Force -Path $dubMoveTarget,$dubMoveAudit | Out-Null
$dubMoveRows = @()
foreach ($dubMoveFile in $dubMoveFiles) {
    $dubMoveRelative = $dubMoveFile.FullName.Substring($dubMoveSource.Length).TrimStart('\')
    $dubMoveDestination = [IO.Path]::GetFullPath((Join-Path $dubMoveTarget $dubMoveRelative))
    if (-not $dubMoveDestination.StartsWith($dubMoveTarget + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Destination escapes intended root.' }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dubMoveDestination) | Out-Null
    if (-not (Test-Path -LiteralPath $dubMoveDestination)) {
        Copy-Item -LiteralPath $dubMoveFile.FullName -Destination $dubMoveDestination
    }
    $dubMoveHash = (Get-FileHash -LiteralPath $dubMoveFile.FullName -Algorithm SHA256).Hash
    if ((Get-FileHash -LiteralPath $dubMoveDestination -Algorithm SHA256).Hash -ne $dubMoveHash -or
        (Get-Item -LiteralPath $dubMoveDestination).Length -ne $dubMoveFile.Length) { throw "Copy verification failed: $dubMoveRelative" }
    $dubMoveRows += [pscustomobject]@{ source = $dubMoveFile.FullName; destination = $dubMoveDestination; bytes = $dubMoveFile.Length; sha256 = $dubMoveHash; copied_verified = $true }
    Write-Output "Verified $($dubMoveRows.Count)/$($dubMoveFiles.Count): $dubMoveRelative"
}
$dubMoveRows | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $dubMoveAudit 'verified-model-copies.json') -Encoding UTF8
# Only remove individually verified task files; never recursively delete a C-drive directory.
foreach ($dubMoveRow in $dubMoveRows) {
    if (-not $dubMoveRow.source.StartsWith($dubMoveSource + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Source escapes intended root.' }
    if ((Get-FileHash -LiteralPath $dubMoveRow.destination -Algorithm SHA256).Hash -ne $dubMoveRow.sha256) { throw 'Destination changed before source cleanup.' }
    Remove-Item -LiteralPath $dubMoveRow.source
}
$dubMoveRecommendation = 'C:\Users\PC\.ollama\cache\model-recommendations.json'
if (Test-Path -LiteralPath $dubMoveRecommendation) {
    $dubMoveRecommendationItem = Get-Item -LiteralPath $dubMoveRecommendation
    if ($dubMoveRecommendationItem.CreationTime.Date -eq [datetime]'2026-10-30') {
        $dubMoveCache = Join-Path $dubMoveRoot 'repo-tests\ollama-storage\cache'
        New-Item -ItemType Directory -Force -Path $dubMoveCache | Out-Null
        $dubMoveCacheFile = Join-Path $dubMoveCache 'model-recommendations.json'
        Copy-Item -LiteralPath $dubMoveRecommendation -Destination $dubMoveCacheFile
        if ((Get-FileHash -LiteralPath $dubMoveRecommendation).Hash -ne (Get-FileHash -LiteralPath $dubMoveCacheFile).Hash) { throw 'Recommendation cache copy failed.' }
        Remove-Item -LiteralPath $dubMoveRecommendation
    }
}
$dubMoveBytes = ($dubMoveRows | Measure-Object bytes -Sum).Sum
@{ moved_files = $dubMoveRows.Count; bytes = $dubMoveBytes; source_remaining_files = @(Get-ChildItem -LiteralPath $dubMoveSource -Recurse -File).Count;
   source = $dubMoveSource; destination = $dubMoveTarget; credentials_apps_and_original_inputs_untouched = $true } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dubMoveAudit 'result.json') -Encoding UTF8
Write-Output "Moved and SHA256 verified $dubMoveBytes bytes to $dubMoveTarget"
