"""Pure media discovery shared by the web app and optional batch tools."""

from pathlib import Path

from chordflask_config import MEDIA_SUFFIX_PRIORITY, SUPPORTED_MEDIA_SUFFIXES


def preferred_media_files(directory):
    """Return one supported file per stem, using the configured format priority."""
    root = Path(directory)
    candidates = [
        entry
        for entry in root.iterdir()
        if entry.is_file() and entry.suffix.lower() in SUPPORTED_MEDIA_SUFFIXES
    ]
    candidates.sort(key=lambda entry: (
        entry.stem.casefold(),
        MEDIA_SUFFIX_PRIORITY[entry.suffix.lower()],
        entry.name.casefold(),
        entry.name,
    ))
    preferred = {}
    for entry in candidates:
        preferred.setdefault(entry.stem.casefold(), entry)
    return sorted(preferred.values(), key=lambda entry: entry.name)
