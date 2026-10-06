"""Alignment grid identity, independent of analysis engines and Lyrics runtimes."""

import hashlib
import json


def rhythm_grid_fingerprint(chord_data):
    """Identify the selected grid's ordered times, beat numbers and meter.

    Times are normalized to floats without rounding. Track IDs, BPM, chords and
    metadata are excluded: an identical Edited snapshot is the same grid.
    Missing/empty grids cannot verify synchronization and return None.
    """
    if chord_data is None or not chord_data.active_rhythm_track_id or not chord_data.beat_times:
        return None
    grid = {
        "beat_times": [float(time) if time else 0.0 for time in chord_data.beat_times],
        "beat_numbers": list(chord_data.beat_numbers),
        "meter_signature": chord_data.meter_signature,
    }
    canonical = json.dumps(grid, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(("chordflask-rhythm-grid-v1\0" + canonical).encode()).hexdigest()
