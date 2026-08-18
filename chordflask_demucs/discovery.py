"""Standalone media discovery for the Demucs batch command."""

from __future__ import annotations

from pathlib import Path

SUPPORTED_SUFFIXES = frozenset({".mp3", ".mp4", ".webm"})
SUFFIX_PRIORITY = {".mp4": 0, ".webm": 1, ".mp3": 2}


class DiscoveryError(FileNotFoundError):
    """The requested target is not a usable media file or directory."""


def _media_candidates(directory: Path) -> list[Path]:
    candidates = []
    try:
        entries = directory.iterdir()
    except OSError as error:
        raise DiscoveryError(f"Could not read media directory {directory}: {error}") from error
    for entry in entries:
        try:
            if entry.is_file() and entry.suffix.lower() in SUPPORTED_SUFFIXES:
                candidates.append(entry)
        except OSError:
            continue
    candidates.sort(
        key=lambda path: (
            path.stem.casefold(),
            SUFFIX_PRIORITY[path.suffix.lower()],
            path.name.casefold(),
            path.name,
        )
    )
    preferred = {}
    for path in candidates:
        preferred.setdefault(path.stem.casefold(), path)
    try:
        return sorted(
            preferred.values(), key=lambda path: (path.stat().st_size, path.name.casefold(), path.name)
        )
    except OSError as error:
        raise DiscoveryError(f"Could not inspect media directory {directory}: {error}") from error


def discover_target(target: Path) -> list[Path]:
    if target.is_dir():
        return _media_candidates(target)
    if target.is_file():
        if target.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise DiscoveryError(f"Unsupported media file (MP3/MP4/WebM): {target}")
        return [target]
    raise DiscoveryError(f"Not a media file or directory: {target}")


__all__ = ["DiscoveryError", "discover_target"]
