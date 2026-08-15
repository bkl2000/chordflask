import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FLASK_DIR = REPO_ROOT / "flask"

if str(FLASK_DIR) not in sys.path:
    sys.path.insert(0, str(FLASK_DIR))

from chorddata import ChordData, ChordTrackRepository


def test_chord_lookup_uses_latest_chord_before_position():
    data = ChordData()
    data.set_base_chords([
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 1.5, "chord": "G"},
        {"timestamp": 3.0, "chord": "F"},
    ])

    assert data.get_chord_at(-0.1) == "N"
    assert data.get_chord_at(0.0) == "C"
    assert data.get_chord_at(2.0) == "G"
    assert data.get_chord_at(9.0) == "F"


def test_unicode_formatting_can_be_toggled():
    data = ChordData()
    data.set_base_chords([
        {"timestamp": 0.0, "chord": "Bb"},
        {"timestamp": 1.0, "chord": "F#"},
    ])

    # Untransposed labels are respelled to Flats spelling before display.
    assert data.get_chords() == [(0.0, "Bb"), (1.0, "Gb")]

    data.set_unicode(True)

    assert data.get_chords() == [(0.0, "B\u266d"), (1.0, "G\u266d")]


def test_prefer_flats_can_be_toggled_for_display():
    data = ChordData(prefer_flats=True)
    data.set_base_chords([
        {"timestamp": 0.0, "chord": "Eb"},
        {"timestamp": 1.0, "chord": "Bb"},
    ])

    assert data.get_chords() == [(0.0, "Eb"), (1.0, "Bb")]

    data.set_prefer_flats(False)

    assert data.get_chords() == [(0.0, "D#"), (1.0, "A#")]


def test_beat_alignment_uses_active_chord():
    data = ChordData()
    data.set_base_chords([
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 2.0, "chord": "G"},
    ])
    data._beat_times = [0.5, 2.5, 4.0]

    assert data.get_chords_per_beat() == [(0.5, "C"), (2.5, "G"), (4.0, "G")]


def test_set_base_chords_preserves_detected_beat_timing_by_default():
    data = ChordData()
    detected_beats = [0.0, 0.51, 1.04, 1.58]

    data.set_base_chords([
        {"timestamp": 0.0, "chord": "C"},
    ], beat_times=detected_beats)

    assert data.beat_times == detected_beats


def test_repository_roundtrip_preserves_track_metadata(tmp_path):
    data = ChordData()
    data.set_base_chords([
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 1.0, "chord": "G"},
    ], beat_times=[0.0, 1.0, 2.0])
    data.bpm = 120
    data.meter_signature = 4
    data.transpose(-2)
    data.user_data = {"transpose": -2, "notes": {"chorus": "practice slowly"}}
    path = tmp_path / "track.json"
    repository = ChordTrackRepository()

    repository.save(data, str(path))
    loaded = repository.load(str(path))

    assert loaded._base_chords == [
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 1.0, "chord": "G"},
    ]
    assert loaded.bpm == 120
    assert loaded.meter_signature == 4
    assert loaded.beat_times == [0.0, 1.0, 2.0]
    assert loaded.transpose_semitones == -2
    assert loaded.user_data == {
        "transpose": -2,
        "notes": {"chorus": "practice slowly"},
    }


def test_get_chords_returns_a_defensive_copy():
    data = ChordData()
    data.set_base_chords([
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 1.0, "chord": "G"},
    ])

    first = data.get_chords()
    first.append((2.0, "F"))

    assert data.get_chords() == [(0.0, "C"), (1.0, "G")]
