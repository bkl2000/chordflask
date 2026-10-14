#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${CHORDFLASK_SCORE_VENV:-${HOME}/.venvs/chordflask-score}"
PYTHON_BIN="${CHORDFLASK_SCORE_PYTHON:-python3.12}"
TORCH_INDEX_URL="${CHORDFLASK_SCORE_TORCH_INDEX_URL:-https://download.pytorch.org/whl/cpu}"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    printf '%s\n' 'Usage: scripts/setup-score.sh' \
        'Install the optional Python 3.12 Score runtime; no system packages are installed.' \
        'Default Torch: CPU. For CUDA set CHORDFLASK_SCORE_TORCH_INDEX_URL=https://download.pytorch.org/whl/cu128.'
    exit 0
fi
RUNTIME_PYTHON="$PYTHON_BIN"
if [[ -x "${VENV_DIR}/bin/python" ]]; then
    RUNTIME_PYTHON="${VENV_DIR}/bin/python"
fi
"$RUNTIME_PYTHON" -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else "Score requires Python 3.12; select CHORDFLASK_SCORE_PYTHON or a new CHORDFLASK_SCORE_VENV")'
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
"${VENV_DIR}/bin/python" -m pip install --quiet --upgrade pip
"${VENV_DIR}/bin/python" -m pip install --quiet 'torch==2.10.0' 'torchaudio==2.10.0' \
    --index-url "$TORCH_INDEX_URL"
"${VENV_DIR}/bin/python" -m pip install --quiet -r "${ROOT_DIR}/chordflask_score/requirements.txt"
# Like Lyrics, this installs the source distribution without core dependencies.
# The isolated worker needs only Score, the neutral base and lightweight Demucs utilities.
"${VENV_DIR}/bin/python" -m pip install --quiet --no-deps "$ROOT_DIR"
"${VENV_DIR}/bin/python" -I -m chordflask_score.worker --check
printf 'Score runtime ready: %s\n' "$VENV_DIR"
