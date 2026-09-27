#!/usr/bin/env bash
set -euo pipefail

# Recursively replace existing .cho sidecars using LRCLIB-first lyric lookup.
# Usage: scripts/regenerate-lyrics.sh DIRECTORY

usage() {
    echo "Usage: ${0##*/} DIRECTORY"
    echo "Regenerate existing .cho files that have same-stem MP3, MP4, or WebM media."
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi
if [[ $# -ne 1 ]]; then
    usage >&2
    exit 2
fi

target_directory=$1
if [[ ! -d "$target_directory" ]]; then
    echo "Directory not found: ${target_directory}" >&2
    exit 2
fi

generator=${CHORDFLASK_GENLYRICS:-${HOME}/.venvs/chordflask-lyrics/bin/chordflask-genlyrics}
if [[ ! -x "$generator" ]]; then
    echo "Lyrics generator is not executable: ${generator}" >&2
    exit 2
fi

found=0
regenerated=0
skipped=0
failed=0

while IFS= read -r -d '' chord_file; do
    ((found += 1))
    media_file=
    stem=${chord_file%.cho}
    for suffix in mp3 MP3 mp4 MP4 webm WEBM; do
        candidate="${stem}.${suffix}"
        if [[ -f "$candidate" ]]; then
            media_file=$candidate
            break
        fi
    done

    if [[ -z "$media_file" ]]; then
        echo "SKIP: no same-stem media for ${chord_file}"
        ((skipped += 1))
        continue
    fi

    echo "REGENERATE: ${media_file}"
    if "$generator" --force --lyrics lrclib:lrc:embedded "$media_file"; then
        ((regenerated += 1))
    else
        echo "FAIL: ${media_file}" >&2
        ((failed += 1))
    fi
done < <(find "$target_directory" -type f -name '*.cho' -print0)

echo "Summary: found=${found} regenerated=${regenerated} skipped=${skipped} failed=${failed}"
((failed == 0))
