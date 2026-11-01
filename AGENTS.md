# DubFlow workspace storage

- Store all new project outputs, model weights, downloads, caches, logs, virtual environments and temporary files on drive D, inside this workspace or the existing D:\OmniVoice caches where appropriate.
- Before running installation, download, benchmark or build commands in PowerShell, dot-source `scripts/local-test-env.ps1`. It sets process-scoped cache and TEMP/TMP paths on D. Do not change HOME or global/user environment settings.
- Use `scripts/start-local-models.ps1` for the local Ollama test server on port11439 (bench experiments only; DubFlow no longer translates with Ollama). Model storage is `repo-tests/ollama-storage/models`. Do not launch the Ollama desktop app or run a model pull against an unverified server: it can fall back to a C-drive cache. Do not delete Ollama or `repo-tests/ollama-storage`: other projects use them.
- Original input videos on C, user attachments, application installations and credentials are not disposable project data. Do not move/delete them or clean unrelated C-drive directories.
- The D:\OmniVoice installation must stay unchanged. Trial venvs may reference its installed libraries read-only.
- Preserve existing benchmark results. New parameter/model/prompt changes require a new run directory.
