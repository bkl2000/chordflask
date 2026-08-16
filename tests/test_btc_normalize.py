"""Tests for BTC raw-label -> ChordFlask normalization."""

import pytest

from chordflask_btc.normalize import (
    BTC_QUALITY_SUFFIX,
    normalize_btc_events,
    normalize_btc_label,
)


def test_all_quality_mappings():
    cases = {
        "C:maj": "C",
        "C:min": "Cm",
        "C:dim": "Cdim",
        "C:aug": "Caug",
        "C:min6": "Cm6",
        "C:maj6": "C6",
        "C:min7": "Cm7",
        "C:minmaj7": "Cmmaj7",
        "C:maj7": "Cmaj7",
        "C:7": "C7",
        "C:dim7": "Cdim7",
        "C:hdim7": "Cm7b5",
        "C:sus2": "Csus2",
        "C:sus4": "Csus4",
    }
    for raw, expected in cases.items():
        assert normalize_btc_label(raw) == expected, raw


def test_sharp_roots():
    assert normalize_btc_label("F#:7") == "F#7"
    assert normalize_btc_label("B:maj7") == "Bmaj7"
    assert normalize_btc_label("A:hdim7") == "Am7b5"
    assert normalize_btc_label("D:minmaj7") == "Dmmaj7"
    assert normalize_btc_label("G#:min") == "G#m"


def test_bare_root_is_major():
    assert normalize_btc_label("C") == "C"
    assert normalize_btc_label("F#") == "F#"
    assert normalize_btc_label("B") == "B"


def test_n_and_x_pass_through():
    assert normalize_btc_label("N") == "N"
    assert normalize_btc_label("X") == "X"


def test_unknown_quality_raises():
    with pytest.raises(ValueError):
        normalize_btc_label("C:9")
    with pytest.raises(ValueError):
        normalize_btc_label("C:foo")


def test_non_string_raises():
    with pytest.raises(ValueError):
        normalize_btc_label(None)
    with pytest.raises(ValueError):
        normalize_btc_label(7)


def test_empty_raises():
    with pytest.raises(ValueError):
        normalize_btc_label("")
    with pytest.raises(ValueError):
        normalize_btc_label("   ")


def test_quality_suffix_table_is_complete():
    assert BTC_QUALITY_SUFFIX == {
        "maj": "",
        "min": "m",
        "dim": "dim",
        "aug": "aug",
        "min6": "m6",
        "maj6": "6",
        "min7": "m7",
        "minmaj7": "mmaj7",
        "maj7": "maj7",
        "7": "7",
        "dim7": "dim7",
        "hdim7": "m7b5",
        "sus2": "sus2",
        "sus4": "sus4",
    }


def test_normalize_btc_events():
    events = [
        {"timestamp": 0.0, "chord": "N"},
        {"timestamp": 2.69, "chord": "F#:7"},
        {"timestamp": 4.09, "chord": "B:maj7"},
    ]
    result = normalize_btc_events(events)
    assert result == [
        {"timestamp": 0.0, "chord": "N"},
        {"timestamp": 2.69, "chord": "F#7"},
        {"timestamp": 4.09, "chord": "Bmaj7"},
    ]


def test_normalize_btc_events_rejects_malformed():
    with pytest.raises(ValueError):
        normalize_btc_events([{"timestamp": 0.0}])
