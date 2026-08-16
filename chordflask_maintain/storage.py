"""Framework-free inspection and cleanup of one media directory's analysis storage.

ChordFlask stores analysis and derived artifacts in a per-media-directory
``.chordflask`` directory. This module inspects exactly one such directory
without changing anything (inspection) or removes only explicitly requested,
reproducible leftover categories (cleanup).

It imports only the Python standard library — no Flask, queue, analysis engine,
torch, librosa, or music21. The only runtime coupling is the analysis-worker
lock file under ``~/.chordflask`` (or ``CHORDFLASK_QUEUE_DIR``), checked with a
plain ``fcntl.flock`` so cleanup refuses to run while a worker is active.
"""

from __future__ import annotations

import fcntl
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

CHORDFLASK_DIR_NAME = ".chordflask"

# MediaConverter creates a hidden conversion temp file
# ``.<stem>.convert-<random>.mp3`` in the analysis directory. Match exactly that
# producer format so a media file whose stem merely contains ".convert-" (and
# its analysis JSON) is never misclassified as a temporary file.
_CONVERT_TEMP_RE = re.compile(r"^\..+\.convert-[0-9A-Za-z_]+\.mp3$")

# Classification status values used in reports.
PROTECTED = "protected"
RECLAIMABLE = "reclaimable"
REVIEW = "review"

_WORKER_LOCK_NAME = "analysis_worker.lock"


@dataclass
class Category:
    """Aggregate counts and sizes for one artifact category."""

    name: str
    status: str
    count: int = 0
    bytes: int = 0


@dataclass
class StorageInspection:
    """Result of inspecting one media directory's ``.chordflask`` storage."""

    media_dir: Path
    chordflask_path: Path
    exists: bool
    categories: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def _video_source_exists(media_dir: Path, stem: str) -> bool:
    """Return whether ``stem`` names a video source in ``media_dir``.

    The cached analysis MP3 is only produced from a video source (MP4/WebM), so
    a ``<stem>.mp3`` inside ``.chordflask`` is a verified cache only when a
    matching video source exists beside it.
    """
    return any((media_dir / f"{stem}{suffix}").is_file() for suffix in (".mp4", ".webm"))


def _classify_entry(entry: Path, media_dir: Path) -> tuple[str, str]:
    """Return (category_name, status) for one ``.chordflask`` entry."""
    if entry.is_symlink():
        return "symlinks", REVIEW

    name = entry.name

    if entry.is_dir():
        if name.startswith(".") and (".analyze-" in name or ".reanalyze-" in name):
            return "orphan temp dirs", REVIEW
        return "other directories", REVIEW

    if ".corrupt-" in name and name.endswith(".json"):
        return "corrupt backups", REVIEW

    if _CONVERT_TEMP_RE.match(name):
        return "temporary files", REVIEW

    suffix = entry.suffix.lower()
    if suffix == ".json":
        return "analysis JSON", PROTECTED
    if suffix == ".mp3":
        if _video_source_exists(media_dir, entry.stem):
            return "cached audio", RECLAIMABLE
        return "unverified audio", REVIEW
    if suffix == ".xml":
        return "MusicXML", RECLAIMABLE
    if suffix == ".mid":
        return "MIDI", RECLAIMABLE
    if suffix == ".song":
        return "song metadata", REVIEW
    if suffix in (".md", ".pdf"):
        return "leadsheet exports", RECLAIMABLE
    return "other", REVIEW


def _entry_size(entry: Path) -> tuple[int, int]:
    """Return (file_count, total_bytes) for a file or directory entry.

    Directory traversal never follows symlinks, so an entry cannot escape the
    ``.chordflask`` scope.
    """
    if entry.is_file() and not entry.is_symlink():
        try:
            return 1, entry.stat().st_size
        except OSError:
            return 0, 0

    if entry.is_dir() and not entry.is_symlink():
        count = 0
        total = 0
        for root, dirs, files in os.walk(entry, followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
            for name in files:
                path = Path(root) / name
                if path.is_symlink():
                    continue
                try:
                    total += path.stat().st_size
                    count += 1
                except OSError:
                    continue
        return count, total

    return 0, 0


def inspect_storage(media_dir) -> StorageInspection:
    """Inspect the ``.chordflask`` directory of one media directory (read-only).

    Raises ``ValueError`` when ``media_dir`` is not an existing directory.
    Never modifies anything.
    """
    media = Path(media_dir).expanduser()
    if not media.is_dir():
        raise ValueError(f"media directory does not exist or is not a directory: {media}")

    chordflask = media / CHORDFLASK_DIR_NAME

    if chordflask.is_symlink():
        return StorageInspection(
            media_dir=media,
            chordflask_path=chordflask,
            exists=False,
            notes=["skipped (symbolic link)"],
        )

    if not chordflask.is_dir():
        return StorageInspection(
            media_dir=media,
            chordflask_path=chordflask,
            exists=False,
        )

    categories: dict[str, Category] = {}
    notes: list[str] = []

    try:
        entries = sorted(chordflask.iterdir(), key=lambda e: e.name)
    except OSError as error:
        return StorageInspection(
            media_dir=media,
            chordflask_path=chordflask,
            exists=True,
            notes=[f"unreadable: {error}"],
        )

    for entry in entries:
        name, status = _classify_entry(entry, media)
        if name == "symlinks":
            notes.append(f"skipped symlink: {entry.name}")
            continue
        count, size = _entry_size(entry)
        if count == 0 and size == 0 and name in ("other directories", "other"):
            continue
        category = categories.setdefault(name, Category(name=name, status=status))
        category.count += count
        category.bytes += size

    ordered = [
        categories[key]
        for key in (
            "analysis JSON",
            "cached audio",
            "unverified audio",
            "MusicXML",
            "MIDI",
            "leadsheet exports",
            "song metadata",
            "corrupt backups",
            "temporary files",
            "orphan temp dirs",
            "other directories",
            "other",
        )
        if key in categories
    ]
    ordered.extend(
        category
        for category in categories.values()
        if category.name not in {item.name for item in ordered}
    )

    return StorageInspection(
        media_dir=media,
        chordflask_path=chordflask,
        exists=True,
        categories=ordered,
        notes=notes,
    )


def _format_bytes(size: int) -> str:
    if size >= 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024 * 1024):.1f} GB"
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def format_storage_report(inspection: StorageInspection) -> str:
    """Render a human-readable report for one storage inspection."""
    lines = [str(inspection.chordflask_path)]
    if not inspection.exists:
        if inspection.notes:
            lines.append(f"  ({inspection.notes[0]})")
        else:
            lines.append("  (no analysis storage)")
        return "\n".join(lines)

    if not inspection.categories:
        lines.append("  (empty)")
    else:
        for category in inspection.categories:
            lines.append(
                f"  {category.name:<20} {category.count:>6}  "
                f"{_format_bytes(category.bytes):>10}  {category.status}"
            )

    for note in inspection.notes:
        lines.append(f"  note: {note}")

    return "\n".join(lines)


# ── conservative cleanup ────────────────────────────────────────────

_CORRUPT_BACKUP_RE = re.compile(r"\.corrupt-\d{8}T\d{12}Z-[0-9a-f]{8}\.json$")


@dataclass
class CleanupResult:
    """Outcome of one cleanup operation.

    ``removed_count`` counts removed cleanup candidates (a removed temporary
    directory counts as one), not every file inside it. ``removed_bytes`` is the
    recursive space reclaimed.
    """

    removed: list = field(default_factory=list)
    removed_count: int = 0
    removed_bytes: int = 0
    refused: bool = False
    reason: str = ""
    failures: list = field(default_factory=list)


def _storage_directory(media_dir):
    """Return the real ``.chordflask`` directory, or None when there is none.

    Raises ``ValueError`` when ``media_dir`` is not an existing directory.
    Symlinks to a ``.chordflask`` are never followed.
    """
    media = Path(media_dir).expanduser()
    if not media.is_dir():
        raise ValueError(f"media directory does not exist or is not a directory: {media}")
    chordflask = media / CHORDFLASK_DIR_NAME
    if chordflask.is_symlink() or not chordflask.is_dir():
        return None
    return chordflask


def queue_dir() -> Path:
    """Return the global ChordFlask state directory (worker lock, queue, logs)."""
    base = os.environ.get("CHORDFLASK_QUEUE_DIR")
    if base:
        return Path(base).expanduser()
    return Path.home() / ".chordflask"


def worker_is_active() -> bool:
    """Return whether an analysis worker currently holds the worker lock."""
    lock_file = queue_dir() / _WORKER_LOCK_NAME
    if not lock_file.exists():
        return False
    try:
        with lock_file.open("a+") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return False
    except OSError:
        return False


def _is_orphan_temp_dir(name):
    return name.startswith(".") and (".analyze-" in name or ".reanalyze-" in name)


def _is_convert_temp_file(name):
    return bool(_CONVERT_TEMP_RE.match(name))


def cleanup_orphan_temp(media_dir):
    """Delete orphaned analysis/conversion temp artifacts in one media directory.

    Refuses (without deleting anything) while an analysis worker is active.
    Never follows symlinks and never removes anything outside ``.chordflask``.
    """
    chordflask = _storage_directory(media_dir)
    result = CleanupResult()
    if chordflask is None:
        return result

    if worker_is_active():
        result.refused = True
        result.reason = "an analysis worker is active; temporary artifacts were not deleted"
        return result

    try:
        entries = sorted(chordflask.iterdir(), key=lambda e: e.name)
    except OSError as error:
        result.failures.append(f"cannot list {chordflask}: {error}")
        return result

    for entry in entries:
        if entry.is_symlink():
            continue
        is_dir_candidate = entry.is_dir() and _is_orphan_temp_dir(entry.name)
        is_file_candidate = entry.is_file() and _is_convert_temp_file(entry.name)
        if not (is_dir_candidate or is_file_candidate):
            continue

        _, size = _entry_size(entry)
        try:
            if is_dir_candidate:
                shutil.rmtree(entry)
            else:
                entry.unlink()
        except OSError as error:
            result.failures.append(f"could not remove {entry.name}: {error}")
            continue

        result.removed.append(entry.name)
        result.removed_count += 1
        result.removed_bytes += size

    return result


def cleanup_corrupt_backups(media_dir, older_than_days):
    """Delete corrupt-analysis backup files older than a retention age.

    Only files matching the exact producer format are candidates. Age is
    compared using each file's modification time (``st_mtime``). Valid analysis
    JSON, arbitrary JSON, malformed names, and symlinks are never candidates.
    """
    if (
        isinstance(older_than_days, bool)
        or not isinstance(older_than_days, (int, float))
        or older_than_days <= 0
    ):
        raise ValueError("older_than_days must be a positive number")

    chordflask = _storage_directory(media_dir)
    result = CleanupResult()
    if chordflask is None:
        return result

    cutoff = time.time() - older_than_days * 86400

    try:
        entries = sorted(chordflask.iterdir(), key=lambda e: e.name)
    except OSError as error:
        result.failures.append(f"cannot list {chordflask}: {error}")
        return result

    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            continue
        if not _CORRUPT_BACKUP_RE.search(entry.name):
            continue
        try:
            stat = entry.stat()
        except OSError as error:
            result.failures.append(f"cannot stat {entry.name}: {error}")
            continue
        if stat.st_mtime >= cutoff:
            continue
        try:
            entry.unlink()
        except OSError as error:
            result.failures.append(f"could not remove {entry.name}: {error}")
            continue

        result.removed.append(entry.name)
        result.removed_count += 1
        result.removed_bytes += stat.st_size

    return result


def cleanup_cached_audio(media_dir):
    """Delete verified cached-audio files in one media directory.

    Only a ``<stem>.mp3`` whose stem names a video source (``.mp4``/``.webm``)
    in the media directory is treated as a reproducible cached audio artifact.
    Refuses while an analysis worker is active because the worker may be
    creating or reusing the cache.
    """
    chordflask = _storage_directory(media_dir)
    result = CleanupResult()
    if chordflask is None:
        return result

    if worker_is_active():
        result.refused = True
        result.reason = (
            "an analysis worker is active; cached audio may be in use or "
            "being regenerated"
        )
        return result

    media = chordflask.parent

    try:
        entries = sorted(chordflask.iterdir(), key=lambda e: e.name)
    except OSError as error:
        result.failures.append(f"cannot list {chordflask}: {error}")
        return result

    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            continue
        if entry.suffix.lower() != ".mp3":
            continue
        if not _video_source_exists(media, entry.stem):
            continue

        try:
            size = entry.stat().st_size
            entry.unlink()
        except OSError as error:
            result.failures.append(f"could not remove {entry.name}: {error}")
            continue

        result.removed.append(entry.name)
        result.removed_count += 1
        result.removed_bytes += size

    return result


def format_cleanup_result(result: CleanupResult, scope: str) -> str:
    """Render one cleanup result."""
    lines = [str(scope)]
    if result.refused:
        lines.append(f"  REFUSED: {result.reason}")
        lines.append("  (nothing deleted)")
        return "\n".join(lines)

    for name in result.removed:
        lines.append(f"  removed  {name}")
    for failure in result.failures:
        lines.append(f"  ERROR    {failure}")

    if result.removed_count:
        lines.append(
            f"  removed {result.removed_count} item(s), "
            f"reclaimed {_format_bytes(result.removed_bytes)}"
        )
    else:
        lines.append("  nothing to remove")
    return "\n".join(lines)
