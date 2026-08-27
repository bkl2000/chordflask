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
