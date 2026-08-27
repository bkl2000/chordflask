import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
FLASK_DIR = REPO_ROOT / "flask"

if str(FLASK_DIR) not in sys.path:
    sys.path.insert(0, str(FLASK_DIR))

import chordflask.chordutils as chordutils
from chordflask_base import ChordData


# ── pure pitch respelling ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("pitch", "prefer_flats", "expected"),
    [
        ("C", True, "C"),
        ("C", False, "C"),
        ("F", False, "F"),
        ("F#", True, "Gb"),
        ("C#", True, "Db"),
        ("D#", True, "Eb"),
        ("G#", True, "Ab"),
        ("A#", True, "Bb"),
        ("Bb", False, "A#"),
        ("Db", False, "C#"),
        ("Eb", False, "D#"),
        ("Gb", False, "F#"),
        ("Ab", False, "G#"),
        ("B#", True, "C"),
        ("B#", False, "C"),
        ("E#", True, "F"),
        ("E#", False, "F"),
        ("Cb", True, "B"),
        ("Cb", False, "B"),
        ("Fb", True, "E"),
        ("Fb", False, "E"),
    ],
)
def test_respell_pitch(pitch, prefer_flats, expected):
    assert chordutils.respell_pitch(pitch, prefer_flats) == expected


@pytest.mark.parametrize(
    ("label", "prefer_flats", "expected"),
    [
        ("F#m7", True, "Gbm7"),
        ("F#m7", False, "F#m7"),
        ("Bbmaj7", True, "Bbmaj7"),
        ("Bbmaj7", False, "A#maj7"),
        ("C", True, "C"),
        ("C", False, "C"),
        ("N", True, "N"),
        ("N", False, "N"),
        ("X", True, "X"),
        ("X", False, "X"),
        ("B#dim", True, "Cdim"),
        ("Cb", False, "B"),
        ("E#m", True, "Fm"),
        ("Fb", False, "E"),
        ("D#sus4", True, "Ebsus4"),
    ],
)
def test_respell_chord_label_roots_and_basses(label, prefer_flats, expected):
    assert chordutils.respell_chord_label(label, prefer_flats) == expected


@pytest.mark.parametrize(
    ("label", "prefer_flats", "expected"),
    [
        ("C7#9", True, "C7#9"),
        ("C7#9", False, "C7#9"),
        ("C7b9", True, "C7b9"),
        ("C7b9", False, "C7b9"),
        ("F#7b9", True, "Gb7b9"),
        ("Gb7b9", False, "F#7b9"),
        ("F#m7b5", True, "Gbm7b5"),
        ("Gbm7b5", False, "F#m7b5"),
        ("C7b5", True, "C7b5"),
        ("F#7b5", True, "Gb7b5"),
    ],
)
def test_respell_chord_label_preserves_quality_alterations(label, prefer_flats, expected):
    assert chordutils.respell_chord_label(label, prefer_flats) == expected


@pytest.mark.parametrize(
    ("label", "prefer_flats", "expected"),
    [
        ("Cmmaj7", True, "Cmmaj7"),
        ("Cmmaj7", False, "Cmmaj7"),
        ("F#mmaj7", True, "Gbmmaj7"),
        ("Bbmmaj7", False, "A#mmaj7"),
    ],
)
def test_respell_chord_label_preserves_mmaj7_suffix(label, prefer_flats, expected):
    assert chordutils.respell_chord_label(label, prefer_flats) == expected


def test_transpose_chord_pitches_preserves_mmaj7_suffix():
    assert chordutils.transpose_chord_pitches("Cmmaj7", 2, False) == "Dmmaj7"
    assert chordutils.transpose_chord_pitches("F#mmaj7", 1, False) == "Gmmaj7"
    assert chordutils.transpose_chord_pitches("Bbmmaj7", 2, True) == "Cmmaj7"


def test_respell_chord_label_respells_slash_bass_only():
    assert chordutils.respell_chord_label("E/G#", True) == "E/Ab"
    assert chordutils.respell_chord_label("E/G#", False) == "E/G#"
    assert chordutils.respell_chord_label("C#m7/G#", True) == "Dbm7/Ab"
    assert chordutils.respell_chord_label("Bb/D", False) == "A#/D"


def test_respell_chord_label_passes_non_string_through():
    assert chordutils.respell_chord_label(None, True) is None
    assert chordutils.respell_chord_label(7, True) == 7


# ── display integration ──────────────────────────────────────────────


def _flat_sharp_data():
    cd = ChordData()
    cd.set_chord_track("chordino", [
        {"timestamp": 0.0, "chord": "F#m7"},
        {"timestamp": 1.0, "chord": "Bbmaj7"},
        {"timestamp": 2.0, "chord": "C7#9"},
        {"timestamp": 3.0, "chord": "E/G#"},
    ])
    cd.set_rhythm_track(
        "qm_barbeattracker", bpm=120, meter_signature=4,
        beat_times=[0.0, 1.0, 2.0, 3.0],
        beat_numbers=[1, 2, 3, 4],
    )
    return cd


def test_chorddata_respells_untransposed_chords_to_flats():
    cd = _flat_sharp_data()
    cd.set_prefer_flats(True)

    labels = [chord for _, chord in cd.get_chords()]

    assert labels == ["Gbm7", "Bbmaj7", "C7#9", "E/Ab"]


def test_chorddata_respells_untransposed_chords_to_sharps():
    cd = _flat_sharp_data()
    cd.set_prefer_flats(False)

    labels = [chord for _, chord in cd.get_chords()]

    assert labels == ["F#m7", "A#maj7", "C7#9", "E/G#"]


def test_chorddata_respelling_is_display_only():
    cd = _flat_sharp_data()
    cd.set_prefer_flats(True)
    stored_before = cd.chord_track_chords("chordino")

    cd.get_chords()

    assert cd.chord_track_chords("chordino") == stored_before


def test_chorddata_respelling_applies_unicode_after_spelling():
    cd = _flat_sharp_data()
    cd.set_prefer_flats(True)
    cd.set_unicode(True)

    labels = [chord for _, chord in cd.get_chords()]

    assert labels[0] == "G\u266dm7"
    assert labels[3] == "E/A\u266d"


def test_chorddata_sharp_spelling_applies_unicode():
    cd = _flat_sharp_data()
    cd.set_prefer_flats(False)
    cd.set_unicode(True)

    labels = [chord for _, chord in cd.get_chords()]

    assert labels == ["F\u266fm7", "A\u266fmaj7", "C7\u266f9", "E/G\u266f"]


def test_chorddata_transposition_respells_nonzero_without_rewriting_quality():
    cd = ChordData()
    cd.set_chord_track("chordino", [
        {"timestamp": 0.0, "chord": "F#m7"},
        {"timestamp": 1.0, "chord": "C7#9"},
        {"timestamp": 2.0, "chord": "E/G#"},
    ])
    cd.set_rhythm_track("qm_barbeattracker", bpm=120, beat_times=[0.0])
    cd.transpose(2)
    cd.set_prefer_flats(True)

    flats = [chord for _, chord in cd.get_chords()]
    cd.set_prefer_flats(False)
    sharps = [chord for _, chord in cd.get_chords()]

    assert flats == ["Abm7", "D7#9", "Gb/Bb"]
    assert sharps == ["G#m7", "D7#9", "F#/A#"]
