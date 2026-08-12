import json
import os
import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "flask"))

import chorddata
from chorddata import ChordTrackRepository, ChordData


def _build_valid():
    return {
        "schema_version": 1,
        "base_chords": [
            {"timestamp": 0.0, "chord": "C"},
            {"timestamp": 1.5, "chord": "G"},
            {"timestamp": 3.0, "chord": "F"},
        ],
        "prefer_flats": True,
        "transpose": 0,
        "bpm": 120.0,
        "meter_signature": 4,
        "beat_times": [0.0, 0.5, 1.0],
        "beat_chord_indexes": [0, 0, 1],
    }


def _write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f)
    return path


# ── schema versioning ──────────────────────────────────────────────


def test_valid_v1_loads_correctly(tmp_path):
    repo = ChordTrackRepository()
    path = _write_json(tmp_path / "chords.json", _build_valid())
    track = repo.load(path)
    assert track.bpm == 120.0
    assert track.meter_signature == 4
    assert len(track._base_chords) == 3
    assert track._chord_times == [0.0, 1.5, 3.0]


def test_missing_schema_version_loads_with_warning(tmp_path, caplog):
    repo = ChordTrackRepository()
    data = _build_valid()
    del data["schema_version"]
    path = _write_json(tmp_path / "chords.json", data)
    import logging
    caplog.set_level(logging.WARNING)
    track = repo.load(path)
    assert any("no schema_version" in m.lower() for m in caplog.text.lower().splitlines())
    assert track.bpm == 120.0


def test_future_schema_version_raises(tmp_path):
    repo = ChordTrackRepository()
    data = _build_valid()
    data["schema_version"] = 99
    path = _write_json(tmp_path / "chords.json", data)
    with pytest.raises(ValueError, match="Unsupported chord data schema version 99"):
        repo.load(path)


# ── validation ──────────────────────────────────────────────────────


def test_negative_timestamp_raises(tmp_path):
    repo = ChordTrackRepository()
    data = _build_valid()
    data["base_chords"][1]["timestamp"] = -1.0
    path = _write_json(tmp_path / "chords.json", data)
    with pytest.raises(ValueError, match="negative timestamp"):
        repo.load(path)


def test_unsorted_timestamps_raises(tmp_path):
    repo = ChordTrackRepository()
    data = _build_valid()
    data["base_chords"][1]["timestamp"] = 5.0  # larger than next
    path = _write_json(tmp_path / "chords.json", data)
    with pytest.raises(ValueError, match="is before previous"):
        repo.load(path)


def test_empty_chord_string_raises(tmp_path):
    repo = ChordTrackRepository()
    data = _build_valid()
    data["base_chords"][1]["chord"] = ""
    path = _write_json(tmp_path / "chords.json", data)
    with pytest.raises(ValueError, match="empty or missing chord"):
        repo.load(path)


def test_non_object_chord_entry_raises_value_error(tmp_path):
    data = _build_valid()
    data["base_chords"][1] = "G"
    path = _write_json(tmp_path / "chords.json", data)
    with pytest.raises(ValueError, match=r"base_chords\[1\] must be an object"):
        ChordTrackRepository().load(path)


@pytest.mark.parametrize("timestamp", [True, float("nan"), float("inf")])
def test_non_finite_or_boolean_timestamp_raises(tmp_path, timestamp):
    data = _build_valid()
    data["base_chords"][0]["timestamp"] = timestamp
    path = _write_json(tmp_path / "chords.json", data)
    with pytest.raises(ValueError, match="invalid or negative timestamp"):
        ChordTrackRepository().load(path)


def test_nonpositive_bpm_raises(tmp_path):
    repo = ChordTrackRepository()
    data = _build_valid()
    data["bpm"] = 0
    path = _write_json(tmp_path / "chords.json", data)
    with pytest.raises(ValueError, match="bpm must be positive"):
        repo.load(path)


def test_negative_bpm_raises(tmp_path):
    repo = ChordTrackRepository()
    data = _build_valid()
    data["bpm"] = -10
    path = _write_json(tmp_path / "chords.json", data)
    with pytest.raises(ValueError, match="bpm must be positive"):
        repo.load(path)


def test_invalid_meter_signature_raises(tmp_path):
    repo = ChordTrackRepository()
    data = _build_valid()
    data["meter_signature"] = "4/4"
    path = _write_json(tmp_path / "chords.json", data)
    with pytest.raises(ValueError, match="meter_signature must be a positive integer"):
        repo.load(path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("bpm", True, "bpm must be positive"),
        ("bpm", float("inf"), "bpm must be positive"),
        ("meter_signature", True, "meter_signature must be a positive integer"),
        ("prefer_flats", 1, "prefer_flats must be a boolean"),
        ("transpose", True, "transpose must be an integer"),
        ("user_data", [], "user_data must be an object"),
    ],
)
def test_invalid_metadata_types_raise(tmp_path, field, value, message):
    data = _build_valid()
    data[field] = value
    path = _write_json(tmp_path / "chords.json", data)
    with pytest.raises(ValueError, match=message):
        ChordTrackRepository().load(path)


def test_beat_indexes_length_mismatch_raises(tmp_path):
    repo = ChordTrackRepository()
    data = _build_valid()
    data["beat_times"] = [0.0, 1.0]
    data["beat_chord_indexes"] = [0]
    path = _write_json(tmp_path / "chords.json", data)
    with pytest.raises(ValueError, match="does not match beat_times length"):
        repo.load(path)


def test_beat_indexes_out_of_range_raises(tmp_path):
    repo = ChordTrackRepository()
    data = _build_valid()
    data["beat_chord_indexes"] = [0, 10, 0]
    path = _write_json(tmp_path / "chords.json", data)
    with pytest.raises(ValueError, match="is out of range"):
        repo.load(path)


def test_nonempty_beat_indexes_with_empty_beat_times_raises(tmp_path):
    data = _build_valid()
    data["beat_times"] = []
    data["beat_chord_indexes"] = [0]
    path = _write_json(tmp_path / "chords.json", data)
    with pytest.raises(ValueError, match="does not match beat_times length"):
        ChordTrackRepository().load(path)


def test_beat_index_is_invalid_when_there_are_no_chords(tmp_path):
    data = _build_valid()
    data["base_chords"] = []
    data["beat_times"] = [0.0]
    data["beat_chord_indexes"] = [0]
    path = _write_json(tmp_path / "chords.json", data)
    with pytest.raises(ValueError, match="is out of range"):
        ChordTrackRepository().load(path)


def test_bpm_can_be_none(tmp_path):
    repo = ChordTrackRepository()
    data = _build_valid()
    data["bpm"] = None
    path = _write_json(tmp_path / "chords.json", data)
    track = repo.load(path)
    assert track.bpm is None


def test_meter_signature_can_be_none(tmp_path):
    repo = ChordTrackRepository()
    data = _build_valid()
    data["meter_signature"] = None
    path = _write_json(tmp_path / "chords.json", data)
    track = repo.load(path)
    assert track.meter_signature is None


def test_corrupt_json_raises(tmp_path):
    repo = ChordTrackRepository()
    path = tmp_path / "bad.json"
    path.write_text("{not valid json")
    with pytest.raises(json.JSONDecodeError):
        repo.load(path)


# ── atomic save ─────────────────────────────────────────────────────


def test_save_includes_schema_version(tmp_path):
    repo = ChordTrackRepository()
    track = ChordData()
    track.set_base_chords([{"timestamp": 0.0, "chord": "A"}])
    track.bpm = 120
    path = str(tmp_path / "out.json")
    repo.save(track, path)
    with open(path) as f:
        data = json.load(f)
    assert data["schema_version"] == 3
    assert "chord_tracks" in data
    assert "chordino" in data["chord_tracks"]
    assert "beat_chord_indexes" not in data


def test_v2_roundtrip_preserves_qm_beat_numbers(tmp_path):
    track = ChordData()
    track.set_base_chords(
        [{"timestamp": 0.0, "chord": "A"}],
        beat_times=[0.0, 0.5, 1.0, 1.5],
    )
    track.set_beat_numbers([1, 2, 3, 4])
    path = tmp_path / "out.json"

    ChordTrackRepository().save(track, path)
    loaded = ChordTrackRepository().load(path)

    assert loaded.beat_numbers == [1, 2, 3, 4]


def test_v2_rejects_beat_number_length_mismatch(tmp_path):
    data = _build_valid()
    data["schema_version"] = 2
    data["beat_numbers"] = [1, 2]
    path = _write_json(tmp_path / "chords.json", data)

    with pytest.raises(ValueError, match="beat_numbers length"):
        ChordTrackRepository().load(path)


def test_v2_rejects_beat_number_outside_meter(tmp_path):
    data = _build_valid()
    data["schema_version"] = 2
    data["beat_numbers"] = [1, 2, 5]
    path = _write_json(tmp_path / "chords.json", data)

    with pytest.raises(ValueError, match="exceeds meter_signature"):
        ChordTrackRepository().load(path)


def test_save_is_atomic_no_tmp_leftover(tmp_path):
    repo = ChordTrackRepository()
    track = ChordData()
    track.set_base_chords([{"timestamp": 0.0, "chord": "A"}])
    path = str(tmp_path / "out.json")
    repo.save(track, path)
    assert not os.path.exists(path + ".tmp")
    assert os.path.exists(path)


def test_save_validates_before_replacing_existing_file(tmp_path):
    path = tmp_path / "out.json"
    path.write_text("original", encoding="utf-8")
    track = ChordData()
    track._base_chords = [{"timestamp": float("nan"), "chord": "C"}]

    with pytest.raises(ValueError, match="invalid or negative timestamp"):
        ChordTrackRepository().save(track, path)

    assert path.read_text(encoding="utf-8") == "original"
    assert list(tmp_path.glob(".out.json.*.tmp")) == []


def test_save_failure_preserves_existing_file_and_cleans_temp(tmp_path, monkeypatch):
    path = tmp_path / "out.json"
    path.write_text("original", encoding="utf-8")
    track = ChordData()
    track.set_base_chords([{"timestamp": 0.0, "chord": "C"}])

    def fail_replace(source, destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(chorddata.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        ChordTrackRepository().save(track, path)

    assert path.read_text(encoding="utf-8") == "original"
    assert list(tmp_path.glob(".out.json.*.tmp")) == []


def test_repository_roundtrip_preserves_timestamps_and_metadata(tmp_path):
    repo = ChordTrackRepository()
    track_in = ChordData()
    track_in.set_base_chords([
        {"timestamp": 0.5, "chord": "Dm"},
        {"timestamp": 2.0, "chord": "G"},
        {"timestamp": 4.0, "chord": "C"},
    ])
    track_in.bpm = 98.5
    track_in.meter_signature = 3
    path = str(tmp_path / "roundtrip.json")
    repo.save(track_in, path)
    track_out = repo.load(path)
    assert track_out.bpm == 98.5
    assert track_out.meter_signature == 3
    assert track_out._base_chords == track_in._base_chords
    assert track_out._chord_times == [0.5, 2.0, 4.0]


def test_load_from_file_propagates_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        ChordData(filename=str(tmp_path / "nonexistent.json"))
