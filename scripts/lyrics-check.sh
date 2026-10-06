#!/usr/bin/env bash
set -euo pipefail

# Diagnose the isolated Lyrics runtime. Read-only; never installs packages.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${CHORDFLASK_LYRICS_VENV:-${HOME}/.venvs/chordflask-lyrics}"
RUNTIME_PYTHON="${VENV_DIR}/bin/python"
HELPER="${VENV_DIR}/bin/chordflask-genlyrics"

if [[ ! -x "$RUNTIME_PYTHON" ]]; then
    echo "Lyrics runtime: MISSING (${VENV_DIR})"
    exit 1
fi
echo "Lyrics runtime: FOUND (${VENV_DIR})"
echo "Python: $(${RUNTIME_PYTHON} -c 'import sys; print(sys.version.split()[0])')"

if [[ ! -x "$HELPER" ]]; then
    echo "Helper: MISSING (${HELPER})"
    exit 1
fi
if ! "$HELPER" --help >/dev/null; then
    echo "Helper: UNUSABLE (${HELPER})"
    exit 1
fi
echo "Helper: OK (${HELPER})"

"$RUNTIME_PYTHON" -I "${ROOT_DIR}/chordflask_lyrics/freshness.py" \
    check --source "$ROOT_DIR" --runtime "$VENV_DIR"
echo "Lyrics runtime: OK (${VENV_DIR})"

"$RUNTIME_PYTHON" - <<'PY'
import onnxruntime
import pythainlp

print("Lyrics dependencies: OK")
PY
