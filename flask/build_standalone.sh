#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${CHORDFLASK_PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"

PRINT_RELEASE_NAME=false
if [[ "${1:-}" == "--print-release-name" && $# -eq 1 ]]; then
    PRINT_RELEASE_NAME=true
elif [[ $# -ne 0 ]]; then
    echo "Usage: $0 [--print-release-name]" >&2
    exit 2
fi

# A release artifact must represent one exact committed source revision. Refuse
# to build when tracked source changes (staged or unstaged) are present, so the
# embedded build commit can never claim a commit while carrying uncommitted edits.
if [[ -n "$(git -C "$PROJECT_ROOT" status --porcelain --untracked-files=no 2>/dev/null)" ]]; then
    echo "ERROR: refusing to build a standalone release artifact from a dirty working tree." >&2
    echo "Uncommitted tracked changes (staged or unstaged) are present:" >&2
    git -C "$PROJECT_ROOT" status --short >&2
    echo "Commit or stash the changes, then rerun 'make standalone'." >&2
    exit 1
fi

detect_distro_token() {
    if [[ ! -r /etc/os-release ]]; then
        echo "linux"
        return
    fi
    local id version
    id="$(sed -n 's/^ID=//p' /etc/os-release | tr -d '"')"
    version="$(sed -n 's/^VERSION_ID=//p' /etc/os-release | tr -d '"' | cut -d. -f1)"
    case "$id" in
        debian)    echo "debian${version}" ;;
        ubuntu)    echo "ubuntu${version}" ;;
        linuxmint) echo "mint${version}" ;;
        *)         echo "linux" ;;
    esac
}

arch_token="$(uname -m)"
py_token="py$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
distro_token="$(detect_distro_token)"
semver="$(head -n1 "${PROJECT_ROOT}/VERSION")"

RELEASE_NAME="chordflask-${distro_token}-${arch_token}-${py_token}-v${semver}"
RELEASE_DIR="${SCRIPT_DIR}/dist/${RELEASE_NAME}"
RELEASE_ARCHIVE="${SCRIPT_DIR}/dist/${RELEASE_NAME}.tar.gz"

if [[ "$PRINT_RELEASE_NAME" == true ]]; then
    printf '%s\n' "$RELEASE_NAME"
    exit 0
fi

cd "$SCRIPT_DIR"

if ! command -v pyinstaller >/dev/null 2>&1; then
    echo "pyinstaller is not installed. Install the Python dependencies first." >&2
    exit 1
fi

pyinstaller \
    --name chordflask \
    --onefile \
    --paths "${PROJECT_ROOT}" \
    --hidden-import=numba \
    --hidden-import=numba.core \
    --hidden-import=numba.core.types \
    --hidden-import=llvmlite \
    --copy-metadata=imageio \
    --copy-metadata=moviepy \
    --additional-hooks-dir=pyinstaller_hooks \
    --exclude-module=imageio_ffmpeg.binaries \
    --exclude-module=chordflask_demucs \
    --exclude-module=chordleadsheet_batch \
    --add-data "templates:templates" \
    --add-data "assets:assets" \
    chordflask.py

archive_listing="$(pyi-archive_viewer -l "${SCRIPT_DIR}/dist/chordflask")"
if grep -Eiq "imageio_ffmpeg/binaries/[^']*ffmpeg|vamp_plugins/[^']*\.so|vendor/vamp/[^']*\.so" <<<"$archive_listing"; then
    echo "Standalone archive contains a prohibited FFmpeg or Vamp executable." >&2
    exit 1
fi

rm -rf "${RELEASE_DIR}"
mkdir -p "${RELEASE_DIR}"
cp "${SCRIPT_DIR}/dist/chordflask" "${RELEASE_DIR}/"

cat > "${RELEASE_DIR}/chordflask.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHORDFLASK_BIN="${SCRIPT_DIR}/chordflask"
exec "${CHORDFLASK_BIN}" "$@"
EOF

cp "${SCRIPT_DIR}/install_vamp.sh" "${RELEASE_DIR}/"
cp "${PROJECT_ROOT}/docs/STANDALONE.md" "${RELEASE_DIR}/README.md"
cp "${PROJECT_ROOT}/THIRD_PARTY_NOTICES.md" "${RELEASE_DIR}/"
cp "${SCRIPT_DIR}/assets/fonts/LICENSE.txt" "${RELEASE_DIR}/LIBERATION-FONTS-LICENSE.txt"
printf '%s %s %s\n' "$semver" "$(date -u +'%Y-%m-%d %H:%M')" "$(git -C "${PROJECT_ROOT}" rev-parse --short HEAD)" \
    > "${RELEASE_DIR}/VERSION"
chmod +x "${RELEASE_DIR}/chordflask" "${RELEASE_DIR}/chordflask.sh" "${RELEASE_DIR}/install_vamp.sh"
tar -C "${SCRIPT_DIR}/dist" -czf "${RELEASE_ARCHIVE}" "${RELEASE_NAME}"
printf '%s\n' "$RELEASE_NAME" > "${SCRIPT_DIR}/dist/.latest-release"

printf '\n'
printf 'Standalone: %s\n' "${RELEASE_DIR}/chordflask"
printf 'Archive:    %s\n' "${RELEASE_ARCHIVE}"
printf 'Start:      %s\n' "${RELEASE_DIR}/chordflask.sh"

if ! command -v ffmpeg >/dev/null 2>&1; then
    printf 'MISSING: ffmpeg — sudo apt install ffmpeg\n'
fi
if [[ ! -f "${HOME}/.vamp/nnls-chroma.so" || ! -f "${HOME}/.vamp/qm-vamp-plugins.so" ]]; then
    printf 'MISSING: Vamp plugins — run: %s/install_vamp.sh\n' "${RELEASE_DIR}"
fi
