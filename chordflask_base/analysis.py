"""Canonical analysis completion and preservation, independent of runtimes."""

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
