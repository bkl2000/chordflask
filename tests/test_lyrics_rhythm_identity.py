"""Synthetic alignment provenance; never read or regenerate real media."""

import copy

import pytest

from chordflask.chordpro_song import parse_chordpro, sheet_rhythm_status
from chordflask_base import ChordData
from chordflask_base.analysis import preserve_analysis_user_data
from chordflask_base.rhythm import rhythm_grid_fingerprint


def grid(*, times=None, numbers=None, meter=4, track="qm_barbeattracker", bpm=60):
    data = ChordData()
    data.set_rhythm_track(
        track, beat_times=times if times is not None else [0, 1, 2, 3],
        beat_numbers=numbers if numbers is not None else [1, 2, 3, 4],
        meter_signature=meter, bpm=bpm,
    )
    return data


def sheet(data):
    return parse_chordpro(
        f"{{x_chordflask_rhythm_fingerprint: {rhythm_grid_fingerprint(data)}}}\n"
        "{x_chordflask_beats: 0,2}\n{x_chordflask_end: 4}\n[C]Hello [G]world"
    )


@pytest.mark.parametrize("changed", [
    {"times": [0, 1.01, 2, 3]},
    {"times": [0, 1, 2], "numbers": [1, 2, 3]},
    {"numbers": [2, 3, 4, 1]},
    {"meter": 5},
])
def test_grid_changes_are_stale_without_changing_sheet(changed):
    song = sheet(grid())
    original = copy.deepcopy(song)
    assert sheet_rhythm_status(song, grid()) == "CURRENT"
    assert sheet_rhythm_status(song, grid(**changed)) == "STALE"
    assert song == original


def test_identity_ignores_unrelated_fields_and_numeric_spelling():
    original = grid()
    equivalent = grid(times=[-0.0, 1.0, 2.0, 3.0], track="manual", bpm=123)
    equivalent.set_chord_track("manual", [{"timestamp": 0, "chord": "Am"}])
    assert rhythm_grid_fingerprint(equivalent) == rhythm_grid_fingerprint(original)
    assert sheet_rhythm_status(sheet(original), equivalent) == "CURRENT"


@pytest.mark.parametrize("directive", ["", "{x_chordflask_rhythm_fingerprint: invalid}\n"])
def test_legacy_is_readable_and_content_unchanged(directive):
    content = "{x_chordflask_beats: 0}\n{x_chordflask_end: 4}\n[C]Hello"
    song = parse_chordpro(directive + content)
    assert song["blocks"] == parse_chordpro(content)["blocks"]
    assert sheet_rhythm_status(song, grid()) == "LEGACY"


def test_unavailable_grid_is_unknown():
    song = sheet(grid())
    assert sheet_rhythm_status(song, None) == "LEGACY"
    assert sheet_rhythm_status(song, ChordData()) == "LEGACY"


def test_edited_snapshot_preserves_identity_across_canonical_replacement():
    original = grid()
    original.set_chord_track("chordino", [{"timestamp": 0, "chord": "C"}])
    original.create_beat_aligned_track("user_edited")
    song = sheet(original)
    replacement = grid(times=[0, 1.1, 2.2, 3.3])
    replacement.set_chord_track("chordino", [{"timestamp": 0, "chord": "G"}])
    preserve_analysis_user_data(original, replacement)
    assert sheet_rhythm_status(song, replacement) == "STALE"
    sources = replacement.chord_track_metadata("user_edited")["sources"]
    replacement.select_rhythm_track(sources["rhythm"])
    assert sheet_rhythm_status(song, replacement) == "CURRENT"
    replacement.set_rhythm_track(
        sources["rhythm"], beat_times=[0, 1.2, 2, 3],
        beat_numbers=[1, 2, 3, 4], meter_signature=4,
    )
    assert sheet_rhythm_status(song, replacement) == "STALE"
