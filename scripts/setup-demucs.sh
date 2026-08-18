#!/usr/bin/env bash
set -euo pipefail

# Set up the optional Demucs runtime outside the normal ChordFlask venv.
# This script never installs system packages and never bundles model weights.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${CHORDFLASK_DEMUCS_VENV:-${HOME}/.venvs/chordflask-demucs}"
PYTHON_BIN="${CHORDFLASK_DEMUCS_PYTHON:-python3}"
TORCH_INDEX_URL="${CHORDFLASK_DEMUCS_TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu124}"
REQUIREMENTS="${ROOT_DIR}/chordflask_demucs/requirements.txt"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    cat <<'EOF'
Usage: scripts/setup-demucs.sh

Create the optional Demucs runtime in ~/.venvs/chordflask-demucs. The runtime
is separate from the normal ChordFlask environment and no system packages are
installed by this script.
EOF
    exit 0
fi

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

printf 'ChordFlask Demucs runtime setup\n'
printf '  venv: %s\n' "${VENV_DIR}"
printf '  model: htdemucs (downloaded by Demucs on first processing run)\n'

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    "${PYTHON_BIN}" -m venv "${VENV_DIR}" || \
        fail "Could not create the venv; ensure python3-venv is installed (sudo apt install python3-venv)"
fi

"${VENV_DIR}/bin/python" -m pip install --quiet --upgrade pip
"${VENV_DIR}/bin/pip" install --quiet \
    "torch==2.6.0" "torchaudio==2.6.0" \
    --index-url "${TORCH_INDEX_URL}" || \
    fail "Could not install the pinned Torch 2.6.0 runtime"
"${VENV_DIR}/bin/pip" install --quiet --requirement "${REQUIREMENTS}" || \
    fail "Could not install the pinned Demucs runtime"

"${VENV_DIR}/bin/python" -m demucs.separate --help >/dev/null || \
    fail "Demucs runtime verification failed"

printf '\nDemucs runtime ready: %s\n' "${VENV_DIR}"
printf 'Diagnose with: make demucs-check\n'
