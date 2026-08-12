#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${HOME}/.vamp"
LOCAL_DIR=""

NNLS_ARCHIVE="nnls-chroma-linux64-v1.1.tar.bz2"
QM_ARCHIVE="qm-vamp-plugins-1.8.0-linux64.tar.gz"
NNLS_MD5="1c06fb30913a02ec203019b1d290b022"
QM_MD5="79747c514aca3c6b34aa5012584157dd"
NNLS_SHA256="877964bce86027d1c73c9210fcb3446b1da10dc40bba36b1bf04a61a60ad1d7f"
QM_SHA256="53f9e0e24d938507c01cb368e098cb321346b91594695aa877e7f67f17841ffa"

NNLS_PRIMARY_URL="https://code.soundsoftware.ac.uk/attachments/download/1693/${NNLS_ARCHIVE}"
QM_PRIMARY_URL="https://code.soundsoftware.ac.uk/attachments/download/2625/${QM_ARCHIVE}"
NNLS_ARCHIVE_URL="https://web.archive.org/web/20160219212458id_/${NNLS_PRIMARY_URL}"
QM_ARCHIVE_URL="https://web.archive.org/web/20241229060448id_/${QM_PRIMARY_URL}"

REQUIRED_LIBS=("nnls-chroma.so" "qm-vamp-plugins.so")
REQUIRED_PLUGINS=("nnls-chroma:chordino" "qm-vamp-plugins:qm-barbeattracker")

usage() {
    cat <<USAGE
Usage: $0 [--dest DIR] [--from DIR]

Install the Vamp plugins required by ChordFlask into a user directory.
No root access is needed.

Methods (tried in order):
  1. --from DIR  : Copy plugin .so/.cat/.n3 files from a local directory.
  2. Download pinned upstream archives, with verified Internet Archive
     snapshots as fallback, and enforce SHA-256 plus published MD5.

Options:
  --dest DIR    Install plugins into DIR (default: ~/.vamp).
  --from DIR    Copy existing plugin files from DIR instead of downloading.
  --help        Show this help text.

Environment:
  NNLS_URL      Direct download URL for ${NNLS_ARCHIVE}.
  QM_URL        Direct download URL for ${QM_ARCHIVE}.
  CHORDIFIER_VENV  Source-install venv used for plugin verification.

The script never invokes sudo.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dest)
            INSTALL_DIR="${2:?Missing directory after --dest}"
            shift 2
            ;;
        --from)
            LOCAL_DIR="${2:?Missing directory after --from}"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }

download_to_file() {
    local url="$1"
    local dest="$2"
    if command -v curl >/dev/null 2>&1; then
        curl -fL --connect-timeout 15 --max-time 300 -o "$dest" "$url"
    else
        wget -O "$dest" --timeout=300 "$url"
    fi
}

already_installed() {
    local dest="$1"
    for lib in "${REQUIRED_LIBS[@]}"; do
        if [[ ! -f "${dest}/${lib}" ]]; then
            return 1
        fi
    done
    return 0
}

verify_archive() {
    local file="$1"
    local expected_sha256="$2"
    local expected_md5="$3"
    local actual_sha256 actual_md5

    command -v sha256sum >/dev/null 2>&1 \
        || fail "sha256sum is required for archive verification."
    command -v md5sum >/dev/null 2>&1 \
        || fail "md5sum is required to match the historical upstream listing."

    actual_sha256="$(sha256sum "$file" | awk '{print $1}')"
    if [[ "$actual_sha256" != "$expected_sha256" ]]; then
        fail "SHA-256 mismatch for $(basename "$file") (expected ${expected_sha256}, got ${actual_sha256})."
    fi
    actual_md5="$(md5sum "$file" | awk '{print $1}')"
    if [[ "$actual_md5" != "$expected_md5" ]]; then
        fail "MD5 provenance mismatch for $(basename "$file") (expected ${expected_md5}, got ${actual_md5})."
    fi
}

verify_plugins() {
    local dest="$1"
    local script_dir chordflask_bin configured_python python_cmd
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    chordflask_bin="${script_dir}/chordflask"

    if [[ -x "$chordflask_bin" ]]; then
        VAMP_PATH="$dest" "$chordflask_bin" --check-vamp \
            || fail "The bundled ChordFlask runtime could not discover both plugins in ${dest}."
        return
    fi

    configured_python="${CHORDIFIER_VENV:-${HOME}/.venvs/chordifier}/bin/python"
    if [[ -x "$configured_python" ]]; then
        python_cmd="$configured_python"
    elif command -v python3 >/dev/null 2>&1; then
        python_cmd=python3
    elif command -v python >/dev/null 2>&1; then
        python_cmd=python
    else
        fail "Python is required to verify the source installation; the standalone archive verifies with its bundled ChordFlask runtime."
    fi
    if ! "$python_cmd" -c "import vamp" 2>/dev/null; then
        fail "The Python Vamp host is unavailable, so plugin discovery cannot be verified. Run this installer beside the standalone ChordFlask executable or from ChordFlask's configured environment."
    fi
    VAMP_PATH="$dest" "$python_cmd" -c "
import os, sys
import vamp
available = set(vamp.list_plugins())
required = {'nnls-chroma:chordino', 'qm-vamp-plugins:qm-barbeattracker'}
missing = required - available
if missing:
    print('ERROR: Plugin discovery failed.', file=sys.stderr)
    print('Missing: ' + ', '.join(sorted(missing)), file=sys.stderr)
    print('VAMP_PATH=' + os.environ.get('VAMP_PATH', ''), file=sys.stderr)
    sys.exit(1)
print('OK Both plugins discovered via VAMP_PATH=' + os.environ['VAMP_PATH'] + '.')
" || fail "Plugin discovery check failed. The .so files were installed but are not found by the Vamp host. Check VAMP_PATH and the plugin files."
}

# ── main ────────────────────────────────────────────────────────────

if already_installed "$INSTALL_DIR"; then
    echo "Vamp plugins are already installed in ${INSTALL_DIR}."
    verify_plugins "$INSTALL_DIR"
    exit 0
fi

mkdir -p "$INSTALL_DIR"

if [[ -n "$LOCAL_DIR" ]]; then
    echo "Copying plugin files from ${LOCAL_DIR}..."
    if [[ ! -d "$LOCAL_DIR" ]]; then
        fail "Source directory does not exist: ${LOCAL_DIR}"
    fi
    copied=0
    for lib in "${REQUIRED_LIBS[@]}"; do
        if [[ -f "${LOCAL_DIR}/${lib}" ]]; then
            cp -f "${LOCAL_DIR}/${lib}" "$INSTALL_DIR/"
            echo "  ${lib}"
            ((copied++)) || true
        fi
    done
    for meta in "${LOCAL_DIR}"/*.cat "${LOCAL_DIR}"/*.n3; do
        if [[ -f "$meta" ]]; then
            cp -f "$meta" "$INSTALL_DIR/"
        fi
    done
    if [[ "$copied" -ne ${#REQUIRED_LIBS[@]} ]]; then
        fail "Not all required plugin files were found in ${LOCAL_DIR}. Expected: ${REQUIRED_LIBS[*]}"
    fi
    echo "Installation from local files complete."
    verify_plugins "$INSTALL_DIR"
    echo ""
    echo "Vamp plugins installed to:"
    echo "  ${INSTALL_DIR}"
    echo ""
    echo "Start or restart ChordFlask. It will detect the plugins automatically."
    exit 0
fi

# ── network download path ───────────────────────────────────────────

TEMPDIR="$(mktemp -d)"
cleanup() { rm -rf "$TEMPDIR"; }
trap cleanup EXIT

echo "Checking download sources..."

NNLS_URL="${NNLS_URL:-$NNLS_PRIMARY_URL}"
QM_URL="${QM_URL:-$QM_PRIMARY_URL}"

echo "NNLS: $NNLS_URL"
echo "QM:   $QM_URL"
echo ""
echo "Downloading..."

if ! download_to_file "$NNLS_URL" "${TEMPDIR}/${NNLS_ARCHIVE}" 2>/dev/null; then
    if [[ -n "${NNLS_URL+x}" && "$NNLS_URL" != "$NNLS_PRIMARY_URL" ]]; then
        fail "NNLS download failed for the explicit NNLS_URL."
    fi
    warn "Primary NNLS download failed; trying the checksum-matched archived upstream file."
    download_to_file "$NNLS_ARCHIVE_URL" "${TEMPDIR}/${NNLS_ARCHIVE}" 2>/dev/null \
        || fail "NNLS download failed from both primary and archived upstream URLs."
fi
verify_archive "${TEMPDIR}/${NNLS_ARCHIVE}" "$NNLS_SHA256" "$NNLS_MD5"

if ! download_to_file "$QM_URL" "${TEMPDIR}/${QM_ARCHIVE}" 2>/dev/null; then
    if [[ -n "${QM_URL+x}" && "$QM_URL" != "$QM_PRIMARY_URL" ]]; then
        fail "QM download failed for the explicit QM_URL."
    fi
    warn "Primary QM download failed; trying the checksum-matched archived upstream file."
    download_to_file "$QM_ARCHIVE_URL" "${TEMPDIR}/${QM_ARCHIVE}" 2>/dev/null \
        || fail "QM download failed from both primary and archived upstream URLs."
fi
verify_archive "${TEMPDIR}/${QM_ARCHIVE}" "$QM_SHA256" "$QM_MD5"

echo ""
echo "Extracting..."

case "$NNLS_ARCHIVE" in
    *.tar.bz2) tar -xjf "${TEMPDIR}/${NNLS_ARCHIVE}" -C "$TEMPDIR" ;;
    *.tar.gz)  tar -xzf "${TEMPDIR}/${NNLS_ARCHIVE}" -C "$TEMPDIR" ;;
    *) fail "Unsupported NNLS archive format: $NNLS_ARCHIVE" ;;
esac
case "$QM_ARCHIVE" in
    *.tar.gz)  tar -xzf "${TEMPDIR}/${QM_ARCHIVE}" -C "$TEMPDIR" ;;
    *.tar.bz2) tar -xjf "${TEMPDIR}/${QM_ARCHIVE}" -C "$TEMPDIR" ;;
    *) fail "Unsupported QM archive format: $QM_ARCHIVE" ;;
esac

echo "Installing to ${INSTALL_DIR}..."
find "$TEMPDIR" -type f \( -name '*.so' -o -name '*.cat' -o -name '*.n3' \) -print0 \
    | while IFS= read -r -d '' file; do
        cp -f "$file" "$INSTALL_DIR/"
    done

for lib in "${REQUIRED_LIBS[@]}"; do
    if [[ ! -f "${INSTALL_DIR}/${lib}" ]]; then
        fail "${lib} was not installed. The archive extraction may have failed or the archive layout changed."
    fi
done

echo ""
echo "Installation complete."
verify_plugins "$INSTALL_DIR"

cat <<DONE

Vamp plugins installed to:
  ${INSTALL_DIR}

Start or restart ChordFlask. It will detect the plugins automatically.
DONE
