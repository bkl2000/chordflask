#!/usr/bin/env bash
set -euo pipefail

# Only this external child leaves the PyInstaller library environment.
if [[ -n "${LD_LIBRARY_PATH_ORIG:-}" ]]; then
    export LD_LIBRARY_PATH="$LD_LIBRARY_PATH_ORIG"
else
    unset LD_LIBRARY_PATH
fi
exec "${CHORDFLASK_SYSTEM_FFMPEG:?System FFmpeg was not configured}" "$@"
