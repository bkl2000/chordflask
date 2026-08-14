#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_VENV_DIR="${HOME}/.venvs/chordflask"
LEGACY_VENV_DIR="${HOME}/.venvs/chordifier"
VENV_DIR="${CHORDFLASK_VENV:-${CHORDIFIER_VENV:-${DEFAULT_VENV_DIR}}}"
if [[ -z "${CHORDFLASK_VENV:-}${CHORDIFIER_VENV:-}" \
    && ! -d "$VENV_DIR" && -d "$LEGACY_VENV_DIR" ]]; then
    VENV_DIR="$LEGACY_VENV_DIR"
fi
PYTHON_BIN="${VENV_DIR}/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Project virtual environment not found: ${VENV_DIR}" >&2
    echo "Create it with:" >&2
    echo "  scripts/setup_venv.sh --dev" >&2
    exit 1
fi

cd "$ROOT_DIR"
"$PYTHON_BIN" -m pytest "$@"
