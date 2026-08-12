#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_VENV_DIR="${HOME}/.venvs/chordifier"
VENV_DIR="${CHORDIFIER_VENV:-${DEFAULT_VENV_DIR}}"
PYTHON_BIN="${VENV_DIR}/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Project virtual environment not found: ${VENV_DIR}" >&2
    echo "Create it with:" >&2
    echo "  scripts/setup_venv.sh --dev" >&2
    exit 1
fi

cd "$ROOT_DIR"
"$PYTHON_BIN" -m pytest "$@"
