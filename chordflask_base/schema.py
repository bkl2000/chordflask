"""Schema-v3 analysis contract (neutral, framework-free).

Part of :mod:`chordflask_base` — the base layer shared by the app (``flask/``)
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
from typing import Any

SCHEMA_VERSION = 3
SUPPORTED_SCHEMA_VERSIONS = {1, 2, 3}

ANALYSIS_DIR_NAME = ".chordflask"
ANALYSIS_SAMPLE_RATE = 44100

DEFAULT_CHORD_TRACK = "chordino"
DEFAULT_RHYTHM_TRACK = "qm_barbeattracker"
MADMOM_TRACK_ID = "madmom"
USER_EDITED_TRACK_ID = "user_edited"
PYTORCH_TRACK_ID = "pytorch"
PYTORCH_V2_TRACK_ID = "pytorch_v2"
REFERENCE_TRACK_ID = "reference"
BTC_TRACK_ID = "btc"


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
