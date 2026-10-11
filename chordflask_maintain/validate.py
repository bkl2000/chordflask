"""Validate ChordFlask analysis JSON files (framework-free).

Validation uses the same neutral validator as ``ChordTrackRepository``,
which accepts schema v1/v2/v3 and unversioned legacy files. The analysis-file
classification is shared with the migration path, so a non-analysis JSON file
(such as ``*.training.json``) is ignored rather than reported as valid. No
Flask, torch, librosa, or music21 import is needed.
"""

from __future__ import annotations

from pathlib import Path

from chordflask_base import analysis_json_path, validate_analysis

from chordflask_maintain.migrate import (
    MigrationFileError,
    classify_analysis,
    read_analysis_json,
)

_MEDIA_SUFFIXES = frozenset({".mp3", ".mp4", ".webm"})


def analysis_for_media(media_path: Path) -> Path:
    """Return one media file's unambiguous existing analysis JSON path."""
    media = Path(media_path)
    if media.suffix.lower() not in _MEDIA_SUFFIXES:
        raise ValueError(f"not an MP3, MP4, or WebM media file: {media}")
    try:
        entries = list(media.parent.iterdir())
    except OSError as error:
        raise ValueError(f"cannot inspect media directory {media.parent}: {error}") from error
    matches = sorted(
        entry
        for entry in entries
        if not entry.is_symlink()
        and entry.is_file()
        and entry.stem == media.stem
        and entry.suffix.lower() in _MEDIA_SUFFIXES
    )
    if len(matches) > 1:
        names = ", ".join(path.name for path in matches)
        raise ValueError(
            f"ambiguous media basename {media.stem!r}: {names} share one analysis path; "
            "validate the JSON file directly"
        )
    json_path = analysis_json_path(media)
    if json_path.is_symlink() or not json_path.is_file():
        raise FileNotFoundError(
            f"no analysis JSON for {media}; expected {json_path}"
        )
    return json_path


def validate_file(json_path: Path) -> tuple[str, str | None]:
    """Classify and validate one JSON file.

    Returns ``("valid"|"invalid"|"ignore", message)`` where ``message`` is the
    error text for ``"invalid"`` or migration guidance for valid older storage. A non-analysis JSON
    file yields ``("ignore", None)``.
    """
    try:
        data = read_analysis_json(json_path)
    except MigrationFileError as exc:
        return ("invalid", str(exc))

    try:
        kind = classify_analysis(data)
    except MigrationFileError as exc:
        return ("invalid", str(exc))

    if kind is None:
        return ("ignore", None)

    try:
        status = validate_analysis(data, json_path)
        guidance = (
            "valid migratable schema; run chordflask-maintain migrate-schema on the media directory"
            if status == "migratable" else None
        )
        return ("valid", guidance)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as error:
        return ("invalid", str(error))


def analysis_json_files(directory: Path) -> list[Path]:
    """Return the analysis JSON files under ``directory/.chordflask``."""
    analysis_dir = Path(directory) / ".chordflask"
    if not analysis_dir.is_dir():
        return []
    return sorted(
        path for path in analysis_dir.glob("*.json")
        if path.is_file() and not path.is_symlink()
    )


def validate_directory(directory: Path) -> dict[str, int]:
    """Validate every analysis JSON in a directory.

    Returns ``{"valid", "invalid"}``. Prints one line per invalid file.
    Non-analysis JSON files are ignored silently. Raises ``ValueError`` when
    ``directory`` is not a directory.
    """
    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")

    counts = {"valid": 0, "invalid": 0}
    for json_path in analysis_json_files(root):
        kind, message = validate_file(json_path)
        if kind == "ignore":
            continue
        if kind == "valid":
            counts["valid"] += 1
            print(f"OK: {json_path.name}" + (f" ({message})" if message else ""))
        else:
            counts["invalid"] += 1
            print(f"ERROR: {json_path.name}: {message}")
    return counts
