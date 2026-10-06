"""BTC track read/write helpers and compatibility re-exports of neutral schema IO.

This module never imports Flask or torch. The shared Schema-v3 contract (track
IDs, entry validation, atomic write, analysis-JSON path) comes from
``chordflask_base`` — the neutral base layer. This module only adds the
BTC-track read/write helpers.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from chordflask_base import (
    ANALYSIS_DIR_NAME as ANALYSIS_DIR_NAME,
    BTC_TRACK_ID,
    SCHEMA_VERSION,
    SchemaV3Error,
    analysis_json_path,
    validate_chord_entries,
    load_analysis as load_analysis,
    validate_analysis as validate_analysis,
    write_atomic,
    analysis_json_lock,
)


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
    with analysis_json_lock(json_path):
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
