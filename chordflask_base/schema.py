"""Schema-v3 analysis contract (neutral, framework-free).

Part of :mod:`chordflask_base` — the base layer shared by the app (``chordflask/``)
and by external chord-track producers. This module is pure stdlib: no Flask, no
audio, no torch.

It is the single source of truth for the Schema-v3 contract: the track-ID
constants, the chord/rhythm-entry validation, the atomic write, and the
analysis-JSON path. Keeping it here (instead of inside the app or a producer)
means both sides import one contract instead of two drifted copies.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import tempfile
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

SCHEMA_VERSION = 3
SUPPORTED_SCHEMA_VERSIONS = {1, 2, 3}

ANALYSIS_DIR_NAME = ".chordflask"
ANALYSIS_SAMPLE_RATE = 44100

DEFAULT_CHORD_TRACK = "chordino"
DEFAULT_RHYTHM_TRACK = "qm_barbeattracker"
MADMOM_TRACK_ID = "madmom"
USER_EDITED_TRACK_ID = "user_edited"
USER_EDITED_RHYTHM_TRACK_ID = "user_edited_rhythm"
PYTORCH_TRACK_ID = "pytorch"
PYTORCH_V2_TRACK_ID = "pytorch_v2"
REFERENCE_TRACK_ID = "reference"
BTC_TRACK_ID = "btc"
AUDIO_TRACKS_KEY = "audio_tracks"
DEMUCS_STEM_NAMES = ("bass", "drums", "other", "vocals")


class SchemaV3Error(ValueError):
    """The analysis file does not satisfy the required storage boundary."""


def analysis_json_path(media_path: Path) -> Path:
    return media_path.parent / ANALYSIS_DIR_NAME / f"{media_path.stem}.json"


def chord_input_sha256(chords: list[dict[str, Any]]) -> str:
    """Identify chord input with the historical V3 sorted-key JSON encoding."""
    return hashlib.sha256(json.dumps(chords, sort_keys=True).encode()).hexdigest()


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def validate_chord_entries(chords: Any, file_path: Path | str, context: str) -> None:
    """Validate one chord track's ``chords`` list (timestamps + labels)."""
    if not isinstance(chords, list):
        raise SchemaV3Error(
            f"Invalid chord data in {file_path}: {context} must be a list"
        )
    prev = None
    for i, entry in enumerate(chords):
        if not isinstance(entry, dict):
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: {context}[{i}] must be an object"
            )
        ts = entry.get("timestamp")
        ch = entry.get("chord")
        if not _is_finite_number(ts) or ts < 0:
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: "
                f"{context}[{i}] has invalid or negative timestamp {ts!r}"
            )
        if not isinstance(ch, str) or not ch.strip():
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: "
                f"{context}[{i}] has empty or missing chord {ch!r}"
            )
        if prev is not None and ts < prev:
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: "
                f"{context}[{i}] timestamp {ts} is before previous {prev}"
            )
        prev = ts


def validate_rhythm_entry(entry: Any, file_path: Path | str, context: str) -> None:
    """Validate one rhythm track entry (bpm, meter, beats, beat numbers)."""
    if not isinstance(entry, dict):
        raise SchemaV3Error(
            f"Invalid chord data in {file_path}: {context} must be an object"
        )
    for required in ("bpm", "meter_signature", "beat_times", "beat_numbers"):
        if required not in entry:
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: {context} must contain \"{required}\""
            )

    bpm = entry["bpm"]
    if bpm is not None and (not _is_finite_number(bpm) or bpm <= 0):
        raise SchemaV3Error(
            f"Invalid chord data in {file_path}: {context} bpm must be positive, got {bpm!r}"
        )

    meter = entry["meter_signature"]
    if meter is not None and (not isinstance(meter, int) or isinstance(meter, bool) or meter <= 0):
        raise SchemaV3Error(
            f"Invalid chord data in {file_path}: "
            f"{context} meter_signature must be a positive integer, got {meter!r}"
        )

    beat_times = entry["beat_times"]
    if not isinstance(beat_times, list):
        raise SchemaV3Error(
            f"Invalid chord data in {file_path}: {context} beat_times must be a list"
        )
    prev_bt = None
    for i, bt in enumerate(beat_times):
        if not _is_finite_number(bt) or bt < 0:
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: "
                f"{context} beat_times[{i}] is negative or not a finite number: {bt!r}"
            )
        if prev_bt is not None and bt < prev_bt:
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: "
                f"{context} beat_times[{i}] {bt} is before previous {prev_bt}"
            )
        prev_bt = bt

    beat_numbers = entry["beat_numbers"]
    if not isinstance(beat_numbers, list):
        raise SchemaV3Error(
            f"Invalid chord data in {file_path}: {context} beat_numbers must be a list"
        )
    if beat_numbers and len(beat_numbers) != len(beat_times):
        raise SchemaV3Error(
            f"Invalid chord data in {file_path}: {context} beat_numbers length "
            f"{len(beat_numbers)} does not match beat_times length {len(beat_times)}"
        )
    for i, bn in enumerate(beat_numbers):
        if not isinstance(bn, int) or isinstance(bn, bool) or bn <= 0:
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: {context} beat_numbers[{i}] must be "
                f"a positive integer, got {bn!r}"
            )
        if meter is not None and bn > meter:
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: {context} beat_numbers[{i}] "
                f"{bn} exceeds meter_signature {meter}"
            )

    metadata = entry.get("metadata", {})
    if not isinstance(metadata, dict):
        raise SchemaV3Error(
            f"Invalid chord data in {file_path}: {context} metadata must be an object"
        )


def _validate_non_empty_string(value: Any, file_path: Path | str, context: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SchemaV3Error(
            f"Invalid audio track set in {file_path}: {context} must be a non-empty string"
        )


def _validate_positive_integer(value: Any, file_path: Path | str, context: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise SchemaV3Error(
            f"Invalid audio track set in {file_path}: {context} must be a positive integer"
        )


def _validate_non_negative_integer(value: Any, file_path: Path | str, context: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SchemaV3Error(
            f"Invalid audio track set in {file_path}: {context} must be a non-negative integer"
        )


def _validate_sha256(value: Any, file_path: Path | str, context: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SchemaV3Error(
            f"Invalid audio track set in {file_path}: {context} must be a SHA-256 hex string"
        )


def _validate_audio_path(value: Any, file_path: Path | str, context: str) -> None:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise SchemaV3Error(
            f"Invalid audio track set in {file_path}: {context} must be a safe relative path"
        )
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise SchemaV3Error(
            f"Invalid audio track set in {file_path}: {context} must be a safe relative path"
        )


def _validate_audio_source(source: Any, file_path: Path | str, context: str) -> None:
    if not isinstance(source, dict):
        raise SchemaV3Error(
            f"Invalid audio track set in {file_path}: {context} must be an object"
        )
    _validate_sha256(source.get("sha256"), file_path, f"{context}.sha256")
    _validate_positive_integer(source.get("size"), file_path, f"{context}.size")
    _validate_positive_integer(
        source.get("sample_rate"), file_path, f"{context}.sample_rate"
    )
    _validate_positive_integer(source.get("channels"), file_path, f"{context}.channels")
    _validate_positive_integer(
        source.get("sample_count"), file_path, f"{context}.sample_count"
    )
    duration = source.get("duration")
    if not _is_finite_number(duration) or duration <= 0:
        raise SchemaV3Error(
            f"Invalid audio track set in {file_path}: {context}.duration must be positive"
        )


def validate_audio_track_set(entry: Any, file_path: Path | str, context: str) -> None:
    """Validate one complete, atomically managed Demucs stem set."""
    if not isinstance(entry, dict):
        raise SchemaV3Error(
            f"Invalid audio track set in {file_path}: {context} must be an object"
        )
    for required in ("provider", "model", "tracks", "metadata"):
        if required not in entry:
            raise SchemaV3Error(
                f"Invalid audio track set in {file_path}: {context} must contain "
                f'"{required}"'
            )
    _validate_non_empty_string(entry["provider"], file_path, f"{context}.provider")
    _validate_non_empty_string(entry["model"], file_path, f"{context}.model")

    tracks = entry["tracks"]
    if not isinstance(tracks, dict) or set(tracks) != set(DEMUCS_STEM_NAMES):
        raise SchemaV3Error(
            f"Invalid audio track set in {file_path}: {context}.tracks must contain exactly "
            f"{list(DEMUCS_STEM_NAMES)!r}"
        )
    for stem_name in DEMUCS_STEM_NAMES:
        stem = tracks[stem_name]
        stem_context = f'{context}.tracks["{stem_name}"]'
        if not isinstance(stem, dict):
            raise SchemaV3Error(
                f"Invalid audio track set in {file_path}: {stem_context} must be an object"
            )
        for required in (
            "path",
            "format",
            "sample_rate",
            "channels",
            "sample_count",
            "duration",
            "size",
            "sha256",
        ):
            if required not in stem:
                raise SchemaV3Error(
                    f"Invalid audio track set in {file_path}: {stem_context} must contain "
                    f'"{required}"'
                )
        _validate_audio_path(stem["path"], file_path, f"{stem_context}.path")
        if stem["format"] != "flac":
            raise SchemaV3Error(
                f"Invalid audio track set in {file_path}: {stem_context}.format must be "
                '"flac"'
            )
        _validate_positive_integer(
            stem["sample_rate"], file_path, f"{stem_context}.sample_rate"
        )
        _validate_positive_integer(stem["channels"], file_path, f"{stem_context}.channels")
        _validate_positive_integer(
            stem["sample_count"], file_path, f"{stem_context}.sample_count"
        )
        duration = stem["duration"]
        if not _is_finite_number(duration) or duration <= 0:
            raise SchemaV3Error(
                f"Invalid audio track set in {file_path}: {stem_context}.duration must be positive"
            )
        _validate_positive_integer(stem["size"], file_path, f"{stem_context}.size")
        _validate_sha256(stem["sha256"], file_path, f"{stem_context}.sha256")

    metadata = entry["metadata"]
    if not isinstance(metadata, dict):
        raise SchemaV3Error(
            f"Invalid audio track set in {file_path}: {context}.metadata must be an object"
        )
    _validate_audio_source(metadata.get("source"), file_path, f"{context}.metadata.source")
    sync = metadata.get("sync")
    if not isinstance(sync, dict):
        raise SchemaV3Error(
            f"Invalid audio track set in {file_path}: {context}.metadata.sync must be an object"
        )
    if not isinstance(sync.get("reference"), str) or not sync["reference"].strip():
        raise SchemaV3Error(
            f"Invalid audio track set in {file_path}: {context}.metadata.sync.reference "
            "must be a non-empty string"
        )
    _validate_non_negative_integer(
        sync.get("start_sample"), file_path, f"{context}.metadata.sync.start_sample"
    )
    _validate_positive_integer(
        sync.get("source_sample_count"),
        file_path,
        f"{context}.metadata.sync.source_sample_count",
    )
    _validate_positive_integer(
        sync.get("stem_sample_count"),
        file_path,
        f"{context}.metadata.sync.stem_sample_count",
    )
    _validate_non_negative_integer(
        sync.get("max_tail_delta_samples"),
        file_path,
        f"{context}.metadata.sync.max_tail_delta_samples",
    )
    adjustments = sync.get("tail_adjustment_samples")
    if not isinstance(adjustments, dict) or set(adjustments) != set(DEMUCS_STEM_NAMES):
        raise SchemaV3Error(
            f"Invalid audio track set in {file_path}: "
            f"{context}.metadata.sync.tail_adjustment_samples must contain exactly "
            f"{list(DEMUCS_STEM_NAMES)!r}"
        )
    for stem_name in DEMUCS_STEM_NAMES:
        adjustment = adjustments[stem_name]
        if not isinstance(adjustment, int) or isinstance(adjustment, bool):
            raise SchemaV3Error(
                f"Invalid audio track set in {file_path}: "
                f"{context}.metadata.sync.tail_adjustment_samples[\"{stem_name}\"] "
                "must be an integer"
            )
    source_timeline = metadata.get("source_timeline")
    if not isinstance(source_timeline, dict):
        raise SchemaV3Error(
            f"Invalid audio track set in {file_path}: "
            f"{context}.metadata.source_timeline must be an object"
        )
    if not isinstance(source_timeline.get("available"), bool):
        raise SchemaV3Error(
            f"Invalid audio track set in {file_path}: "
            f"{context}.metadata.source_timeline.available must be a boolean"
        )
    for field in ("start_time", "container_start_time"):
        value = source_timeline.get(field)
        if value is not None and not _is_finite_number(value):
            raise SchemaV3Error(
                f"Invalid audio track set in {file_path}: "
                f"{context}.metadata.source_timeline.{field} must be finite or null"
            )
    for field in ("audio_stream_index", "start_pts"):
        value = source_timeline.get(field)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            raise SchemaV3Error(
                f"Invalid audio track set in {file_path}: "
                f"{context}.metadata.source_timeline.{field} must be an integer or null"
            )
    time_base = source_timeline.get("time_base")
    if time_base is not None and (not isinstance(time_base, str) or not time_base.strip()):
        raise SchemaV3Error(
            f"Invalid audio track set in {file_path}: "
            f"{context}.metadata.source_timeline.time_base must be a string or null"
        )


def write_atomic(json_path: Path | str, data: dict[str, Any]) -> None:
    """Write JSON atomically: fsync content, then ``os.replace``."""
    destination = Path(json_path).resolve()
    destination_dir = destination.parent
    serialized = json.dumps(data, indent=4, allow_nan=False) + "\n"
    descriptor, tmp_path = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination_dir
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, destination)
        tmp_path = ""
        _fsync_directory(destination_dir)
    finally:
        if descriptor != -1:
            os.close(descriptor)
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError as error:
        logging.warning("Could not open %s for directory fsync: %s", directory, error)
        return
    try:
        os.fsync(descriptor)
    except OSError as error:
        logging.warning("Could not fsync directory %s: %s", directory, error)
    finally:
        os.close(descriptor)


class AnalysisMigrationRequired(SchemaV3Error):
    """Valid older storage must be explicitly migrated before producer updates."""


def analysis_schema_status(data, file_path="<analysis>"):
    """Classify the version only; validate_analysis also checks the structure."""
    if not isinstance(data, dict):
        raise SchemaV3Error(f"Invalid chord data in {file_path}: root must be an object")
    version = data.get("schema_version")
    if version is not None and (
        type(version) is not int or version not in SUPPORTED_SCHEMA_VERSIONS
    ):
        raise SchemaV3Error(
            f"Unsupported chord data schema version {version!r} "
            f"(current: {SCHEMA_VERSION}) in {file_path}"
        )
    return "current" if version == SCHEMA_VERSION else "migratable"


def validate_analysis(data, file_path="<analysis>", *, require_current=False):
    """Validate supported storage; return current/migratable, never migrate or write.

    Producers requiring track dictionaries set require_current=True. Canonical
    Chordino/QM completion is a separate predicate, independent of validity.
    """
    if not isinstance(data, dict):
        raise SchemaV3Error(
            f"Invalid chord data in {file_path}: root must be an object"
        )

    status = analysis_schema_status(data, file_path)
    version = data.get("schema_version")

    prefer_flats = data.get("prefer_flats", True)
    if not isinstance(prefer_flats, bool):
        raise SchemaV3Error(
            f"Invalid chord data in {file_path}: prefer_flats must be a boolean"
        )

    transpose = data.get("transpose", 0)
    if not isinstance(transpose, int) or isinstance(transpose, bool):
        raise SchemaV3Error(
            f"Invalid chord data in {file_path}: transpose must be an integer"
        )

    user_data = data.get("user_data", {})
    if not isinstance(user_data, dict):
        raise SchemaV3Error(
            f"Invalid chord data in {file_path}: user_data must be an object"
        )

    if version is not None and version >= 3:
        _validate_v3(data, file_path)
    else:
        _validate_legacy(data, file_path)
    if require_current and status == "migratable":
        raise AnalysisMigrationRequired(
            f"Valid migratable analysis schema {version!r}; migration to Schema v{SCHEMA_VERSION} "
            f"required before updating tracks: {file_path}. "
            "Run chordflask-maintain migrate-schema on the media directory."
        )
    return status

def _validate_v3(data, file_path):
    for required in ("chord_tracks", "rhythm_tracks"):
        if required not in data:
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: "
                f"schema v3 must contain \"{required}\""
            )

    chord_tracks = data["chord_tracks"]
    if not isinstance(chord_tracks, dict):
        raise SchemaV3Error(
            f"Invalid chord data in {file_path}: chord_tracks must be an object"
        )
    for tid, entry in chord_tracks.items():
        if not isinstance(tid, str) or not tid.strip():
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: chord_tracks key must be a non-empty string"
            )
        if not isinstance(entry, dict):
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: chord_tracks[\"{tid}\"] must be an object"
            )
        if "chords" not in entry:
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: chord_tracks[\"{tid}\"] must contain \"chords\""
            )
        validate_chord_entries(
            entry["chords"], file_path, f"chord_tracks[\"{tid}\"].chords"
        )
        metadata = entry.get("metadata", {})
        if not isinstance(metadata, dict):
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: chord_tracks[\"{tid}\"].metadata must be an object"
            )

    rhythm_tracks = data["rhythm_tracks"]
    if not isinstance(rhythm_tracks, dict):
        raise SchemaV3Error(
            f"Invalid chord data in {file_path}: rhythm_tracks must be an object"
        )
    for tid, entry in rhythm_tracks.items():
        if not isinstance(tid, str) or not tid.strip():
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: rhythm_tracks key must be a non-empty string"
            )
        if not isinstance(entry, dict):
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: rhythm_tracks[\"{tid}\"] must be an object"
            )
        validate_rhythm_entry(
            entry, file_path, f"rhythm_tracks[\"{tid}\"]"
        )

    audio_tracks = data.get(AUDIO_TRACKS_KEY, {})
    if not isinstance(audio_tracks, dict):
        raise SchemaV3Error(
            f"Invalid chord data in {file_path}: audio_tracks must be an object"
        )
    for set_id, entry in audio_tracks.items():
        if not isinstance(set_id, str) or not set_id.strip():
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: "
                "audio_tracks key must be a non-empty string"
            )
        validate_audio_track_set(
            entry, file_path, f'audio_tracks["{set_id}"]'
        )

def _validate_legacy(data, file_path):
    chords = data.get("base_chords", [])
    validate_chord_entries(
        chords, file_path, "base_chords"
    )

    bpm = data.get("bpm")
    if bpm is not None:
        if not _is_finite_number(bpm) or bpm <= 0:
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: bpm must be positive, got {bpm!r}"
            )

    meter = data.get("meter_signature")
    if meter is not None:
        if not isinstance(meter, int) or isinstance(meter, bool) or meter <= 0:
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: "
                f"meter_signature must be a positive integer, got {meter!r}"
            )

    beat_times = data.get("beat_times", [])
    beat_indexes = data.get("beat_chord_indexes")
    if not isinstance(beat_times, list):
        raise SchemaV3Error(
            f"Invalid chord data in {file_path}: beat_times must be a list"
        )
    if beat_indexes is not None and not isinstance(beat_indexes, list):
        raise SchemaV3Error(
            f"Invalid chord data in {file_path}: beat_chord_indexes must be a list"
        )
    if beat_indexes is not None and len(beat_indexes) != len(beat_times):
        raise SchemaV3Error(
            f"Invalid chord data in {file_path}: "
            f"beat_chord_indexes length {len(beat_indexes)} "
            f"does not match beat_times length {len(beat_times)}"
        )

    prev_bt = None
    for i, bt in enumerate(beat_times):
        if not _is_finite_number(bt) or bt < 0:
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: "
                f"beat_times[{i}] is negative or not a finite number: {bt!r}"
            )
        if prev_bt is not None and bt < prev_bt:
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: "
                f"beat_times[{i}] {bt} is before previous {prev_bt}"
            )
        prev_bt = bt

    max_index = len(chords) - 1
    for i, ci in enumerate(beat_indexes or []):
        if (
            not isinstance(ci, int)
            or isinstance(ci, bool)
            or ci < 0
            or ci > max_index
        ):
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: "
                f"beat_chord_indexes[{i}] {ci!r} is out of range [0, {max_index}]"
            )

    beat_numbers = data.get("beat_numbers", [])
    if not isinstance(beat_numbers, list):
        raise SchemaV3Error(
            f"Invalid chord data in {file_path}: beat_numbers must be a list"
        )
    if beat_numbers and len(beat_numbers) != len(beat_times):
        raise SchemaV3Error(
            f"Invalid chord data in {file_path}: beat_numbers length "
            f"{len(beat_numbers)} does not match beat_times length {len(beat_times)}"
        )
    for i, beat_number in enumerate(beat_numbers):
        if (
            not isinstance(beat_number, int)
            or isinstance(beat_number, bool)
            or beat_number <= 0
        ):
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: beat_numbers[{i}] must be "
                f"a positive integer, got {beat_number!r}"
            )
        if meter is not None and beat_number > meter:
            raise SchemaV3Error(
                f"Invalid chord data in {file_path}: beat_numbers[{i}] "
                f"{beat_number} exceeds meter_signature {meter}"
            )


def load_analysis(
    media_path: Path, *, discard_invalid_metadata_for: str | None = None,
    require_current: bool = True,
) -> tuple[dict[str, Any], Path]:
    """Load validated analysis, optionally discarding one refreshed track's bad metadata.

    This repairs only the parsed in-memory copy; the file is never written.
    All chord entries and other tracks retain normal schema validation. Legacy
    data requires explicit migration by default; require_current=False permits
    read-only inspection of supported older storage without changing its layout.
    """
    json_path = analysis_json_path(media_path)
    if json_path.is_symlink() or not json_path.is_file():
        raise SchemaV3Error(f"Analysis file missing or not a regular file: {json_path}")
    try:
        data = read_analysis_json(json_path)
    except (OSError, UnicodeError, ValueError) as exc:
        raise SchemaV3Error(f"Analysis file unreadable or not valid JSON: {json_path}") from exc
    if discard_invalid_metadata_for is not None and isinstance(data, dict):
        tracks = data.get("chord_tracks")
        track = tracks.get(discard_invalid_metadata_for) if isinstance(tracks, dict) else None
        if isinstance(track, dict) and not isinstance(track.get("metadata", {}), dict):
            track["metadata"] = {}
    validate_analysis(data, json_path, require_current=require_current)
    return data, json_path



def read_analysis_json(json_path: Path | str) -> Any:
    """Read JSON only, retaining standard IO/JSON errors for repository callers."""
    with Path(json_path).open("r", encoding="utf-8") as handle:
        return json.load(handle)
