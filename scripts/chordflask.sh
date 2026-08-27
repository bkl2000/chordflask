#!/usr/bin/env bash
set -euo pipefail

# Start the ChordFlask web app plus worker from the project virtual environment.

DEFAULT_VENV_DIR="${HOME}/.venvs/chordflask"
LEGACY_VENV_DIR="${HOME}/.venvs/chordifier"
VENV_DIR="${CHORDFLASK_VENV:-${CHORDIFIER_VENV:-${DEFAULT_VENV_DIR}}}"
if [[ -z "${CHORDFLASK_VENV:-}${CHORDIFIER_VENV:-}" \
    && ! -d "$VENV_DIR" && -d "$LEGACY_VENV_DIR" ]]; then
    VENV_DIR="$LEGACY_VENV_DIR"
fi
CHORDFLASK_BIN="${VENV_DIR}/bin/chordflask"

if [[ -n "${PYTHON_BIN:-}" ]]; then
    if [[ ! -x "$PYTHON_BIN" ]]; then
        echo "Configured Python interpreter not found: ${PYTHON_BIN}" >&2
        exit 1
    fi
    exec "${PYTHON_BIN}" -m chordflask "$@"
fi

if [[ ! -x "$CHORDFLASK_BIN" ]]; then
    echo "Project virtual environment not found: ${VENV_DIR}" >&2
    echo "Run 'make setup' in the ChordFlask repository." >&2
    exit 1
fi

exec "${CHORDFLASK_BIN}" "$@"
