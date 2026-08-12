#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
    printf '%s\n' \
        "Usage: $0 [--help]" \
        "" \
        "Restore executable bits lost by Nextcloud cross-filesystem sync." \
        "" \
        "Primary mode: reads Git tree mode 100755 from the current HEAD." \
        "Fallback mode: scans for files with a shebang (#!) on line 1." \
        "" \
        "Options:" \
        "  --help    Show this help text"
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi

fixed=0
already=0
missing=0

restore_from_git() {
    local file="$1"
    local rel
    rel="$(realpath --relative-to="$ROOT_DIR" "$file")"
    if [[ ! -f "$file" ]]; then
        printf '  SKIP (not a regular file) %s\n' "$rel"
        return 0
    fi
    local mode
    mode="$(git -C "$ROOT_DIR" ls-files --full-name -s "$rel" 2>/dev/null | awk '{print $1}')" || true
    if [[ "$mode" == "100755" ]]; then
        if [[ -x "$file" ]]; then
            ((already++)) || true
        else
            printf '  +x %s\n' "$rel"
            chmod +x "$file"
            ((fixed++)) || true
        fi
    elif [[ "$mode" == "100644" ]]; then
        if [[ -x "$file" ]]; then
            printf '  -x %s\n' "$rel"
            chmod -x "$file"
            ((fixed++)) || true
        fi
    else
        printf '  SKIP (not in Git) %s\n' "$rel"
        ((missing++)) || true
    fi
    return 0
}

shebang_fallback() {
    local file="$1"
    local rel
    rel="$(realpath --relative-to="$ROOT_DIR" "$file")"
    if [[ ! -f "$file" ]]; then
        printf '  SKIP (not a regular file) %s\n' "$rel"
        return 0
    fi
    if ! head -n1 "$file" 2>/dev/null | grep -q '^#!'; then
        return 0
    fi
    if [[ -x "$file" ]]; then
        return 0
    fi
    printf '  +x (shebang) %s\n' "$rel"
    chmod +x "$file"
    ((fixed++)) || true
    return 0
}

# Primary: restore from Git tree modes for tracked files. The shebang fallback
# is deliberately not run afterward because it must not override a tracked
# 100644 mode merely because that file has a shebang.
if git -C "$ROOT_DIR" rev-parse HEAD &>/dev/null; then
    while IFS= read -r -d '' rel; do
        restore_from_git "$ROOT_DIR/$rel"
    done < <(git -C "$ROOT_DIR" ls-files -z 2>/dev/null || true)
else
    printf '%s\n' "Git repository not detected; falling back to shebang scan."
    while IFS= read -r -d '' file; do
        shebang_fallback "$file"
    done < <(find "$ROOT_DIR/flask" "$ROOT_DIR/scripts" \
        -type f \( -name '*.sh' -o -name '*.py' -o -name '*.bash' \) \
        -not -path '*/helpers/*' -print0 2>/dev/null || true)
fi

printf '%s\n' "Done: $fixed fixed, $already already correct, $missing not in Git."
