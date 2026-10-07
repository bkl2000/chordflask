"""Canonical analysis completion and preservation, independent of runtimes."""

import copy
from functools import lru_cache
from pathlib import Path

from .schema import (
    DEFAULT_CHORD_TRACK,
    DEFAULT_RHYTHM_TRACK,
    USER_EDITED_RHYTHM_TRACK_ID,
    USER_EDITED_TRACK_ID,
)


def is_canonical_analysis_complete(chord_data):
    """Require both canonical track IDs in a loaded, valid analysis.

    Optional-only analyses remain valid. Empty canonical results are allowed;
    this predicate checks completion, not musical quality or source freshness.
    """
    return (
        chord_data.has_chord_track(DEFAULT_CHORD_TRACK)
        and chord_data.has_rhythm_track(DEFAULT_RHYTHM_TRACK)
    )


def preserve_analysis_user_data(current_track, replacement_track, *, drop_edited=False):
    """Merge existing noncanonical tracks/settings into a canonical replacement.

    Edited chords retain their rhythm source, snapshotting canonical rhythm
    before replacement when necessary. Raise if they cannot be preserved safely.
    """
    edited_metadata = None
    edited_rhythm_id = None
    if current_track.has_chord_track(USER_EDITED_TRACK_ID):
        metadata = current_track.chord_track_metadata(USER_EDITED_TRACK_ID)
        sources = metadata.get("sources")
        if isinstance(sources, dict) and isinstance(sources.get("rhythm"), str):
            edited_rhythm_id = sources["rhythm"]

        if not drop_edited:
            if not edited_rhythm_id or not current_track.has_rhythm_track(
                edited_rhythm_id
            ):
                raise RuntimeError(
                    "Cannot safely preserve Edited chords: their rhythm "
                    "source is missing or invalid"
                )
            edited_metadata = metadata
            if edited_rhythm_id == DEFAULT_RHYTHM_TRACK:
                if current_track.has_rhythm_track(USER_EDITED_RHYTHM_TRACK_ID):
                    raise RuntimeError(
                        "Cannot safely preserve Edited chords: reserved Edited "
                        "rhythm snapshot already exists"
                    )
                rhythm = current_track.rhythm_track_data(DEFAULT_RHYTHM_TRACK)
                snapshot_metadata = rhythm.get("metadata", {})
                snapshot_metadata.update({
                    "display_name": "Edited rhythm snapshot",
                    "snapshot_for": USER_EDITED_TRACK_ID,
                    "source_track_id": DEFAULT_RHYTHM_TRACK,
                })
                rhythm["metadata"] = snapshot_metadata
                replacement_track.set_rhythm_track(
                    USER_EDITED_RHYTHM_TRACK_ID, **rhythm
                )
                edited_metadata["sources"]["rhythm"] = (
                    USER_EDITED_RHYTHM_TRACK_ID
                )
                edited_rhythm_id = USER_EDITED_RHYTHM_TRACK_ID

    for track_id in current_track.available_chord_track_ids:
        if track_id == DEFAULT_CHORD_TRACK:
            continue
        if drop_edited and track_id == USER_EDITED_TRACK_ID:
            continue
        metadata = (
            edited_metadata
            if track_id == USER_EDITED_TRACK_ID and edited_metadata is not None
            else current_track.chord_track_metadata(track_id)
        )
        replacement_track.set_chord_track(
            track_id,
            current_track.chord_track_chords(track_id),
            metadata=metadata,
        )
    for track_id in current_track.available_rhythm_track_ids:
        if track_id == DEFAULT_RHYTHM_TRACK:
            continue
        if (
            drop_edited
            and track_id == USER_EDITED_RHYTHM_TRACK_ID
            and edited_rhythm_id == USER_EDITED_RHYTHM_TRACK_ID
        ):
            continue
        rhythm = current_track.rhythm_track_data(track_id)
        replacement_track.set_rhythm_track(track_id, **rhythm)

    for track_id in current_track.available_audio_track_ids:
        replacement_track.set_audio_track(
            track_id,
            current_track.audio_track_data(track_id),
        )

    replacement_track.transpose(current_track.transpose_semitones)
    replacement_track.set_prefer_flats(current_track.prefer_flats)
    replacement_track.user_data = current_track.user_data
    # Canonical refresh rebuilds known canonical data, while extensions and
    # preserved optional tracks come from the latest locked document.
    opaque = copy.deepcopy(current_track._opaque_document)
    for key, value in replacement_track._opaque_document.items():
        if key in ("chord_tracks", "rhythm_tracks"):
            tracks = opaque.setdefault(key, {})
            for track_id, entry in value.items():
                tracks.setdefault(track_id, {}).update(copy.deepcopy(entry))
        else:
            opaque[key] = copy.deepcopy(value)
    replacement_track._opaque_document = opaque


def _source_stamp(stat):
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def media_source_identity(media_path):
    """Hash original media bytes with the same streaming SHA-256 used by producers."""
    import hashlib
    import os

    path = Path(media_path)
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        digest = hashlib.sha256()
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        after = os.fstat(handle.fileno())
    if _source_stamp(before) != _source_stamp(after) or _source_stamp(after) != _source_stamp(path.stat()):
        raise RuntimeError("Media changed while reading source identity; retry")
    return {"sha256": digest.hexdigest(), "size": after.st_size}


@lru_cache(maxsize=128)
def _cached_source_identity(path, stamp):
    identity = media_source_identity(path)
    if _source_stamp(path.stat()) != stamp:
        raise RuntimeError("Media changed while reading source identity; retry")
    return identity


def canonical_source_status(chord_data, media_path, *, identity=None, cache_identity=False):
    """Return current/stale/legacy independently of schema validity/completeness.

    Missing or unverifiable metadata is legacy/unknown, never proof of currency.
    Legacy inspection does not hash media. Checks run only at explicit load or
    analysis boundaries, not playback polling. Web callers may reuse a verified
    digest while the full filesystem stamp is unchanged (including ctime, so
    same-size rewrites with restored mtime invalidate it). The cache is bounded,
    process-local and never persisted. Analysis/CLI verification remains uncached.
    """
    if not is_canonical_analysis_complete(chord_data):
        return "legacy"
    sources = [chord_data.chord_track_metadata(DEFAULT_CHORD_TRACK).get("source_media"),
               chord_data.rhythm_track_metadata(DEFAULT_RHYTHM_TRACK).get("source_media")]
    for source in sources:
        if not isinstance(source, dict):
            return "legacy"
        digest, size = source.get("sha256"), source.get("size")
        if (not isinstance(digest, str) or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
                or type(size) is not int or size < 0):
            return "legacy"
    if sources[0] != sources[1]:
        return "stale"
    try:
        if identity is not None:
            current = identity
        elif cache_identity:
            path = Path(media_path).resolve(strict=True)
            stamp = _source_stamp(path.stat())
            current = _cached_source_identity(path, stamp)
            if _source_stamp(path.stat()) != stamp:
                raise RuntimeError("Media changed during source verification; retry")
        else:
            current = media_source_identity(media_path)
    except (OSError, RuntimeError):
        return "legacy"
    return "current" if sources[0] == current else "stale"


def record_canonical_source(chord_data, identity):
    """Attach the same original-media identity to both generated canonical tracks."""
    if not is_canonical_analysis_complete(chord_data):
        return
    metadata = chord_data.chord_track_metadata(DEFAULT_CHORD_TRACK)
    metadata["source_media"] = dict(identity)
    chord_data.set_chord_track(DEFAULT_CHORD_TRACK,
                               chord_data.chord_track_chords(DEFAULT_CHORD_TRACK), metadata=metadata)
    rhythm = chord_data.rhythm_track_data(DEFAULT_RHYTHM_TRACK)
    rhythm["metadata"]["source_media"] = dict(identity)
    chord_data.set_rhythm_track(DEFAULT_RHYTHM_TRACK, **rhythm)
