import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FLASK_DIR = REPO_ROOT / "flask"

if str(FLASK_DIR) not in sys.path:
    sys.path.insert(0, str(FLASK_DIR))

from chord_postprocess import ChordPostProcessor


def test_disabled_postprocessor_returns_original_chords():
    chords = [
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 0.2, "chord": "G"},
    ]
    processor = ChordPostProcessor(enabled=False)

    processed = processor.process(chords)

    assert processed is chords


def test_postprocessor_merges_adjacent_equal_chords():
    chords = [
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 0.4, "chord": "C"},
        {"timestamp": 1.0, "chord": "G"},
    ]
    processor = ChordPostProcessor(enabled=True)

    processed = processor.process(chords)

    assert processed == [
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 1.0, "chord": "G"},
    ]


def test_postprocessor_removes_short_bridge_between_same_chords():
    chords = [
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 1.0, "chord": "Am"},
        {"timestamp": 1.2, "chord": "C"},
        {"timestamp": 2.0, "chord": "G"},
    ]
    processor = ChordPostProcessor(enabled=True, min_duration_seconds=0.35)

    processed = processor.process(chords)

    assert processed == [
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 2.0, "chord": "G"},
    ]


def test_postprocessor_removes_short_chord_when_neighbors_differ():
    chords = [
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 1.0, "chord": "Am"},
        {"timestamp": 1.2, "chord": "F"},
    ]
    processor = ChordPostProcessor(enabled=True, min_duration_seconds=0.35)

    processed = processor.process(chords)

    assert processed == [
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 1.2, "chord": "F"},
    ]


def test_postprocessor_can_be_enabled_from_environment(monkeypatch):
    monkeypatch.setenv("CHORDIFIER_POSTPROCESS", "1")
    monkeypatch.setenv("CHORDIFIER_KEY_CORRECT", "1")
    monkeypatch.setenv("CHORDIFIER_POSTPROCESS_MIN_DURATION", "0.5")
    monkeypatch.setenv("CHORDIFIER_KEY_CORRECT_MARGIN", "0.2")

    processor = ChordPostProcessor.from_environment()

    assert processor.enabled is True
    assert processor.key_correction_enabled is True
    assert processor.min_duration_seconds == 0.5
    assert processor.correction_margin == 0.2


def test_postprocessor_default_min_duration_from_environment(monkeypatch):
    monkeypatch.setenv("CHORDIFIER_POSTPROCESS", "1")
    monkeypatch.delenv("CHORDIFIER_POSTPROCESS_MIN_DURATION", raising=False)

    processor = ChordPostProcessor.from_environment()

    assert processor.min_duration_seconds == 0.5


def test_key_correction_changes_simple_major_to_minor_in_estimated_g_major():
    chords = [
        {"timestamp": 0.0, "chord": "G"},
        {"timestamp": 2.0, "chord": "C"},
        {"timestamp": 4.0, "chord": "D"},
        {"timestamp": 6.0, "chord": "Em"},
        {"timestamp": 8.0, "chord": "A"},
        {"timestamp": 10.0, "chord": "C"},
        {"timestamp": 12.0, "chord": "G"},
    ]
    processor = ChordPostProcessor(
        enabled=True,
        min_duration_seconds=0.0,
        key_correction_enabled=True,
    )

    processed = processor.process(chords)

    assert [entry["chord"] for entry in processed] == ["G", "C", "D", "Em", "Am", "C", "G"]
    assert processor.estimated_key_pc == 7


def test_key_correction_is_transposition_invariant_for_c_major():
    chords = [
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 2.0, "chord": "F"},
        {"timestamp": 4.0, "chord": "G"},
        {"timestamp": 6.0, "chord": "Am"},
        {"timestamp": 8.0, "chord": "D"},
        {"timestamp": 10.0, "chord": "F"},
        {"timestamp": 12.0, "chord": "C"},
    ]
    processor = ChordPostProcessor(
        enabled=True,
        min_duration_seconds=0.0,
        key_correction_enabled=True,
    )

    processed = processor.process(chords)

    assert [entry["chord"] for entry in processed] == ["C", "F", "G", "Am", "Dm", "F", "C"]
    assert processor.estimated_key_pc == 0


def test_key_correction_does_not_run_without_explicit_flag():
    chords = [
        {"timestamp": 0.0, "chord": "G"},
        {"timestamp": 2.0, "chord": "C"},
        {"timestamp": 4.0, "chord": "D"},
        {"timestamp": 6.0, "chord": "A7"},
        {"timestamp": 8.0, "chord": "G"},
    ]
    processor = ChordPostProcessor(enabled=True, min_duration_seconds=0.0)

    processed = processor.process(chords)

    assert [entry["chord"] for entry in processed] == ["G", "C", "D", "A7", "G"]


def test_key_correction_does_not_change_extended_or_dominant_chords():
    chords = [
        {"timestamp": 0.0, "chord": "Ab"},
        {"timestamp": 2.0, "chord": "Db"},
        {"timestamp": 4.0, "chord": "Eb"},
        {"timestamp": 6.0, "chord": "Bb7"},
        {"timestamp": 8.0, "chord": "Caug"},
        {"timestamp": 10.0, "chord": "Ab"},
    ]
    processor = ChordPostProcessor(
        enabled=True,
        min_duration_seconds=0.0,
        key_correction_enabled=True,
    )

    processed = processor.process(chords)

    assert [entry["chord"] for entry in processed] == ["Ab", "Db", "Eb", "Bb7", "Caug", "Ab"]
