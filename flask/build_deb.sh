#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="${CHORDFLASK_VENV:-${HOME}/.venvs/chordflask}"
export PATH="$VENV_DIR/bin:$PATH"

command -v dpkg-deb >/dev/null || { echo 'dpkg-deb is required to build a Debian package.' >&2; exit 1; }
[[ "$(uname -m)" == x86_64 ]] || { echo 'The Debian standalone package requires an amd64 build host.' >&2; exit 1; }

# Explicit reuse is for a bundle built by the canonical standalone path.
# Without it, build and check the standalone rather than reuse stale output.
if [[ $# -eq 0 ]]; then
    CHORDFLASK_SUPPRESS_COPY_HINT=1 make -C "$PROJECT_ROOT" standalone "VENV_DIR=$VENV_DIR"
    release_name="$(cat "$SCRIPT_DIR/dist/.latest-release")"
    bundle="$SCRIPT_DIR/dist/$release_name"
elif [[ $# -eq 2 && "$1" == --standalone-dir ]]; then
    bundle="$2"
else
    echo "Usage: $0 [--standalone-dir DIRECTORY]" >&2
    exit 2
fi

export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(git -C "$PROJECT_ROOT" log -1 --format=%ct)}"
"$VENV_DIR/bin/python" "$SCRIPT_DIR/deb_package.py" build "$bundle" "$SCRIPT_DIR/dist"
package="$SCRIPT_DIR/dist/$(basename "$bundle").deb"
printf '\nDebian package:\n%s\n\nInstall:\nsudo apt install %q\n' "$package" "$package"
