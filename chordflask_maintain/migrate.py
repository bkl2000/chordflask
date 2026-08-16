"""Idempotent Schema-v3 migration for ChordFlask analysis files (no reanalysis).

Reads ``DIRECTORY/.chordflask/*.json``, migrates legacy analysis files (schema 1,
schema 2, or unversioned with ``base_chords``) to Schema 3 through
``ChordTrackRepository.load()`` + ``save()``, and skips files that are already
Schema 3. Non-analysis JSON files (no ``schema_version`` and no ``base_chords``,
such as ``*.training.json``) are ignored silently.

This is a pure schema roundtrip: no audio processing, no Chordino/QM reanalysis,
and no import of the Flask app or the training package. The atomic write
(fsync + ``os.replace``) in ``ChordTrackRepository.save()`` guarantees the
original file stays byte-identical on any error.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chordflask_base import ChordTrackRepository


class MigrationFileError(Exception):
    """One analysis file could not be migrated or classified."""


def read_analysis_json(json_path: Path) -> Any:
    """Read and JSON-parse an analysis file.

    Raises :class:`MigrationFileError` when the file is unreadable or is not
    valid JSON.
    """
    try:
        with json_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationFileError(f"could not read JSON: {exc}") from exc


def classify_analysis(data: Any) -> str | None:
    """Classify a parsed analysis JSON root.

    Returns ``"v3"`` for schema 3, ``"legacy"`` for schema 1/2 or an
    unversioned file that has ``base_chords``, or ``None`` for a non-analysis
    JSON file. Raises :class:`MigrationFileError` for a non-object root or an
    unsupported schema version.
    """
    if not isinstance(data, dict):
        raise MigrationFileError("JSON root must be an object")

    version = data.get("schema_version")
    if version == 3:
        return "v3"
    if version is None and "base_chords" not in data:
        return None
    if version in (1, 2, None):
        return "legacy"
    raise MigrationFileError(f"unsupported schema version {version!r}")


def migrate_analysis_file(json_path: Path) -> tuple[str, str | None]:
    """Classify and migrate one analysis file.

    Returns ``("ok", label)`` on success, ``("skip", "already schema 3")`` for an
    already-migrated file, or ``("ignore", None)`` for a non-analysis JSON file.
    Raises :class:`MigrationFileError` for unreadable, invalid, or unsupported
    files; in that case the file is left byte-identical.
    """
    data = read_analysis_json(json_path)
    kind = classify_analysis(data)
    if kind == "v3":
        return ("skip", "already schema 3")
    if kind is None:
        return ("ignore", None)

    repo = ChordTrackRepository()
    try:
        track = repo.load(str(json_path))
        repo.save(track, str(json_path))
    except Exception as exc:
        raise MigrationFileError(f"migration failed: {exc}") from exc

    version = data.get("schema_version")
    label = {1: "schema 1 -> 3", 2: "schema 2 -> 3", None: "legacy -> 3"}[version]
    return ("ok", label)


def migrate_directory(directory: Path) -> dict[str, int]:
    """Migrate every analysis JSON in ``directory/.chordflask``.

    Returns ``{"files", "migrated", "skipped", "failed"}``. Per-file lines are
    printed to stdout; one file's error never aborts the batch. Raises
    :class:`ValueError` when ``directory`` is not a directory.
    """
    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")

    counts = {"files": 0, "migrated": 0, "skipped": 0, "failed": 0}
    analysis_dir = root / ".chordflask"
    if not analysis_dir.is_dir():
        return counts

    json_files = sorted(
        path for path in analysis_dir.glob("*.json")
        if path.is_file() and not path.is_symlink()
    )
    for json_path in json_files:
        try:
            kind, label = migrate_analysis_file(json_path)
        except MigrationFileError as exc:
            counts["files"] += 1
            counts["failed"] += 1
            print(f"ERROR: {json_path.name}: {exc}")
            continue
        if kind == "ignore":
            continue
        counts["files"] += 1
        if kind == "ok":
            counts["migrated"] += 1
            print(f"OK: {label}")
        else:
            counts["skipped"] += 1
            print("SKIP: already schema 3")
    return counts
