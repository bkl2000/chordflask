#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="${ROOT_DIR}/vamp"
DOWNLOAD_DIR="${WORK_DIR}/downloads"
EXTRACT_DIR="${WORK_DIR}/plugins"
INSTALL_DIR="${HOME}/.vamp"
VENDOR_DIR=""

NNLS_PAGE_URL="https://isophonics.net/nnls-chroma.html"
QM_PAGE_URL="https://code.soundsoftware.ac.uk/projects/qm-vamp-plugins/files"

NNLS_ARCHIVE="nnls-chroma-linux64-v1.1.tar.bz2"
QM_ARCHIVE="qm-vamp-plugins-1.8.0-linux64.tar.gz"
NNLS_VERSION="1.1"
QM_VERSION="1.8.0"

NNLS_MD5="1c06fb30913a02ec203019b1d290b022"
QM_MD5="79747c514aca3c6b34aa5012584157dd"
NNLS_SHA256="877964bce86027d1c73c9210fcb3446b1da10dc40bba36b1bf04a61a60ad1d7f"
QM_SHA256="53f9e0e24d938507c01cb368e098cb321346b91594695aa877e7f67f17841ffa"

usage() {
    cat <<USAGE
Usage: $0 [--dest DIR]

Downloads and installs the Vamp plugins required by the chordifier.

Options:
  --dest DIR   Install plugin files into DIR instead of ~/.vamp.
  --vendor DIR Also copy the required plugin files into DIR.

Environment overrides:
  NNLS_URL     Direct download URL for ${NNLS_ARCHIVE}.
  QM_URL       Direct download URL for ${QM_ARCHIVE}.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dest)
            INSTALL_DIR="${2:?Missing directory after --dest}"
            shift 2
            ;;
        --vendor)
            VENDOR_DIR="${2:?Missing directory after --vendor}"
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

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Missing required command: $1" >&2
        exit 1
    fi
}

fetch() {
    local url="$1"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$url"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- "$url"
    else
        echo "Missing curl or wget" >&2
        exit 1
    fi
}

download_to_file() {
    local url="$1"
    local dest="$2"
    if command -v curl >/dev/null 2>&1; then
        curl -fL "$url" -o "$dest"
    else
        wget -O "$dest" "$url"
    fi
}

resolve_download_url() {
    local page_url="$1"
    local filename="$2"
    local html
    local href

    html="$(fetch "$page_url")"
    href="$(printf '%s\n' "$html" \
        | grep -Eo "href=\"[^\"]*${filename}\"" \
        | head -n 1 \
        | sed -E 's/^href="//; s/"$//')"

    if [[ -z "$href" ]]; then
        echo "Could not find download link for ${filename} on ${page_url}" >&2
        exit 1
    fi

    if [[ "$href" == http://* || "$href" == https://* ]]; then
        printf '%s\n' "$href"
    elif [[ "$href" == /* ]]; then
        printf 'https://code.soundsoftware.ac.uk%s\n' "$href"
    else
        printf '%s/%s\n' "$(dirname "$page_url")" "$href"
    fi
}

version_is_newer() {
    local candidate="$1"
    local current="$2"
    local newest

    newest="$(printf '%s\n%s\n' "$candidate" "$current" | sort -V | tail -n 1)"
    [[ "$newest" == "$candidate" && "$candidate" != "$current" ]]
}

warn_if_newer_version_exists() {
    local label="$1"
    local page_url="$2"
    local version_pattern="$3"
    local current_version="$4"
    local html
    local latest_version

    if ! html="$(fetch "$page_url")"; then
        echo "Warning: could not check ${label} for newer versions." >&2
        return
    fi

    latest_version="$(printf '%s\n' "$html" \
        | grep -Eo "$version_pattern" \
        | sed -E 's/[^0-9]*([0-9]+(\.[0-9]+)+).*/\1/' \
        | sort -Vu \
        | tail -n 1 || true)"

    if [[ -n "$latest_version" ]] && version_is_newer "$latest_version" "$current_version"; then
        echo "Warning: ${label} ${latest_version} appears to be available; this script is pinned to ${current_version}." >&2
    fi
}

verify_archive() {
    local file="$1"
    local expected_sha256="$2"
    local expected_md5="$3"
    local actual_sha256 actual_md5

    require_command sha256sum
    require_command md5sum
    actual_sha256="$(sha256sum "$file" | awk '{print $1}')"
    if [[ "$actual_sha256" != "$expected_sha256" ]]; then
        echo "SHA-256 mismatch for ${file}" >&2
        echo "Expected: ${expected_sha256}" >&2
        echo "Actual:   ${actual_sha256}" >&2
        exit 1
    fi
    actual_md5="$(md5sum "$file" | awk '{print $1}')"
    if [[ "$actual_md5" != "$expected_md5" ]]; then
        echo "MD5 provenance mismatch for ${file}" >&2
        echo "Expected: ${expected_md5}" >&2
        echo "Actual:   ${actual_md5}" >&2
        exit 1
    fi
}

download_archive() {
    local label="$1"
    local url="$2"
    local archive="$3"
    local sha256="$4"
    local md5="$5"
    local dest="${DOWNLOAD_DIR}/${archive}"

    if [[ -f "$dest" ]]; then
        echo "${label}: using existing ${dest}"
    else
        echo "${label}: downloading ${url}"
        download_to_file "$url" "$dest"
    fi

    verify_archive "$dest" "$sha256" "$md5"
}

extract_archives() {
    rm -rf "$EXTRACT_DIR"
    mkdir -p "$EXTRACT_DIR"
    tar -xf "${DOWNLOAD_DIR}/${NNLS_ARCHIVE}" -C "$EXTRACT_DIR"
    tar -xf "${DOWNLOAD_DIR}/${QM_ARCHIVE}" -C "$EXTRACT_DIR"
}

install_plugins() {
    mkdir -p "$INSTALL_DIR"

    find "$EXTRACT_DIR" -type f \( -name '*.so' -o -name '*.cat' -o -name '*.n3' \) -print0 \
        | while IFS= read -r -d '' file; do
            cp -f "$file" "$INSTALL_DIR/"
        done

    if [[ ! -f "${INSTALL_DIR}/nnls-chroma.so" ]]; then
        echo "nnls-chroma.so was not installed" >&2
        exit 1
    fi

    if [[ ! -f "${INSTALL_DIR}/qm-vamp-plugins.so" ]]; then
        echo "qm-vamp-plugins.so was not installed" >&2
        exit 1
    fi
}

vendor_plugins() {
    if [[ -z "$VENDOR_DIR" ]]; then
        return
    fi

    mkdir -p "$VENDOR_DIR"
    find "$EXTRACT_DIR" -type f \( -name '*.so' -o -name '*.cat' -o -name '*.n3' \) -print0 \
        | while IFS= read -r -d '' file; do
            cp -f "$file" "$VENDOR_DIR/"
        done

    echo "Vendored Vamp plugins into:"
    echo "  ${VENDOR_DIR}"
}

require_command tar
mkdir -p "$DOWNLOAD_DIR"

warn_if_newer_version_exists "NNLS Chroma/Chordino" "$NNLS_PAGE_URL" "nnls-chroma-linux64-v[0-9]+(\\.[0-9]+)+" "$NNLS_VERSION"
warn_if_newer_version_exists "QM Vamp Plugins" "$QM_PAGE_URL" "qm-vamp-plugins-[0-9]+(\\.[0-9]+)+" "$QM_VERSION"

NNLS_URL="${NNLS_URL:-$(resolve_download_url "$NNLS_PAGE_URL" "$NNLS_ARCHIVE")}"
QM_URL="${QM_URL:-$(resolve_download_url "$QM_PAGE_URL" "$QM_ARCHIVE")}"

download_archive "NNLS Chroma/Chordino" "$NNLS_URL" "$NNLS_ARCHIVE" "$NNLS_SHA256" "$NNLS_MD5"
download_archive "QM Vamp Plugins" "$QM_URL" "$QM_ARCHIVE" "$QM_SHA256" "$QM_MD5"
extract_archives
install_plugins
vendor_plugins

cat <<DONE

Vamp plugins installed into:
  ${INSTALL_DIR}

The chordifier will use this automatically when VAMP_PATH is unset.
For a custom install path, start the app with:
  export VAMP_PATH="${INSTALL_DIR}"
  cd flask
  python3 chordflask.py
DONE
