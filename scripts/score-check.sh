#!/usr/bin/env bash
set -euo pipefail

VENV_DIR="${CHORDFLASK_SCORE_VENV:-${HOME}/.venvs/chordflask-score}"
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    printf 'Score runtime missing: %s. Run make setup-score.\n' "$VENV_DIR" >&2
    exit 1
fi
"${VENV_DIR}/bin/python" -I -m chordflask_score.worker --check
command -v ffmpeg >/dev/null
command -v ffprobe >/dev/null
