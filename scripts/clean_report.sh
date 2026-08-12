#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${CLEAN_REPORT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

if [[ ! -d "$ROOT_DIR" ]]; then
    echo "Clean-report root is not a directory: ${ROOT_DIR}" >&2
    exit 2
fi

CLEANABLE=(
    flask/build
    flask/dist
    .pytest_cache
    .mypy_cache
    .ruff_cache
    .coverage
    htmlcov
)

total=0
count=0

report_path() {
    local path="$1"
    local rel="${path#"$ROOT_DIR"/}"
    local size_kb

    if ! size_kb=$(du -sk -- "$path" 2>/dev/null | cut -f1); then
        printf '  unable to measure  %s\n' "$rel" >&2
        return
    fi
    if [[ -z "$size_kb" ]]; then
        return
    fi

    total=$((total + size_kb))
    count=$((count + 1))
    if (( size_kb >= 1048576 )); then
        printf '  %5s GB  %s\n' "$(( size_kb / 1048576 ))" "$rel"
    elif (( size_kb >= 1024 )); then
        printf '  %5s MB  %s\n' "$(( size_kb / 1024 ))" "$rel"
    else
        printf '  %5s KB  %s\n' "$size_kb" "$rel"
    fi
}

for rel in "${CLEANABLE[@]}"; do
    path="$ROOT_DIR/$rel"
    if [[ -e "$path" || -L "$path" ]]; then
        report_path "$path"
    fi
done

search_roots=()
for rel in flask scripts tests; do
    [[ -d "$ROOT_DIR/$rel" ]] && search_roots+=("$ROOT_DIR/$rel")
done

if [[ ${#search_roots[@]} -gt 0 ]]; then
    while IFS= read -r -d '' path; do
        report_path "$path"
    done < <(
        find "${search_roots[@]}" \
            \( -path "$ROOT_DIR/flask/build" -o -path "$ROOT_DIR/flask/dist" \
               -o -name videos -o -name .chordflask -o -name backups \
               -o -name vendor -o -name .git \) -prune -o \
            \( -type d -name __pycache__ -print0 -prune \) -o \
            \( -type f \( -name '*.pyc' -o -name '*.pyo' \) -print0 \)
    )
fi

echo ""
printf 'Cleanable: %s entries, ' "$count"
if (( total >= 1048576 )); then
    printf '%s GB\n' "$(( total / 1048576 ))"
elif (( total >= 1024 )); then
    printf '%s MB\n' "$(( total / 1024 ))"
else
    printf '%s KB\n' "$total"
fi
printf '%s\n' 'Protected project data is excluded and is never scanned.'
printf '%s\n' 'Run "make clean" to free this space.'
