# Project-scoped storage: no user/global environment changes.
$dubStorageRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dubStorage = Join-Path $dubStorageRoot 'repo-tests\local-storage'
$dubStoragePaths = @{
    OLLAMA_MODELS = (Join-Path $dubStorageRoot 'repo-tests\ollama-storage\models')
    HF_HOME = (Join-Path $dubStorage 'huggingface')
    HF_HUB_CACHE = (Join-Path $dubStorage 'huggingface\hub')
    HF_ASSETS_CACHE = (Join-Path $dubStorage 'huggingface\assets')
    HF_XET_CACHE = (Join-Path $dubStorage 'huggingface\xet')
    TORCH_HOME = (Join-Path $dubStorage 'torch')
    PIP_CACHE_DIR = (Join-Path $dubStorageRoot 'repo-tests\pip-cache')
    npm_config_cache = (Join-Path $dubStorageRoot 'repo-tests\npm-cache')
    UV_CACHE_DIR = (Join-Path $dubStorageRoot 'repo-tests\runtime\uv-cache')
    XDG_CACHE_HOME = (Join-Path $dubStorage 'cache')
    XDG_DATA_HOME = (Join-Path $dubStorage 'data')
    TEMP = (Join-Path $dubStorage 'tmp')
    TMP = (Join-Path $dubStorage 'tmp')
}
foreach ($dubStorageEntry in $dubStoragePaths.GetEnumerator()) {
    New-Item -ItemType Directory -Force -Path $dubStorageEntry.Value | Out-Null
    [Environment]::SetEnvironmentVariable($dubStorageEntry.Key, $dubStorageEntry.Value, 'Process')
}
$env:OLLAMA_HOST = '127.0.0.1:11439'
$env:OLLAMA_NO_CLOUD = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
