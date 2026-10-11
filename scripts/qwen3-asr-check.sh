#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${CHORDFLASK_QWEN3_VENV:-${HOME}/.venvs/chordflask-qwen3-asr}"
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    echo "Qwen3 runtime missing: $VENV_DIR; run make setup-qwen3-asr" >&2
    exit 1
fi
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 "${VENV_DIR}/bin/python" -I \
    "$ROOT_DIR/chordflask_lyrics/qwen3_worker.py" --models "$VENV_DIR/models" --check
