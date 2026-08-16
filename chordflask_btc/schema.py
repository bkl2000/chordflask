"""Schema-v3 read/write helpers for the BTC chord track.

This module never imports Flask or torch. The shared Schema-v3 contract (track
IDs, entry validation, atomic write, analysis-JSON path) comes from
``chordflask_base`` — the neutral base layer. This module only adds the
BTC-track read/write helpers.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from chordflask_base import (
    ANALYSIS_DIR_NAME as ANALYSIS_DIR_NAME,
    BTC_TRACK_ID,
    SCHEMA_VERSION,
    SchemaV3Error,
    analysis_json_path,
    validate_chord_entries,
    validate_rhythm_entry,
    write_atomic,
)


def load_analysis(media_path: Path) -> tuple[dict[str, Any], Path]:
    json_path = analysis_json_path(media_path)
    if json_path.is_symlink() or not json_path.is_file():
        raise SchemaV3Error(f"Analysis file missing or not a regular file: {json_path}")
    try:
        text = json_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SchemaV3Error(f"Analysis file missing or unreadable: {json_path}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SchemaV3Error(f"Analysis file is not valid JSON: {json_path}") from exc
    validate_analysis(data, json_path)
    return data, json_path


def validate_analysis(data: Any, json_path: Path | str) -> None:
    if not isinstance(data, dict):
        raise SchemaV3Error(f"Analysis file root must be an object: {json_path}")
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise SchemaV3Error(
            f"Analysis file must be Schema v{SCHEMA_VERSION}, got {version!r}: {json_path}"
        )
    chord_tracks = data.get("chord_tracks")
    if not isinstance(chord_tracks, dict):
        raise SchemaV3Error(f"Analysis file must contain a 'chord_tracks' object: {json_path}")
    rhythm_tracks = data.get("rhythm_tracks")
    if not isinstance(rhythm_tracks, dict):
        raise SchemaV3Error(f"Analysis file must contain a 'rhythm_tracks' object: {json_path}")
    if not isinstance(data.get("prefer_flats", True), bool):
        raise SchemaV3Error(f"prefer_flats must be a boolean: {json_path}")
    transpose = data.get("transpose", 0)
    if not isinstance(transpose, int) or isinstance(transpose, bool):
        raise SchemaV3Error(f"transpose must be an integer: {json_path}")
    if not isinstance(data.get("user_data", {}), dict):
        raise SchemaV3Error(f"user_data must be an object: {json_path}")
    for track_id, entry in chord_tracks.items():
        if not isinstance(track_id, str) or not track_id.strip() or not isinstance(entry, dict):
            raise SchemaV3Error(f"Invalid chord track {track_id!r}: {json_path}")
        validate_chord_entries(
            entry.get("chords"), json_path, f"chord_tracks[{track_id}].chords"
        )
        if not isinstance(entry.get("metadata", {}), dict):
            raise SchemaV3Error(f"Chord track {track_id!r} metadata must be an object: {json_path}")
    for track_id, entry in rhythm_tracks.items():
        if not isinstance(track_id, str) or not track_id.strip() or not isinstance(entry, dict):
            raise SchemaV3Error(f"Invalid rhythm track {track_id!r}: {json_path}")
        validate_rhythm_entry(entry, json_path, f"rhythm_tracks[{track_id}]")


def _validate_chords(chords: Any) -> None:
    validate_chord_entries(chords, "<chords>", "chords")


def make_btc_track(
    chords: list[dict[str, Any]], metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    _validate_chords(chords)
    clean_metadata = {} if metadata is None else metadata
    if not isinstance(clean_metadata, dict):
        raise SchemaV3Error("btc track metadata must be an object")
    return {
        "chords": [{"timestamp": entry["timestamp"], "chord": entry["chord"]} for entry in chords],
        "metadata": copy.deepcopy(clean_metadata),
    }


def insert_btc_track(
    data: dict[str, Any],
    chords: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
    *,
    replace: bool = False,
) -> dict[str, Any]:
    if not isinstance(data, dict) or not isinstance(data.get("chord_tracks"), dict):
        raise SchemaV3Error("analysis data must contain a 'chord_tracks' object")
    if BTC_TRACK_ID in data["chord_tracks"] and not replace:
        raise SchemaV3Error(
            f"a '{BTC_TRACK_ID}' chord track already exists; use --replace to overwrite it"
        )
    result = copy.deepcopy(data)
    result["chord_tracks"][BTC_TRACK_ID] = make_btc_track(chords, metadata)
    return result


def write_btc_track(
    media_path: Path,
    chords: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
    *,
    replace: bool = False,
) -> Path:
    json_path = analysis_json_path(media_path)
    if json_path.exists(follow_symlinks=False):
        data, json_path = load_analysis(media_path)
    else:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": SCHEMA_VERSION,
            "prefer_flats": True,
            "transpose": 0,
            "user_data": {},
            "chord_tracks": {},
            "rhythm_tracks": {},
        }
    updated = insert_btc_track(data, chords, metadata, replace=replace)
    validate_analysis(updated, json_path)
    write_atomic(json_path, updated)
    return json_path
