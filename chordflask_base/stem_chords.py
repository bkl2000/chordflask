"""Chordino chord tracks computed from one stem of a registered audio-track set.

A stem result is an ordinary Schema-v3 chord track (``chordino_stem_<stem>``)
displayed on the original rhythm grid. Stems are sample-aligned with the
original media, so timestamps need no offset. Freshness is derived from
hashes already recorded in the analysis JSON; nothing here reads media files.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from .schema import DEFAULT_CHORD_TRACK

STEM_CHORD_TRACK_PREFIX = "chordino_stem_"
_STEM_NAME = re.compile(r"[a-z0-9_]+")


def stem_chord_track_id(stem: str) -> str:
    if not isinstance(stem, str) or not _STEM_NAME.fullmatch(stem):
        raise ValueError(f"stem name must match [a-z0-9_]+, got {stem!r}")
    return f"{STEM_CHORD_TRACK_PREFIX}{stem}"


def stem_from_track_id(track_id: str) -> str | None:
    if not isinstance(track_id, str) or not track_id.startswith(STEM_CHORD_TRACK_PREFIX):
        return None
    stem = track_id[len(STEM_CHORD_TRACK_PREFIX):]
    return stem if _STEM_NAME.fullmatch(stem) else None


def build_stem_chord_metadata(
    *,
    stem: str,
    set_id: str,
    stem_entry: dict[str, Any],
    set_source_sha256: str,
    source_media: dict[str, Any] | None,
) -> dict[str, Any]:
    metadata = {
        "display_name": f"Chordino · {stem.capitalize()} stem",
        "engine": "chordino",
        "audio_source": {
            "kind": "stem",
            "set_id": set_id,
            "stem": stem,
            "stem_sha256": stem_entry["sha256"],
            "stem_size": stem_entry["size"],
            "set_source_sha256": set_source_sha256,
        },
        "timeline": {"reference": "original", "offset_seconds": 0.0},
    }
    if source_media is not None:
        metadata["source_media"] = copy.deepcopy(source_media)
    return metadata


def stem_chord_track_status(chord_data, track_id: str) -> str | None:
    """Return current/stale/stems_missing for a stem track, or None otherwise."""
    if not chord_data.has_chord_track(track_id):
        return None
    audio_source = chord_data.chord_track_metadata(track_id).get("audio_source")
    if not isinstance(audio_source, dict) or audio_source.get("kind") != "stem":
        return None
    track_source_media = chord_data.chord_track_metadata(track_id).get("source_media")
    chordino_source_media = (
        chord_data.chord_track_metadata(DEFAULT_CHORD_TRACK).get("source_media")
        if chord_data.has_chord_track(DEFAULT_CHORD_TRACK)
        else None
    )
    set_id = audio_source.get("set_id")
    stem = audio_source.get("stem")
    if not isinstance(set_id, str) or not isinstance(stem, str):
        return "stale"
    if not chord_data.has_audio_track(set_id):
        return "stems_missing"
    try:
        set_data = chord_data.audio_track_data(set_id)
        if set_data["tracks"][stem]["sha256"] != audio_source["stem_sha256"]:
            return "stale"
        if set_data["metadata"]["source"]["sha256"] != audio_source["set_source_sha256"]:
            return "stale"
    except (KeyError, TypeError, ValueError):
        return "stale"
    # Unknown original provenance is not proof of staleness (see canonical_source_status).
    if chordino_source_media is not None and chordino_source_media != track_source_media:
        return "stale"
    return "current"


__all__ = [
    "STEM_CHORD_TRACK_PREFIX",
    "build_stem_chord_metadata",
    "stem_chord_track_id",
    "stem_chord_track_status",
    "stem_from_track_id",
]
