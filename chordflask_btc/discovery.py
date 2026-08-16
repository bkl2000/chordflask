"""Non-recursive media discovery with ChordFlask same-stem priority."""

from __future__ import annotations

from pathlib import Path

SUPPORTED_MEDIA_SUFFIXES = frozenset({".mp3", ".mp4", ".webm"})
MEDIA_SUFFIX_PRIORITY = {".mp4": 0, ".webm": 1, ".mp3": 2}


class DirectoriesError(ValueError):
    """The media directory is invalid."""


def discover_media_directory(directory: Path) -> list[Path]:
    """Non-recursively discover one preferred media file per stem, sorted by size.

    Mirrors ChordFlask's preferred-media rule: one file per casefolded stem using
    the format priority MP4 > WebM > MP3. The result is sorted smallest first by
    ``(size, name.casefold(), name)`` so ties are deterministic.
    """
    if not directory.is_dir():
        raise DirectoriesError(
            f"Media directory does not exist or is not a directory: {directory}"
        )
    candidates: list[Path] = []
    for entry in directory.iterdir():
        if entry.is_symlink() or not entry.is_file():
            continue
        if entry.suffix.lower() not in SUPPORTED_MEDIA_SUFFIXES:
            continue
        candidates.append(entry)
    candidates.sort(
        key=lambda path: (
            path.stem.casefold(),
            MEDIA_SUFFIX_PRIORITY[path.suffix.lower()],
            path.name.casefold(),
        )
    )
    preferred: dict[str, Path] = {}
    for entry in candidates:
        preferred.setdefault(entry.stem.casefold(), entry)
    return sorted(
        preferred.values(),
        key=lambda path: (path.stat().st_size, path.name.casefold(), path.name),
    )
