"""Deterministic Demucs storage, status classification, and publication."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from chordflask_base import ChordData, ChordTrackRepository, analysis_json_path

from .audio import AudioCommandError, AudioFacts, AudioValidationError, hash_file, probe_audio
from .constants import (
    AUDIO_SET_ID,
    CURRENT,
    DEMUCS_MODEL,
    DEMUCS_STEM_NAMES,
    ERROR,
    STALE,
    TODO,
)
from .runtime import RuntimeInfo
from .validation import build_audio_track_set, pipeline_fingerprint


class DemucsStorageError(RuntimeError):
    """A Demucs result cannot be safely classified or published."""


class DemucsBusyError(DemucsStorageError):
    """Another process is currently handling this media file."""


@dataclass(frozen=True)
class DemucsStatus:
    label: str
    reason: str = ""


def analysis_path(media_path: Path) -> Path:
    return analysis_json_path(media_path)


def safe_media_key(media_path: Path) -> str:
    readable = re.sub(r"[^A-Za-z0-9._-]+", "_", media_path.stem).strip("._")
    readable = readable or "media"
    name_hash = hashlib.sha256(media_path.name.encode("utf-8")).hexdigest()[:12]
    return f"{readable}-{name_hash}"


def stems_root(media_path: Path) -> Path:
    return media_path.parent / ".chordflask" / "stems" / "demucs" / DEMUCS_MODEL / safe_media_key(media_path)


def generation_id(
    source_hash: str,
    pipeline: str,
    stem_hashes: dict[str, str],
) -> str:
    payload = {
        "source_sha256": source_hash,
        "pipeline_fingerprint": pipeline,
        "stems": {stem: stem_hashes[stem] for stem in DEMUCS_STEM_NAMES},
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialized).hexdigest()[:24]


def _resolve_stem_path(media_path: Path, relative_path: str) -> Path:
    candidate = media_path.parent / Path(relative_path)
    if candidate.is_symlink():
        raise DemucsStorageError(f"Audio stem is a symlink: {candidate}")
    resolved = candidate.resolve()
    root = stems_root(media_path).resolve()
    if not resolved.is_relative_to(root):
        raise DemucsStorageError(f"Audio stem escapes the Demucs storage root: {candidate}")
    return resolved


def _load_analysis(media_path: Path) -> ChordData:
    path = analysis_path(media_path)
    if not path.is_file():
        return ChordData()
    return ChordTrackRepository().load(path)


def _facts_match(actual: AudioFacts, expected: dict) -> bool:
    if actual.format != "flac" or actual.codec != "flac":
        return False
    if actual.sample_rate != expected["sample_rate"]:
        return False
    if actual.channels != expected["channels"]:
        return False
    if actual.sample_count != expected["sample_count"]:
        return False
    if actual.start_time is not None and abs(actual.start_time) > 1 / actual.sample_rate:
        return False
    return abs(actual.duration - expected["duration"]) <= 2 / actual.sample_rate


def _set_current(
    media_path: Path,
    set_data: dict,
    *,
    runtime: RuntimeInfo | None,
    device: str,
) -> tuple[bool, str]:
    if set_data.get("provider") != "demucs" or set_data.get("model") != DEMUCS_MODEL:
        return False, "the audio set belongs to another provider or model"

    metadata = set_data["metadata"]
    source = metadata["source"]
    try:
        actual_source_hash = hash_file(media_path)
        source_size = media_path.stat().st_size
    except OSError as error:
        return False, f"source cannot be read: {error}"
    if source["sha256"] != actual_source_hash or source["size"] != source_size:
        return False, "source media has changed"

    if runtime is not None:
        if metadata.get("device") != device:
            return False, "processing device differs"
        expected_pipeline = pipeline_fingerprint(runtime, device=device)
        if metadata.get("pipeline_fingerprint") != expected_pipeline:
            return False, "Demucs runtime or processing configuration differs"

    for stem_name in DEMUCS_STEM_NAMES:
        stem = set_data["tracks"][stem_name]
        try:
            path = _resolve_stem_path(media_path, stem["path"])
            if not path.is_file():
                return False, f"{stem_name} stem is missing"
            if path.stat().st_size != stem["size"]:
                return False, f"{stem_name} stem size changed"
            if hash_file(path) != stem["sha256"]:
                return False, f"{stem_name} stem hash changed"
            if not _facts_match(probe_audio(path), stem):
                return False, f"{stem_name} stem metadata changed"
        except (AudioCommandError, AudioValidationError, OSError, ValueError, DemucsStorageError) as error:
            return False, f"{stem_name} stem is invalid: {error}"
    return True, "all four stems and source metadata match"


def classify(
    media_path: Path,
    *,
    runtime: RuntimeInfo | None = None,
    device: str = "auto",
) -> DemucsStatus:
    """Classify one media file without modifying its analysis or stems."""
    json_path = analysis_path(media_path)
    if not json_path.is_file():
        return DemucsStatus(TODO, "no analysis JSON exists")
    try:
        data = ChordTrackRepository().load(json_path)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as error:
        return DemucsStatus(ERROR, f"analysis JSON is invalid: {error}")
    if not data.has_audio_track(AUDIO_SET_ID):
        return DemucsStatus(TODO, "the Demucs stem set is not registered")
    try:
        current, reason = _set_current(
            media_path,
            data.audio_track_data(AUDIO_SET_ID),
            runtime=runtime,
            device=device,
        )
    except (KeyError, TypeError, ValueError) as error:
        return DemucsStatus(ERROR, f"Demucs stem set is malformed: {error}")
    return DemucsStatus(CURRENT if current else STALE, reason)


@contextmanager
def media_lock(media_path: Path):
    analysis_dir = media_path.parent / ".chordflask"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    lock_path = analysis_dir / f".{safe_media_key(media_path)}.demucs.lock"
    with lock_path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise DemucsBusyError(f"Demucs processing is already running for {media_path}") from error
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _verify_existing_generation(
    generation_dir: Path,
    stem_hashes: dict[str, str],
    stem_facts: dict[str, AudioFacts],
    stem_sizes: dict[str, int],
) -> None:
    for stem_name in DEMUCS_STEM_NAMES:
        path = generation_dir / f"{stem_name}.flac"
        if path.is_symlink() or not path.is_file():
            raise DemucsStorageError(f"Existing generation is incomplete: {path}")
        if path.stat().st_size != stem_sizes[stem_name]:
            raise DemucsStorageError(f"Existing generation has changed size: {path}")
        if hash_file(path) != stem_hashes[stem_name]:
            raise DemucsStorageError(f"Existing generation has changed content: {path}")
        if not _facts_match(
            probe_audio(path),
            {
                "format": "flac",
                "sample_rate": stem_facts[stem_name].sample_rate,
                "channels": stem_facts[stem_name].channels,
                "sample_count": stem_facts[stem_name].sample_count,
                "duration": stem_facts[stem_name].duration,
            },
        ):
            raise DemucsStorageError(f"Existing generation has invalid metadata: {path}")


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def publish_set(
    media_path: Path,
    *,
    staged_dir: Path,
    source: AudioFacts,
    source_hash: str,
    source_size: int,
    source_timeline: dict,
    runtime: RuntimeInfo,
    device: str,
    stem_facts: dict[str, AudioFacts],
    tail_adjustments: dict[str, int],
) -> Path:
    """Publish a complete generation and then atomically publish its JSON."""
    stem_hashes = {stem_name: hash_file(staged_dir / f"{stem_name}.flac") for stem_name in DEMUCS_STEM_NAMES}
    stem_sizes = {
        stem_name: (staged_dir / f"{stem_name}.flac").stat().st_size for stem_name in DEMUCS_STEM_NAMES
    }
    pipeline = pipeline_fingerprint(runtime, device=device)
    final_dir = stems_root(media_path) / generation_id(source_hash, pipeline, stem_hashes)
    final_dir.parent.mkdir(parents=True, exist_ok=True)

    if final_dir.exists():
        _verify_existing_generation(final_dir, stem_hashes, stem_facts, stem_sizes)
        shutil.rmtree(staged_dir)
    else:
        os.replace(staged_dir, final_dir)
        _fsync_directory(final_dir)
        _fsync_directory(final_dir.parent)

    final_paths = {stem_name: final_dir / f"{stem_name}.flac" for stem_name in DEMUCS_STEM_NAMES}
    set_data = build_audio_track_set(
        source=source,
        source_hash=source_hash,
        source_size=source_size,
        source_timeline=source_timeline,
        runtime=runtime,
        device=device,
        stem_paths=final_paths,
        stem_facts=stem_facts,
        stem_hashes=stem_hashes,
        stem_sizes=stem_sizes,
        tail_adjustments=tail_adjustments,
        relative_to=media_path.parent,
    )

    json_path = analysis_path(media_path)
    analysis_dir = json_path.parent
    analysis_dir.mkdir(parents=True, exist_ok=True)
    data = _load_analysis(media_path)
    data.set_audio_track(AUDIO_SET_ID, set_data)

    descriptor, staged_json_name = tempfile.mkstemp(
        prefix=f".{json_path.name}.", suffix=".tmp", dir=analysis_dir
    )
    os.close(descriptor)
    staged_json = Path(staged_json_name)
    try:
        ChordTrackRepository().save(data, staged_json)
        os.replace(staged_json, json_path)
        _fsync_directory(analysis_dir)
    finally:
        try:
            staged_json.unlink()
        except FileNotFoundError:
            pass
    return json_path


__all__ = [
    "CURRENT",
    "DemucsBusyError",
    "DemucsStatus",
    "DemucsStorageError",
    "ERROR",
    "STALE",
    "TODO",
    "analysis_path",
    "classify",
    "generation_id",
    "media_lock",
    "publish_set",
    "safe_media_key",
    "stems_root",
]
