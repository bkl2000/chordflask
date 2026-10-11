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
import hashlib
import os
import re
import shutil
import stat
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from chordflask_base import (
    ANALYSIS_DIR_NAME,
    DEMUCS_STEM_NAMES,
    ChordTrackRepository,
    analysis_json_path,
)

from chordflask_maintain.migrate import (
    MigrationFileError,
    classify_analysis,
    read_analysis_json,
)
from chordflask_maintain.storage import LockStatus, check_lock_file, worker_lock_status

# Consumer-side identifier matching the producer's set id. It is defined here
# so this framework-free package never imports the optional producer package.
DEMUCS_AUDIO_SET_ID = "demucs:htdemucs"

_STEMS_REL = Path("stems") / "demucs" / "htdemucs"
_MEDIA_SUFFIXES = frozenset({".mp3", ".mp4", ".webm"})


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
    refusal_kind: str = ""
    reason: str = ""
    failures: list = field(default_factory=list)


@dataclass
class StemRemoval:
    """Removal outcome for one explicitly identified media file."""

    media: Path
    registration_removed: bool = False
    files: list = field(default_factory=list)
    generations: list = field(default_factory=list)
    key_directory_removed: bool = False
    refused: bool = False
    refusal_kind: str = ""
    reason: str = ""
    failures: list = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return (
            self.registration_removed
            or self.key_directory_removed
            or bool(self.files or self.generations)
        )


@dataclass
class StemsRemovalResult:
    """Outcome of an explicit single-song or directory-wide removal."""

    removals: list = field(default_factory=list)

    @property
    def refused(self) -> bool:
        return any(item.refused for item in self.removals)

    @property
    def failures(self) -> list:
        return [failure for item in self.removals for failure in item.failures]


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


def _iter_json_files(chordflask: Path, *, fail_closed: bool = False):
    try:
        entries = list(chordflask.iterdir())
    except OSError:
        if fail_closed:
            raise
        return []
    json_files = []
    for path in entries:
        if path.suffix != ".json":
            continue
        try:
            if stat.S_ISREG(path.lstat().st_mode):
                json_files.append(path)
        except OSError:
            if fail_closed:
                raise
    return sorted(json_files)


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


def demucs_lock_status(chordflask: Path) -> LockStatus:
    """Return the aggregate Demucs lock state, failing closed on errors."""
    try:
        lock_files = sorted(
            path for path in chordflask.iterdir() if path.name.endswith(".demucs.lock")
        )
    except OSError as error:
        return LockStatus("error", f"cannot list Demucs locks in {chordflask}: {error}")
    for lock_path in lock_files:
        status = check_lock_file(lock_path, "Demucs lock")
        if status.state != "inactive":
            return status
    return LockStatus("inactive")


def demucs_lock_is_active(chordflask: Path) -> bool:
    """Compatibility helper returning whether a Demucs lock is held."""
    return demucs_lock_status(chordflask).state == "active"


def _media_key(media: Path) -> str:
    """Return the producer's deterministic storage key without importing it."""
    readable = re.sub(r"[^A-Za-z0-9._-]+", "_", media.stem).strip("._")
    readable = readable or "media"
    name_hash = hashlib.sha256(media.name.encode("utf-8")).hexdigest()[:12]
    return f"{readable}-{name_hash}"


def _demucs_lock_path(media: Path) -> Path:
    return media.parent / ANALYSIS_DIR_NAME / f".{_media_key(media)}.demucs.lock"


@contextmanager
def _exclusive_lock(
    lock_path: Path, description: str, *, create: bool, blocking: bool = False
):
    """Acquire one regular lock file without following symlinks."""
    flags = os.O_RDWR | (os.O_CREAT if create else 0)
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o666)
    except FileNotFoundError:
        yield LockStatus("inactive")
        return
    except OSError as error:
        yield LockStatus("error", f"cannot open {description} {lock_path}: {error}")
        return
    handle = os.fdopen(descriptor, "a+")
    try:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            yield LockStatus(
                "error", f"cannot inspect {description} {lock_path}: not a regular file"
            )
            return
        try:
            operation = fcntl.LOCK_EX
            if not blocking:
                operation |= fcntl.LOCK_NB
            fcntl.flock(handle.fileno(), operation)
        except BlockingIOError:
            yield LockStatus("active")
            return
        except OSError as error:
            yield LockStatus(
                "error", f"cannot inspect {description} {lock_path}: {error}"
            )
            return
        try:
            yield LockStatus("inactive")
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _demucs_media_lock(media: Path, *, dry_run: bool):
    """Acquire the producer's per-media lock, without creating it for previews."""
    return _exclusive_lock(
        _demucs_lock_path(media), "Demucs lock", create=not dry_run
    )


def _removal_analysis_lock(json_path: Path, *, dry_run: bool):
    """Use the normal writer lock, or inspect an existing lock for a dry run."""
    resolved = json_path.resolve()
    lock_path = resolved.parent / f".{resolved.stem}.analysis.lock"
    return _exclusive_lock(
        lock_path,
        "analysis JSON lock",
        create=not dry_run,
        blocking=not dry_run,
    )


def _registered_generation(media_dir: Path, set_data: dict) -> tuple[Path, Path]:
    """Validate and return the registered key and generation directories."""
    if set_data.get("provider") != "demucs" or set_data.get("model") != "htdemucs":
        raise ValueError("registered stem set has an unexpected provider or model")

    generation_parts = None
    tracks = set_data.get("tracks")
    if not isinstance(tracks, dict):
        raise ValueError("registered stem set has no valid tracks object")
    for stem in DEMUCS_STEM_NAMES:
        entry = tracks.get(stem)
        relative = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(relative, str):
            raise ValueError(f"registered {stem} stem has no path")
        parts = Path(relative).parts
        expected_prefix = (ANALYSIS_DIR_NAME, "stems", "demucs", "htdemucs")
        if (
            len(parts) != 7
            or parts[:4] != expected_prefix
            or parts[4] in {".", ".."}
            or parts[5] in {".", ".."}
            or parts[6] != f"{stem}.flac"
        ):
            raise ValueError(
                f"registered {stem} stem is outside the Demucs storage layout"
            )
        current = parts[:6]
        if generation_parts is None:
            generation_parts = current
        elif current != generation_parts:
            raise ValueError("registered stems do not belong to one generation")

    generation = media_dir.joinpath(*generation_parts)
    return generation.parent, generation


def _analysis_media_keys(media: Path) -> set[str]:
    """Return exact media keys that can legitimately share this analysis JSON."""
    keys = set()
    try:
        entries = list(media.parent.iterdir())
    except OSError as error:
        raise ValueError(f"cannot inspect media directory {media.parent}: {error}") from error
    for entry in entries:
        try:
            if (
                not entry.is_symlink()
                and entry.is_file()
                and entry.stem == media.stem
                and entry.suffix.lower() in _MEDIA_SUFFIXES
            ):
                keys.add(_media_key(entry))
        except OSError as error:
            raise ValueError(f"cannot inspect possible media owner {entry}: {error}") from error
    return keys


def _owned_tree(media: Path) -> tuple[list[Path], list[Path]]:
    """Return regular files and generation dirs in this song's verified key dir."""
    root = stems_root(media.parent)
    current = media.parent / ANALYSIS_DIR_NAME
    for part in _STEMS_REL.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            return [], []
        except OSError as error:
            raise ValueError(f"cannot inspect stem storage path {current}: {error}") from error
        if stat.S_ISLNK(mode):
            raise ValueError(f"stem storage path is a symlink: {current}")
        if not stat.S_ISDIR(mode):
            raise ValueError(f"stem storage path is not a directory: {current}")

    key_dir = root / _media_key(media)
    try:
        key_mode = key_dir.lstat().st_mode
    except FileNotFoundError:
        return [], []
    except OSError as error:
        raise ValueError(f"cannot inspect song stem storage {key_dir}: {error}") from error
    if stat.S_ISLNK(key_mode):
        raise ValueError(f"song stem storage is a symlink: {key_dir}")
    if not stat.S_ISDIR(key_mode):
        raise ValueError(f"song stem storage is not a directory: {key_dir}")

    files = []
    generations = []
    try:
        entries = sorted(key_dir.iterdir(), key=lambda path: path.name)
    except OSError as error:
        raise ValueError(f"cannot inspect song stem storage {key_dir}: {error}") from error
    for generation in entries:
        try:
            mode = generation.lstat().st_mode
        except OSError as error:
            raise ValueError(f"cannot inspect stem generation {generation}: {error}") from error
        if not stat.S_ISDIR(mode):
            raise ValueError(f"unexpected entry in song stem storage: {generation}")
        generations.append(generation)
        try:
            generation_entries = sorted(
                generation.iterdir(), key=lambda path: path.name
            )
        except OSError as error:
            raise ValueError(f"cannot inspect stem generation {generation}: {error}") from error
        expected_names = {f"{stem}.flac" for stem in DEMUCS_STEM_NAMES}
        for entry in generation_entries:
            try:
                entry_mode = entry.lstat().st_mode
            except OSError as error:
                raise ValueError(f"cannot inspect stem file {entry}: {error}") from error
            if not stat.S_ISREG(entry_mode) or entry.name not in expected_names:
                raise ValueError(f"unexpected entry in stem generation: {entry}")
            files.append(entry)
    return files, generations


def _validate_other_references(media: Path, key_dir: Path, target_json: Path) -> None:
    chordflask = media.parent / ANALYSIS_DIR_NAME
    try:
        json_files = _iter_json_files(chordflask, fail_closed=True)
    except OSError as error:
        raise ValueError(f"cannot inspect analysis JSON files: {error}") from error
    for json_path in json_files:
        if json_path == target_json:
            continue
        try:
            data = read_analysis_json(json_path)
            kind = classify_analysis(data)
            if kind is None:
                continue
            track = ChordTrackRepository().load(json_path)
        except Exception as error:  # noqa: BLE001 - fail-closed ownership boundary
            raise ValueError(f"cannot safely inspect {json_path.name}: {error}") from error
        if not track.has_audio_track(DEMUCS_AUDIO_SET_ID):
            continue
        registered_key, _ = _registered_generation(
            media.parent, track.audio_track_data(DEMUCS_AUDIO_SET_ID)
        )
        if registered_key == key_dir:
            raise ValueError(
                f"{json_path.name} also references this song's stem storage"
            )


def _remove_owned_files(
    result: StemRemoval, files: list[Path], generations: list[Path], *, dry_run: bool
) -> None:
    if dry_run:
        result.files.extend(str(path) for path in files)
        result.generations.extend(str(path) for path in generations)
        key_dir = stems_root(result.media.parent) / _media_key(result.media)
        result.key_directory_removed = key_dir.is_dir()
        return

    for path in files:
        try:
            if not stat.S_ISREG(path.lstat().st_mode):
                raise OSError("path is no longer a regular file")
            path.unlink()
        except OSError as error:
            result.failures.append(f"could not remove stem file {path}: {error}")
            continue
        result.files.append(str(path))

    for path in reversed(generations):
        try:
            if not stat.S_ISDIR(path.lstat().st_mode):
                raise OSError("path is no longer a directory")
            path.rmdir()
        except OSError as error:
            result.failures.append(f"could not remove stem generation {path}: {error}")
            continue
        result.generations.append(str(path))

    key_dir = stems_root(result.media.parent) / _media_key(result.media)
    try:
        key_dir.rmdir()
    except FileNotFoundError:
        pass
    except OSError as error:
        result.failures.append(
            f"could not remove song stem directory {key_dir}: {error}"
        )
    else:
        result.key_directory_removed = True


def _remove_one(media: Path, *, dry_run: bool) -> StemRemoval:
    result = StemRemoval(media=media)
    chordflask = _analysis_dir(media.parent)
    if chordflask is None:
        return result

    with _demucs_media_lock(media, dry_run=dry_run) as lock_status:
        if lock_status.state != "inactive":
            result.refused = True
            result.refusal_kind = (
                "demucs_active"
                if lock_status.state == "active"
                else "demucs_lock_error"
            )
            result.reason = (
                "Demucs processing is active for this song; stems were not changed"
                if lock_status.state == "active"
                else f"{lock_status.reason}; stem removal cannot safely continue"
            )
            return result

        json_path = analysis_json_path(media)
        if json_path.is_symlink():
            result.refused = True
            result.refusal_kind = "analysis_json_error"
            result.reason = f"analysis JSON is a symlink: {json_path}"
            return result
        with _removal_analysis_lock(json_path, dry_run=dry_run) as analysis_status:
            if analysis_status.state != "inactive":
                result.refused = True
                result.refusal_kind = (
                    "analysis_active"
                    if analysis_status.state == "active"
                    else "analysis_lock_error"
                )
                result.reason = (
                    "the analysis JSON is being updated; stems were not changed"
                    if analysis_status.state == "active"
                    else f"{analysis_status.reason}; stem removal cannot safely continue"
                )
                return result
            track = None
            set_data = None
            registration_owned = False
            if json_path.exists():
                try:
                    track = ChordTrackRepository().load(json_path)
                except Exception as error:  # noqa: BLE001 - validation boundary
                    result.refused = True
                    result.refusal_kind = "analysis_json_error"
                    result.reason = f"invalid analysis JSON {json_path.name}: {error}"
                    return result
                if track.has_audio_track(DEMUCS_AUDIO_SET_ID):
                    set_data = track.audio_track_data(DEMUCS_AUDIO_SET_ID)

            try:
                files, generations = _owned_tree(media)
                key_dir = stems_root(media.parent) / _media_key(media)
                if set_data is not None:
                    registered_key, _ = _registered_generation(media.parent, set_data)
                    if registered_key.name not in _analysis_media_keys(media):
                        raise ValueError(
                            "registered stems do not belong to an existing media file "
                            "for this analysis"
                        )
                    registration_owned = registered_key == key_dir
                key_dir_present = key_dir.is_dir()
                if (
                    not registration_owned
                    and not files
                    and not generations
                    and not key_dir_present
                ):
                    return result
                _validate_other_references(media, key_dir, json_path)
            except ValueError as error:
                result.refused = True
                result.refusal_kind = "generation_unresolved"
                result.reason = f"cannot establish safe stem ownership: {error}"
                return result

            if registration_owned:
                if dry_run:
                    result.registration_removed = True
                else:
                    try:
                        track.remove_audio_track(DEMUCS_AUDIO_SET_ID)
                        ChordTrackRepository().save(track, json_path)
                    except Exception as error:  # noqa: BLE001 - atomic persistence boundary
                        result.failures.append(
                            f"could not remove stem registration from {json_path}: {error}"
                        )
                        return result
                    result.registration_removed = True

            _remove_owned_files(
                result, files, generations, dry_run=dry_run
            )
    return result


def remove_stems(target, *, all_directory: bool = False, dry_run: bool = False):
    """Remove one song's owned stems, or all safely identifiable songs in a directory."""
    path = Path(target).expanduser()
    if all_directory:
        if path.is_symlink() or not path.is_dir():
            raise ValueError(f"media directory does not exist or is unsafe: {path}")
        try:
            media_files = sorted(
                entry
                for entry in path.iterdir()
                if not entry.is_symlink()
                and entry.is_file()
                and entry.suffix.lower() in _MEDIA_SUFFIXES
            )
        except OSError as error:
            raise ValueError(f"cannot inspect media directory {path}: {error}") from error
    else:
        if (
            path.is_symlink()
            or not path.is_file()
            or path.suffix.lower() not in _MEDIA_SUFFIXES
        ):
            raise ValueError(f"not a safe MP3, MP4, or WebM media file: {path}")
        media_files = [path]

    return StemsRemovalResult(
        removals=[_remove_one(media, dry_run=dry_run) for media in media_files]
    )


def format_stems_removal(result: StemsRemovalResult, *, dry_run: bool = False) -> str:
    """Render explicit stem-removal actions, preservation, and summary."""
    action = "would remove" if dry_run else "removed"
    lines = []
    if not result.removals:
        lines.append("UNCHANGED: no supported media files found")
    for item in result.removals:
        lines.append(str(item.media))
        if item.refused:
            lines.append(f"  REFUSED: {item.reason}")
            continue
        if item.registration_removed:
            lines.append(f"  {action}  Demucs stem registration")
        for path in item.files:
            lines.append(f"  {action}  {path}")
        for path in item.generations:
            lines.append(f"  {action}  generation {path}")
        if item.key_directory_removed:
            lines.append(f"  {action}  song stem directory")
        for failure in item.failures:
            lines.append(f"  ERROR: {failure}")
        if not item.changed and not item.failures:
            lines.append("  UNCHANGED: no registered or stored Demucs stems")

    changed = sum(item.changed for item in result.removals)
    registrations = sum(item.registration_removed for item in result.removals)
    files = sum(len(item.files) for item in result.removals)
    generations = sum(len(item.generations) for item in result.removals)
    refused = sum(item.refused for item in result.removals)
    failures = len(result.failures)
    change_label = "would change" if dry_run else "changed"
    lines.append(
        f"SUMMARY: songs {changed} {change_label}, registrations {registrations}, "
        f"files {files}, generations {generations}, refused {refused}, failures {failures}"
    )
    lines.append(
        "PRESERVED: original media, chord analyses, Edited chords, BTC tracks, "
        "lyrics, journals, and unrelated data"
    )
    return "\n".join(lines)


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

    worker_status = worker_lock_status()
    if worker_status.state != "inactive":
        result.refused = True
        result.refusal_kind = (
            "worker_active" if worker_status.state == "active" else "worker_lock_error"
        )
        result.reason = (
            "an analysis worker is active; stem storage was not changed"
            if worker_status.state == "active"
            else f"{worker_status.reason}; cleanup cannot safely continue"
        )
        return result

    chordflask = _analysis_dir(media)
    if chordflask is None:
        return result

    demucs_status = demucs_lock_status(chordflask)
    if demucs_status.state != "inactive":
        result.refused = True
        result.refusal_kind = (
            "demucs_active" if demucs_status.state == "active" else "demucs_lock_error"
        )
        result.reason = (
            "a Demucs process holds a lock; stem storage was not changed"
            if demucs_status.state == "active"
            else f"{demucs_status.reason}; cleanup cannot safely continue"
        )
        return result

    referenced: set = set()
    try:
        json_files = _iter_json_files(chordflask, fail_closed=True)
    except OSError as error:
        result.refused = True
        result.refusal_kind = "analysis_json_error"
        result.reason = (
            f"cannot inspect analysis JSON files: {error}; "
            "orphan references cannot be determined safely"
        )
        return result

    for json_path in json_files:
        try:
            data = read_analysis_json(json_path)
        except MigrationFileError as error:
            result.refused = True
            result.refusal_kind = "analysis_json_error"
            result.reason = (
                f"cannot read {json_path.name}: {error}; "
                "orphan references cannot be determined safely"
            )
            return result
        try:
            kind = classify_analysis(data)
        except MigrationFileError as error:
            result.refused = True
            result.refusal_kind = "analysis_json_error"
            result.reason = (
                f"cannot classify {json_path.name}: {error}; "
                "orphan references cannot be determined safely"
            )
            return result
        if kind is None:
            continue  # non-analysis JSON (e.g. *.training.json)
        try:
            track = ChordTrackRepository().load(str(json_path))
        except Exception as error:  # noqa: BLE001 - validation boundary
            result.refused = True
            result.refusal_kind = "analysis_json_error"
            result.reason = (
                f"invalid analysis JSON {json_path.name}: {error}; "
                "orphan references cannot be determined safely"
            )
            return result
        if track.has_audio_track(DEMUCS_AUDIO_SET_ID):
            generation = _referenced_generation(
                media, track.audio_track_data(DEMUCS_AUDIO_SET_ID)
            )
            if generation is None:
                result.refused = True
                result.refusal_kind = "generation_unresolved"
                result.reason = (
                    f"cannot resolve registered stem generation for {json_path.name}; "
                    "orphan status cannot be proven safely"
                )
                return result
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
    "StemsRemovalResult",
    "StemsReport",
    "cleanup_orphan_stems",
    "demucs_lock_is_active",
    "demucs_lock_status",
    "format_stems_cleanup",
    "format_stems_removal",
    "format_stems_report",
    "inspect_stems",
    "remove_stems",
    "stems_root",
]
