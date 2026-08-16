#!/usr/bin/env bash
set -euo pipefail

# Set up the isolated BTC-ISMIR19 runtime used by the optional BTC analyzer.
#
# The BTC model code is MIT-licensed, but the pretrained checkpoint weights have
# no clearly documented redistribution license (the MIT license covers the code
# only). This script therefore never downloads the weights silently: it requires
# BTC_ACKNOWLEDGE_WEIGHTS=1 on the run that actually fetches the checkpoint.
#
# Runtime layout (kept entirely outside the normal chordflask venv):
#   venv:       ~/.venvs/chordflask-btc        (override: CHORDFLASK_BTC_VENV)
#   model code: chordflask_btc/model/          (tracked, MIT-adapted)
#   checkpoint: chordflask_btc/model/btc_model_large_voca.pt  (git-ignored, 12,229,576 B)
#   pin:        chordflask_btc/model/checkpoint.sha256        (tracked expected SHA-256)
#
# PyTorch 2.6.0 (cu124) is installed to match an NVIDIA driver reporting
# CUDA 12.4; inference falls back to CPU automatically when CUDA is unavailable.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BTC_DIR="${CHORDFLASK_BTC_DIR:-${ROOT_DIR}/chordflask_btc/model}"
VENV_DIR="${CHORDFLASK_BTC_VENV:-${HOME}/.venvs/chordflask-btc}"
PYTHON_BIN="${CHORDFLASK_BTC_PYTHON:-python3}"

TORCH_VERSION="2.6.0"
TORCH_INDEX_URL="https://download.pytorch.org/whl/cu124"
CHECKPOINT_NAME="btc_model_large_voca.pt"
CHECKPOINT_SIZE=12229576
CHECKPOINT_URL="https://raw.githubusercontent.com/benasterisk/stemtube-desktop-app/main/external/BTC-ISMIR19/test/btc_model_large_voca.pt"
CHECKPOINT="${BTC_DIR}/${CHECKPOINT_NAME}"
SHA_FILE="${BTC_DIR}/checkpoint.sha256"
WRAPPER_SOURCE="${BTC_DIR}/predict_raw.py"
WRAPPER_BIN="${VENV_DIR}/bin/btc-predict-raw"

fail() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "  $*"; }

echo "ChordFlask BTC runtime setup"
echo "  venv:       ${VENV_DIR}"
echo "  model code: ${BTC_DIR}"
echo "  checkpoint: ${CHECKPOINT}"

# ── 1. Python virtual environment ────────────────────────────────────

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    info "Creating BTC virtual environment at ${VENV_DIR}"
    "$PYTHON_BIN" -m venv "$VENV_DIR" || \
        fail "Could not create venv; ensure python3-venv is installed (sudo apt install python3-venv)"
else
    info "BTC venv already present"
fi

# ── 2. PyTorch 2.6.0 (cu124) ─────────────────────────────────────────

if "${VENV_DIR}/bin/python" -c "import torch" >/dev/null 2>&1 && \
    [[ "$("${VENV_DIR}/bin/python" -c "import torch; print(torch.__version__)" 2>/dev/null)" == "${TORCH_VERSION}"* ]]; then
    info "PyTorch ${TORCH_VERSION} already installed"
else
    info "Installing PyTorch ${TORCH_VERSION} (cu124)"
    "${VENV_DIR}/bin/pip" install --quiet --upgrade pip
    "${VENV_DIR}/bin/pip" install --quiet "torch==${TORCH_VERSION}" --index-url "${TORCH_INDEX_URL}" || \
        fail "Could not install torch ${TORCH_VERSION} from ${TORCH_INDEX_URL}"
fi

# ── 3. numpy + librosa (feature pipeline) ────────────────────────────

if "${VENV_DIR}/bin/python" -c "import numpy, librosa" >/dev/null 2>&1; then
    info "numpy and librosa already installed"
else
    info "Installing numpy and librosa"
    "${VENV_DIR}/bin/pip" install --quiet numpy librosa || \
        fail "Could not install numpy/librosa"
fi

# ── 4. Checkpoint weights ────────────────────────────────────────────

need_download=0
if [[ ! -f "$CHECKPOINT" ]]; then
    need_download=1
elif [[ "$(stat -c%s "$CHECKPOINT" 2>/dev/null || echo 0)" != "$CHECKPOINT_SIZE" ]]; then
    need_download=1
fi

if [[ "$need_download" == 1 ]]; then
    if [[ "${BTC_ACKNOWLEDGE_WEIGHTS:-}" != "1" ]]; then
        cat >&2 <<EOF
ERROR: the BTC checkpoint weights have no clearly documented redistribution
license (the MIT license covers the BTC code only). setup-btc refuses to
download them without an explicit opt-in.

Provenance: BTC-ISMIR19 (MIT code, copyright 2019 Jonggwon Park), ISMIR 2019;
the large-vocabulary checkpoint (${CHECKPOINT_NAME}, ${CHECKPOINT_SIZE} bytes)
is redistributed by the benasterisk/stemtube-desktop-app fork without an
explicit weights license. It is used only locally, never committed or published.

To proceed, acknowledge the provenance and rerun:

    make setup-btc BTC_ACKNOWLEDGE_WEIGHTS=1
EOF
        exit 1
    fi
    if ! command -v curl >/dev/null 2>&1; then
        fail "curl is required to download the checkpoint (sudo apt install curl)"
    fi
    info "Downloading checkpoint (${CHECKPOINT_SIZE} bytes)"
    tmp="${CHECKPOINT}.download.$$"
    trap 'rm -f "${tmp}"' EXIT
    curl -fL --retry 3 -o "$tmp" "$CHECKPOINT_URL" || \
        fail "Checkpoint download failed from ${CHECKPOINT_URL}"
    size="$(stat -c%s "$tmp")"
    [[ "$size" == "$CHECKPOINT_SIZE" ]] || \
        fail "Checkpoint size ${size} != expected ${CHECKPOINT_SIZE}"
    mv "$tmp" "$CHECKPOINT"
    trap - EXIT
else
    info "Checkpoint already present with the expected size"
fi

# ── 5. SHA-256 pinning ───────────────────────────────────────────────

actual_sha="$(sha256sum "$CHECKPOINT" | cut -d' ' -f1)"
expected_sha="${BTC_CHECKPOINT_SHA256:-}"
if [[ -z "$expected_sha" && -f "$SHA_FILE" ]]; then
    expected_sha="$(tr -d '[:space:]' < "$SHA_FILE")"
fi

if [[ -z "$expected_sha" ]]; then
    printf '%s\n' "$actual_sha" > "$SHA_FILE"
    info "First run: recorded checkpoint SHA-256 to ${SHA_FILE}"
    info "Review and commit that file so future runs validate against it."
elif [[ "$actual_sha" != "$expected_sha" ]]; then
    fail "Checkpoint SHA-256 mismatch: expected ${expected_sha}, got ${actual_sha}"
else
    info "Checkpoint SHA-256 verified: ${actual_sha}"
fi

# ── 6. btc-predict-raw wrapper ───────────────────────────────────────

# Always (re)write the wrapper: it embeds the absolute model-code path, so it
# must track the current BTC_DIR (e.g. after an upgrade moves the model code).
info "Installing btc-predict-raw wrapper"
cat > "$WRAPPER_BIN" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec "${VENV_DIR}/bin/python" "${WRAPPER_SOURCE}" "\$@"
EOF
chmod +x "$WRAPPER_BIN"

# ── 7. Verification ──────────────────────────────────────────────────

info "Verifying BTC runtime ..."
"${VENV_DIR}/bin/python" -c "
import sys
sys.path.insert(0, '${BTC_DIR}')
import btc_model, features, vocabulary
import torch
print('  torch:', torch.__version__, '| cuda:', torch.cuda.is_available())
" || fail "BTC runtime verification failed"

echo ""
echo "BTC runtime ready: ${VENV_DIR}"
echo "Diagnose with: make btc-check"
