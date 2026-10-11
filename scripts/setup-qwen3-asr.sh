#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${CHORDFLASK_QWEN3_VENV:-${HOME}/.venvs/chordflask-qwen3-asr}"
PYTHON_BIN="${CHORDFLASK_QWEN3_PYTHON:-python3.12}"
if [[ -x "${VENV_DIR}/bin/python" ]]; then
    PYTHON_BIN="${VENV_DIR}/bin/python"
fi
if ! command -v "$PYTHON_BIN" >/dev/null; then
    echo "Qwen3 Python missing: $PYTHON_BIN" >&2
    echo "ChordFlask Qwen3 Lyrics V2 currently supports Python 3.10–3.13; Python 3.12 is recommended." >&2
    echo "Python 3.14 is not yet supported by our Qwen3 setup." >&2
    echo "You must provide a compatible interpreter and set CHORDFLASK_QWEN3_PYTHON to its command or path." >&2
    exit 1
fi
"$PYTHON_BIN" -c 'import sys; assert (3,10) <= sys.version_info[:2] <= (3,13), "ChordFlask Qwen3 Lyrics V2 currently supports Python 3.10–3.13; Python 3.12 is recommended. Python 3.14 is not yet supported by our Qwen3 setup. You must provide a compatible interpreter and set CHORDFLASK_QWEN3_PYTHON to its command or path."'
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
"${VENV_DIR}/bin/python" -m pip install --upgrade pip
# Optional wheel index lets users install CPU-only or a driver-compatible CUDA
# wheel. Default PyTorch wheels support CPU and CUDA on supported Linux hosts.
TORCH_ARGS=()
if [[ -n "${CHORDFLASK_QWEN3_TORCH_INDEX:-}" ]]; then
    TORCH_ARGS=(--index-url "$CHORDFLASK_QWEN3_TORCH_INDEX")
fi
"${VENV_DIR}/bin/python" -m pip install 'torch>=2.6,<3' "${TORCH_ARGS[@]}"
"${VENV_DIR}/bin/python" -m pip install 'qwen-asr==0.0.6' 'huggingface_hub<1'
"${VENV_DIR}/bin/python" - "$VENV_DIR/models" <<'PY'
from huggingface_hub import snapshot_download
from pathlib import Path
import sys
for name in ("Qwen3-ASR-1.7B", "Qwen3-ForcedAligner-0.6B"):
    snapshot_download("Qwen/" + name, local_dir=Path(sys.argv[1]) / name)
PY
bash "$ROOT_DIR/scripts/qwen3-asr-check.sh"
