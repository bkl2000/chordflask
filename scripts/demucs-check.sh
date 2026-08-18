#!/usr/bin/env bash
set -euo pipefail

# Read-only diagnostic for the optional Demucs runtime.
VENV_DIR="${CHORDFLASK_DEMUCS_VENV:-${HOME}/.venvs/chordflask-demucs}"
VENV_PY="${VENV_DIR}/bin/python"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    printf '%s\n' 'Usage: scripts/demucs-check.sh' 'Read-only optional Demucs runtime diagnostic.'
    exit 0
fi

printf '%-18s ' 'Demucs venv:'
if [[ ! -x "${VENV_PY}" ]]; then
    printf 'MISSING (%s)\n' "${VENV_DIR}"
    exit 1
fi
printf 'OK\n'

REPORT="$(
    "${VENV_PY}" -c '
import json
import sys
import demucs
import torch
print(json.dumps({
    "python": sys.version.split()[0],
    "demucs": getattr(demucs, "__version__", "unknown"),
    "torch": torch.__version__,
    "cuda": bool(torch.cuda.is_available()),
}))
' 2>&1
)" || {
    printf '%s\n' "${REPORT}" >&2
    exit 1
}

"${VENV_PY}" -m demucs.separate --help >/dev/null
printf '%s\n' "${REPORT}" | "${VENV_PY}" -c '
import json
import sys
report = json.load(sys.stdin)
for key in ("python", "demucs", "torch", "cuda"):
    print(f"{key}: {report[key]}")
'
command -v ffmpeg >/dev/null 2>&1 && printf 'OK\n' || { printf 'MISSING\n'; exit 1; }
printf '%-18s ' 'ffprobe:'
command -v ffprobe >/dev/null 2>&1 && printf 'OK\n' || { printf 'MISSING\n'; exit 1; }
