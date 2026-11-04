#!/usr/bin/env bash
# Start the DubFlow API (serves frontend/dist) on 127.0.0.1:8765. Reads <repo>/.env if present.
# Usage: scripts/start-linux.sh [--dev]   (--dev also starts Vite on 5173)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$ROOT/.env" ]; then set -a; . "$ROOT/.env"; set +a; fi
MODELS="${DUBFLOW_MODELS_DIR:-$ROOT/models}"
export TORCH_HOME="${TORCH_HOME:-$MODELS/cache/torch}"   # Demucs checkpoint lives under $TORCH_HOME/hub/checkpoints
export PYTHONPATH="$ROOT/backend" PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1
mkdir -p "${DUBFLOW_DATA_DIR:-$ROOT/data}/logs"
if [ "${1:-}" = "--dev" ]; then
  (cd "$ROOT/frontend" && npm run dev) &
  trap 'kill %1 2>/dev/null || true' EXIT
elif [ ! -f "$ROOT/frontend/dist/index.html" ]; then
  (cd "$ROOT/frontend" && npm run build)
fi
cd "$ROOT"
exec "$ROOT/backend/.venv/bin/python" -m uvicorn dubflow.app:app --host 127.0.0.1 --port 8765
