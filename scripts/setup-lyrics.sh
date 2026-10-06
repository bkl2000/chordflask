#!/usr/bin/env bash
set -euo pipefail

# Install a self-contained Lyrics generator outside the core/source runtime.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${CHORDFLASK_LYRICS_VENV:-${HOME}/.venvs/chordflask-lyrics}"
PYTHON_BIN="${CHORDFLASK_LYRICS_PYTHON:-python3}"
RUNTIME_PYTHON="$PYTHON_BIN"

fail() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "  $*"; }

echo "ChordFlask Lyrics runtime setup"
echo "  venv: ${VENV_DIR}"

if [[ -x "${VENV_DIR}/bin/python" ]]; then
    RUNTIME_PYTHON="${VENV_DIR}/bin/python"
fi
"$RUNTIME_PYTHON" - <<'PY' || fail "Lyrics Python preflight failed. Set CHORDFLASK_LYRICS_PYTHON to Python 3.10 through 3.14; for an existing unsupported venv, select a new CHORDFLASK_LYRICS_VENV path."
import sys

if not (3, 10) <= sys.version_info[:2] <= (3, 14):
    sys.exit("Lyrics requires Python 3.10 through 3.14; found {}.{}.".format(*sys.version_info[:2]))
PY

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    info "Creating Lyrics virtual environment at ${VENV_DIR}"
    "$PYTHON_BIN" -m venv "$VENV_DIR" || \
        fail "Could not create venv; ensure python3-venv is installed"
fi

SOURCE_IDENTITY="$("${VENV_DIR}/bin/python" -I "${ROOT_DIR}/chordflask_lyrics/freshness.py" \
    fingerprint --source "$ROOT_DIR")" || fail "Could not identify the Lyrics source"

info "Installing the Lyrics generator and PyThaiNLP/ONNX runtime"
"${VENV_DIR}/bin/python" -m pip install --quiet --upgrade pip
"${VENV_DIR}/bin/python" -m pip uninstall --quiet --yes \
    tltk pandas requests || \
    fail "Could not remove the obsolete TLTK runtime stack"
"${VENV_DIR}/bin/python" -m pip install --quiet \
    --requirement "${ROOT_DIR}/requirements-lyrics.txt" || \
    fail "Could not install the Lyrics dependencies"
"${VENV_DIR}/bin/python" -m pip install --quiet --no-deps "$ROOT_DIR" || \
    fail "Could not install the Lyrics generator"

info "Verifying Lyrics runtime"
"${VENV_DIR}/bin/chordflask-genlyrics" --help >/dev/null || \
    fail "The installed chordflask-genlyrics helper could not start"

"${VENV_DIR}/bin/python" -I "${ROOT_DIR}/chordflask_lyrics/freshness.py" \
    record --source "$ROOT_DIR" --runtime "$VENV_DIR" --expected "$SOURCE_IDENTITY" || \
    fail "Could not verify and record the installed Lyrics source identity"

echo ""
echo "Lyrics runtime ready: ${VENV_DIR}"
echo "Diagnose with: make lyrics-check"
