"""Shared non-recursive media discovery for the batch/CLI helpers.

Discovery is shared with the active app through ``flask/media_library.py``:
only MP4/WebM/MP3 files directly inside the target directory are returned,
using the active same-stem priority (MP4 > WebM > MP3) and sorted smallest
first.
"""

from pathlib import Path

from ..media_library import preferred_media_files


def find_media_files(media_dir):
    root = Path(media_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"Media directory does not exist: {media_dir}")
    files = preferred_media_files(root)
    return sorted(files, key=lambda path: (path.stat().st_size, path.name.lower()))
