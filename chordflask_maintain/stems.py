"""Framework-free inspection and conservative cleanup of Demucs stem storage.

ChordFlask stores optional Demucs stems below a media directory:

```text
.chordflask/stems/demucs/htdemucs/<media-key>/<generation>/<stem>.flac
```

and registers the four FLAC files as one
``audio_tracks["demucs:htdemucs"]`` set in the analysis JSON. This module
inspects that storage (read-only) or removes only unreferenced ("orphan")
generation directories, without ever invoking Demucs.

It imports only ``chordflask_base`` and the standard library — no Flask, no
analysis engine, no torch, no librosa, and no import of the optional Demucs
producer package.
"""

from __future__ import annotations

import fcntl
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from chordflask_base import ANALYSIS_DIR_NAME, DEMUCS_STEM_NAMES, ChordTrackRepository

from chordflask_maintain.migrate import (
    MigrationFileError,
    classify_analysis,
    read_analysis_json,
)
from chordflask_maintain.storage import worker_is_active

# Consumer-side identifier matching the producer's set id. It is defined here
# so this framework-free package never imports the optional producer package.
DEMUCS_AUDIO_SET_ID = "demucs:htdemucs"

_STEMS_REL = Path("stems") / "demucs" / "htdemucs"


def stems_root(media_dir) -> Path:
    """Return the base directory that holds all Demucs generations."""
    return Path(media_dir) / ANALYSIS_DIR_NAME / _STEMS_REL


@dataclass
class StemRecord:
    """One media analysis that registers a Demucs stem set."""

    media_stem: str
    status: str  # "complete" | "incomplete"
    generation: Path | None = None
    missing_files: list = field(default_factory=list)


@dataclass
class StemsReport:
    """Result of inspecting one media directory's Demucs stem storage."""

    media_dir: Path
    stems_root: Path
    exists: bool
    records: list = field(default_factory=list)
    orphans: list = field(default_factory=list)  # (generation Path, bytes)
    total_bytes: int = 0
    invalid: list = field(default_factory=list)  # (filename, reason)
    notes: list = field(default_factory=list)


@dataclass
class StemsCleanupResult:
    """Outcome of one orphan-generation cleanup."""

    removed: list = field(default_factory=list)
    removed_bytes: int = 0
    refused: bool = False
    reason: str = ""
    failures: list = field(default_factory=list)


def _format_bytes(size: int) -> str:
    if size >= 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024 * 1024):.1f} GB"
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def _analysis_dir(media: Path) -> Path | None:
    """Return the real ``.chordflask`` directory, or None when unusable."""
    chordflask = media / ANALYSIS_DIR_NAME
    if chordflask.is_symlink() or not chordflask.is_dir():
        return None
    return chordflask


def _iter_json_files(chordflask: Path):
    try:
        return sorted(
            path
            for path in chordflask.glob("*.json")
            if path.is_file() and not path.is_symlink()
        )
    except OSError:
        return []


def _referenced_generation(media: Path, set_data: dict) -> Path | None:
    """Return the resolved generation directory referenced by one stem set.

    Derived purely from the validated relative stem path in the JSON, so it
    does not depend on whether the FLAC files currently exist on disk.
    """
    tracks = set_data.get("tracks")
    if not isinstance(tracks, dict):
        return None
    for stem in DEMUCS_STEM_NAMES:
        entry = tracks.get(stem)
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            try:
                return (media / Path(entry["path"])).resolve().parent
            except OSError:
                continue
    return None


def _stem_record(media: Path, media_stem: str, set_data: dict) -> StemRecord:
    tracks = set_data.get("tracks")
    missing = []
    for stem in DEMUCS_STEM_NAMES:
        entry = tracks.get(stem) if isinstance(tracks, dict) else None
        relative = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(relative, str):
            missing.append(stem)
            continue
        try:
            candidate = media / Path(relative)
            if candidate.is_symlink() or not candidate.is_file():
                missing.append(stem)
        except OSError:
            missing.append(stem)
    status = "complete" if not missing else "incomplete"
    return StemRecord(
        media_stem=media_stem,
        status=status,
        generation=_referenced_generation(media, set_data),
        missing_files=missing,
    )


def _iter_subdirs(path: Path):
    try:
        entries = list(path.iterdir())
    except OSError:
        return []
    result = []
    for entry in entries:
        try:
            if entry.is_dir() and not entry.is_symlink():
                result.append(entry)
        except OSError:
            continue
    result.sort(key=lambda entry: entry.name)
    return result


def _dir_size(path: Path) -> int:
    total = 0
    for root, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
        for name in files:
            child = Path(root) / name
            if child.is_symlink():
                continue
            try:
                total += child.stat().st_size
            except OSError:
                continue
    return total


def _orphan_generations(media: Path, referenced: set) -> tuple[list, int, list]:
    """Return (orphans, orphan_bytes, notes) for unreferenced generations."""
    root = stems_root(media)
    if root.is_symlink() or not root.is_dir():
        return [], 0, []
    orphans = []
    orphan_bytes = 0
    notes = []
    for key_dir in _iter_subdirs(root):
        for gen_dir in _iter_subdirs(key_dir):
            try:
                resolved = gen_dir.resolve()
            except OSError:
                notes.append(f"skipped unresolvable generation dir: {gen_dir.name}")
                continue
            if resolved in referenced:
                continue
            size = _dir_size(gen_dir)
            orphans.append((gen_dir, size))
            orphan_bytes += size
    return orphans, orphan_bytes, notes


def inspect_stems(media_dir) -> StemsReport:
    """Inspect one media directory's Demucs stem storage (read-only)."""
    media = Path(media_dir).expanduser()
    if not media.is_dir():
        raise ValueError(f"media directory does not exist or is not a directory: {media}")

    root = stems_root(media)
    chordflask = _analysis_dir(media)
    exists = chordflask is not None and not root.is_symlink() and root.is_dir()

    report = StemsReport(media_dir=media, stems_root=root, exists=exists)
    if chordflask is None:
        return report

    referenced: set = set()
    for json_path in _iter_json_files(chordflask):
        try:
            data = read_analysis_json(json_path)
        except MigrationFileError as error:
            report.invalid.append((json_path.name, str(error)))
            continue
        try:
            kind = classify_analysis(data)
        except MigrationFileError as error:
            report.invalid.append((json_path.name, str(error)))
            continue
        if kind is None:
            continue  # non-analysis JSON (e.g. *.training.json)
        try:
            track = ChordTrackRepository().load(str(json_path))
        except Exception as error:  # noqa: BLE001 - validation boundary
            report.invalid.append((json_path.name, str(error)))
            continue
        if not track.has_audio_track(DEMUCS_AUDIO_SET_ID):
            continue
        set_data = track.audio_track_data(DEMUCS_AUDIO_SET_ID)
        record = _stem_record(media, json_path.stem, set_data)
        report.records.append(record)
        if record.generation is not None:
            referenced.add(record.generation)

    if exists:
        orphans, orphan_bytes, notes = _orphan_generations(media, referenced)
        report.orphans = orphans
        report.notes = notes
        report.total_bytes = _dir_size(root)

    return report


def format_stems_report(report: StemsReport) -> str:
    """Render a human-readable report for one stem-storage inspection."""
    lines = [str(report.stems_root)]
    if not report.exists:
        lines.append("  (no Demucs stem storage)")
        return "\n".join(lines)

    if report.records:
        lines.append("  registered sets:")
        for record in sorted(report.records, key=lambda item: item.media_stem):
            suffix = (
                ""
                if record.status == "complete"
                else f" (missing: {', '.join(record.missing_files)})"
            )
            lines.append(f"    {record.media_stem}: {record.status}{suffix}")
    else:
        lines.append("  registered sets: none")

    for name, reason in report.invalid:
        lines.append(f"  invalid JSON  {name}: {reason}")

    orphan_bytes = sum(size for _, size in report.orphans)
    lines.append(
        f"  orphan generations: {len(report.orphans)} "
        f"({_format_bytes(orphan_bytes)})"
    )
    for path, size in report.orphans:
        try:
            relative = path.relative_to(report.stems_root)
        except ValueError:
            relative = path
        lines.append(f"    orphan  {relative}  {_format_bytes(size)}")

    lines.append(f"  total stem storage: {_format_bytes(report.total_bytes)}")

    for note in report.notes:
        lines.append(f"  note: {note}")

    return "\n".join(lines)


def demucs_lock_is_active(chordflask: Path) -> bool:
    """Return whether any Demucs per-media lock is currently held."""
    try:
        lock_files = [
            path
            for path in chordflask.glob("*.demucs.lock")
            if path.is_file() and not path.is_symlink()
        ]
    except OSError:
        return False
    for lock_path in lock_files:
        try:
            with lock_path.open("a+") as handle:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return True
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            continue
    return False


def cleanup_orphan_stems(media_dir, *, dry_run: bool = False) -> StemsCleanupResult:
    """Delete unreferenced Demucs generation directories in one media directory.

    Only generation directories under ``.chordflask/stems/demucs/htdemucs/``
    that are not referenced by any valid analysis JSON are candidates. Refuses
    (deleting nothing) while an analysis worker or a Demucs process is active,
    or when any actual analysis JSON is unreadable/invalid, because orphan
    status cannot then be proven safely. Symlinks are never followed.
    """
    media = Path(media_dir).expanduser()
    if not media.is_dir():
        raise ValueError(f"media directory does not exist or is not a directory: {media}")

    result = StemsCleanupResult()

    if worker_is_active():
        result.refused = True
        result.reason = "an analysis worker is active; stem storage was not changed"
        return result

    chordflask = _analysis_dir(media)
    if chordflask is None:
        return result

    if demucs_lock_is_active(chordflask):
        result.refused = True
        result.reason = "a Demucs process holds a lock; stem storage was not changed"
        return result

    referenced: set = set()
    for json_path in _iter_json_files(chordflask):
        try:
            data = read_analysis_json(json_path)
        except MigrationFileError as error:
            result.refused = True
            result.reason = f"cannot read {json_path.name}: {error}"
            return result
        try:
            kind = classify_analysis(data)
        except MigrationFileError as error:
            result.refused = True
            result.reason = f"cannot classify {json_path.name}: {error}"
            return result
        if kind is None:
            continue  # non-analysis JSON (e.g. *.training.json)
        try:
            track = ChordTrackRepository().load(str(json_path))
        except Exception as error:  # noqa: BLE001 - validation boundary
            result.refused = True
            result.reason = f"invalid analysis JSON {json_path.name}: {error}"
            return result
        if track.has_audio_track(DEMUCS_AUDIO_SET_ID):
            generation = _referenced_generation(
                media, track.audio_track_data(DEMUCS_AUDIO_SET_ID)
            )
            if generation is not None:
                referenced.add(generation)

    orphans, _, _ = _orphan_generations(media, referenced)
    for gen_dir, size in orphans:
        if dry_run:
            result.removed.append(str(gen_dir))
            result.removed_bytes += size
            continue
        try:
            shutil.rmtree(gen_dir)
        except OSError as error:
            result.failures.append(f"could not remove {gen_dir}: {error}")
            continue
        result.removed.append(str(gen_dir))
        result.removed_bytes += size

    return result


def format_stems_cleanup(result: StemsCleanupResult, *, dry_run: bool = False) -> str:
    """Render one stem-storage cleanup result."""
    verb = "would remove" if dry_run else "removed"
    lines = []
    if result.refused:
        lines.append(f"REFUSED: {result.reason}")
        lines.append("(nothing deleted)")
        return "\n".join(lines)

    for path in result.removed:
        lines.append(f"  {verb}  {path}")
    for failure in result.failures:
        lines.append(f"  ERROR    {failure}")

    if result.removed:
        lines.append(
            f"  {verb} {len(result.removed)} generation(s), "
            f"{_format_bytes(result.removed_bytes)}"
        )
    else:
        lines.append("  nothing to remove")
    return "\n".join(lines)


__all__ = [
    "DEMUCS_AUDIO_SET_ID",
    "StemRecord",
    "StemsCleanupResult",
    "StemsReport",
    "cleanup_orphan_stems",
    "demucs_lock_is_active",
    "format_stems_cleanup",
    "format_stems_report",
    "inspect_stems",
    "stems_root",
]
