#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RELEASE_NAME="chordflask-linux-x86_64"
RELEASE_DIR="${SCRIPT_DIR}/dist/${RELEASE_NAME}"
RELEASE_ARCHIVE="${SCRIPT_DIR}/dist/${RELEASE_NAME}.tar.gz"

cd "$SCRIPT_DIR"

if ! command -v pyinstaller >/dev/null 2>&1; then
    echo "pyinstaller is not installed. Install the Python dependencies first." >&2
    exit 1
fi

pyinstaller \
    --name chordflask \
    --onefile \
    --hidden-import=numba \
    --hidden-import=numba.core \
    --hidden-import=numba.core.types \
    --hidden-import=llvmlite \
    --copy-metadata=imageio \
    --copy-metadata=moviepy \
    --additional-hooks-dir=pyinstaller_hooks \
    --exclude-module=imageio_ffmpeg.binaries \
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
semver="$(head -n1 "${PROJECT_ROOT}/VERSION")"
printf '%s %s %s\n' "$semver" "$(date -u +'%Y-%m-%d %H:%M')" "$(git -C "${PROJECT_ROOT}" rev-parse --short HEAD)" \
    > "${RELEASE_DIR}/VERSION"
chmod +x "${RELEASE_DIR}/chordflask" "${RELEASE_DIR}/chordflask.sh" "${RELEASE_DIR}/install_vamp.sh"
tar -C "${SCRIPT_DIR}/dist" -czf "${RELEASE_ARCHIVE}" "${RELEASE_NAME}"

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
