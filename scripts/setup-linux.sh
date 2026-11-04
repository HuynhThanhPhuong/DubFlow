#!/usr/bin/env bash
# DubFlow Linux setup: venvs inside the repo, pinned requirements, cache dirs, final check.
# Usage: scripts/setup-linux.sh [--skip-frontend] [--skip-engines] [--cpu-torch]
#   PYTHON=python3.12      interpreter used to create the venvs (Windows runtimes use 3.12)
#   DUBFLOW_RUNTIME_DIR    engine venvs (default <repo>/runtime)
#   DUBFLOW_MODELS_DIR     models + caches (default <repo>/models)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
RUNTIME="${DUBFLOW_RUNTIME_DIR:-$ROOT/runtime}"
MODELS="${DUBFLOW_MODELS_DIR:-$ROOT/models}"
TORCH_INDEX="https://download.pytorch.org/whl/cu128"
SKIP_FRONTEND=0; SKIP_ENGINES=0
for arg in "$@"; do
  case "$arg" in
    --skip-frontend) SKIP_FRONTEND=1 ;;
    --skip-engines) SKIP_ENGINES=1 ;;
    --cpu-torch) TORCH_INDEX="https://download.pytorch.org/whl/cpu" ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

command -v "$PYTHON" >/dev/null || { echo "Khong tim thay $PYTHON (can Python 3.12)." >&2; exit 1; }
command -v ffmpeg >/dev/null || echo "CANH BAO: chua co ffmpeg/ffprobe (apt install ffmpeg)." >&2

mkdir -p "$ROOT/data" "$RUNTIME" "$MODELS/cache/hf-asr" "$MODELS/cache/hf-tts" "$MODELS/cache/torch" \
         "$MODELS/lama" "$MODELS/voices" "$MODELS/vi-prompt"

make_venv() {  # name
  local dir="$1"
  [ -x "$dir/bin/python" ] || "$PYTHON" -m venv "$dir"
  "$dir/bin/python" -m pip install --upgrade pip >/dev/null
}

# API backend (always).
make_venv "$ROOT/backend/.venv"
"$ROOT/backend/.venv/bin/python" -m pip install -r "$ROOT/backend/requirements.txt"

if [ "$SKIP_ENGINES" -eq 0 ]; then
  for engine in asr tts speaker ocr; do
    venv="$RUNTIME/$engine/.venv"
    make_venv "$venv"
    if [ "$engine" != "ocr" ]; then
      "$venv/bin/python" -m pip install -r "$ROOT/requirements/torch.txt" --index-url "$TORCH_INDEX"
    fi
    "$venv/bin/python" -m pip install -r "$ROOT/requirements/$engine.txt"
  done
fi

if [ "$SKIP_FRONTEND" -eq 0 ]; then
  if command -v npm >/dev/null; then
    (cd "$ROOT/frontend" && npm ci && npm run build)
  else
    echo "CANH BAO: chua co npm/node (can Node 20+); bo qua build frontend." >&2
  fi
fi

echo
echo "== Kiem tra =="
"$ROOT/backend/.venv/bin/python" --version
if command -v ffmpeg >/dev/null; then ffmpeg -version | head -n 1; else echo "ffmpeg: MISSING"; fi

has() { [ -e "$1" ] && echo "found   $2" || echo "MISSING $2  ($1)"; }
for engine in asr tts speaker ocr; do
  has "$RUNTIME/$engine/.venv/bin/python" "venv $engine"
done
has "$MODELS/cache/hf-asr/hub/models--openai--whisper-large-v3-turbo" "Whisper large-v3-turbo"
has "$MODELS/cache/hf-asr/hub/models--k2-fsa--OmniVoice" "OmniVoice"
has "$MODELS/cache/hf-tts/hub/models--openbmb--VoxCPM2" "VoxCPM2"
has "$MODELS/cache/torch/hub/checkpoints/955717e8-8726e21a.th" "Demucs HTDemucs"
has "$MODELS/lama/lama_fp32.onnx" "LaMa ONNX"
has "$MODELS/speaker-ecapa-voxceleb/embedding_model.ckpt" "Speaker ECAPA"
has "$MODELS/vi-prompt/vi-prompt.json" "Vietnamese primer (dub mode)"
has "$MODELS/voices" "system voices dir (optional)"
if command -v nvidia-smi >/dev/null; then nvidia-smi --query-gpu=name,memory.total --format=csv,noheader; else echo "GPU: khong thay nvidia-smi (cac buoc GPU se bao loi ro rang)"; fi
echo
echo "Tiep theo: python scripts/download-models-linux.py (bang runtime/asr/.venv/bin/python), roi scripts/start-linux.sh"
