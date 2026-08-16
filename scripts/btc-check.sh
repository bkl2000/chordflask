#!/usr/bin/env bash
set -euo pipefail

# Diagnose the isolated BTC runtime. Read-only; never installs or downloads.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BTC_DIR="${CHORDFLASK_BTC_DIR:-${ROOT_DIR}/chordflask_btc/model}"
VENV_DIR="${CHORDFLASK_BTC_VENV:-${HOME}/.venvs/chordflask-btc}"
VENV_PY="${VENV_DIR}/bin/python"
CHECKPOINT="${BTC_DIR}/btc_model_large_voca.pt"
CHECKPOINT_SIZE=12229576
WRAPPER_BIN="${VENV_DIR}/bin/btc-predict-raw"
SHA_FILE="${BTC_DIR}/checkpoint.sha256"

status() {
    local label="$1" ok="$2"
    printf '%-16s %s\n' "${label}" "${ok}"
}

printf '%-16s ' "BTC venv:"
[[ -x "$VENV_PY" ]] && status "" "OK" || { status "" "MISSING ($VENV_DIR)"; }

if [[ -x "$VENV_PY" ]]; then
    PY_REPORT="$("$VENV_PY" -c "
import sys
print(sys.version.split()[0])
try:
    import torch
    print('torch ' + torch.__version__)
except Exception as exc:
    print('torch missing: ' + str(exc))
" 2>&1 || true)"

    printf '%-16s %s\n' "Python:" "$(head -n1 <<<"$PY_REPORT")"

    if grep -q '^torch ' <<<"$PY_REPORT"; then
        printf '%-16s %s\n' "PyTorch:" "$(grep '^torch ' <<<"$PY_REPORT" | cut -d' ' -f2)"
    else
        printf '%-16s %s\n' "PyTorch:" "MISSING"
    fi
else
    printf '%-16s %s\n' "Python:" "MISSING"
    printf '%-16s %s\n' "PyTorch:" "MISSING"
fi

printf '%-16s ' "BTC code:"
[[ -f "$BTC_DIR/btc_model.py" && -f "$BTC_DIR/predict_raw.py" ]] \
    && printf 'OK\n' || printf 'MISSING\n'

printf '%-16s ' "Model:"
if [[ -f "$CHECKPOINT" && "$(stat -c%s "$CHECKPOINT" 2>/dev/null || echo 0)" == "$CHECKPOINT_SIZE" ]]; then
    printf 'OK\n'
else
    printf 'MISSING (expected %s bytes)\n' "$CHECKPOINT_SIZE"
fi

printf '%-16s ' "Model SHA256:"
if [[ -f "$CHECKPOINT" ]]; then
    printf '%s\n' "$(sha256sum "$CHECKPOINT" | cut -d' ' -f1)"
else
    printf '-\n'
fi

if [[ -f "$SHA_FILE" ]]; then
    printf '%-16s %s\n' "Pinned SHA256:" "$(tr -d '[:space:]' < "$SHA_FILE")"
fi

printf '%-16s ' "Wrapper:"
[[ -x "$WRAPPER_BIN" ]] && printf 'OK\n' || printf 'MISSING\n'

if [[ -x "$VENV_PY" ]]; then
    CUDA_REPORT="$("$VENV_PY" -c "
import torch
avail = torch.cuda.is_available()
print('yes' if avail else 'no')
if avail:
    print(torch.cuda.get_device_name(0))
    print(torch.cuda.device_count())
else:
    print('-')
    print('0')
" 2>&1 || true)"
    cuda_avail="$(sed -n '1p' <<<"$CUDA_REPORT")"
    gpu_name="$(sed -n '2p' <<<"$CUDA_REPORT")"
    gpu_count="$(sed -n '3p' <<<"$CUDA_REPORT")"

    if [[ "$cuda_avail" == "yes" ]]; then
        printf '%-16s %s\n' "CUDA:" "available"
        printf '%-16s %s\n' "CUDA available:" "yes"
        printf '%-16s %s\n' "GPU:" "$gpu_name"
        printf '%-16s %s\n' "CUDA device count:" "$gpu_count"
        printf '%-16s %s\n' "Device selected:" "cuda"
    else
        printf '%-16s %s\n' "CUDA:" "unavailable"
        printf '%-16s %s\n' "CUDA available:" "no"
        printf '%-16s %s\n' "Device selected:" "cpu"
    fi
else
    printf '%-16s %s\n' "CUDA:" "unavailable"
    printf '%-16s %s\n' "Device selected:" "cpu"
fi
