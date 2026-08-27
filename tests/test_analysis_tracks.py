import json
import os
from pathlib import Path

import pytest


from chordflask_base import ChordData, ChordTrackRepository


# ── helpers ───────────────────────────────────────────────────────────

def _v1_fixture(chords=None, bpm=None, meter=None, beat_times=None,
                beat_indexes=None, beat_numbers=None):
    return {
        "schema_version": 1,
        "base_chords": chords or [{"timestamp": 0.0, "chord": "C"}],
        "prefer_flats": True,
        "transpose": 0,
        "bpm": bpm,
        "meter_signature": meter,
        "beat_times": beat_times or [],
        "beat_chord_indexes": beat_indexes or [],
        "beat_numbers": beat_numbers or [],
    }


def _v2_fixture(chords=None, bpm=None, meter=None, beat_times=None,
                beat_indexes=None, beat_numbers=None):
    data = _v1_fixture(chords, bpm, meter, beat_times, beat_indexes, beat_numbers)
    data["schema_version"] = 2
    return data


def _v3_fixture(chord_tracks=None, rhythm_tracks=None, **extra):
    data = {
        "schema_version": 3,
        "prefer_flats": True,
        "transpose": 0,
        "user_data": {},
        "chord_tracks": chord_tracks if chord_tracks is not None else {},
        "rhythm_tracks": rhythm_tracks if rhythm_tracks is not None else {},
    }
    data.update(extra)
    return data


def _write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _load_track(json_path):
    return ChordTrackRepository().load(str(json_path))


# ── legacy migration ──────────────────────────────────────────────────


def test_v1_legacy_migrates_to_chordino_and_qm(tmp_path):
    path = _write_json(tmp_path / "v1.json", _v1_fixture(
        chords=[{"timestamp": 0.0, "chord": "C"}, {"timestamp": 1.0, "chord": "G"}],
        bpm=120, meter=4, beat_times=[0.0, 0.5, 1.0],
        beat_indexes=[0, 0, 1], beat_numbers=[1, 2, 3],
    ))

    track = _load_track(path)

    assert track.active_chord_track_id == "chordino"
    assert track.active_rhythm_track_id == "qm_barbeattracker"
    assert track.bpm == 120
    assert track.meter_signature == 4
    assert len(track.chord_track_chords("chordino")) == 2
    assert track.beat_times == [0.0, 0.5, 1.0]
    assert track.beat_numbers == [1, 2, 3]


def test_v2_legacy_migrates_to_chordino_and_qm(tmp_path):
    path = _write_json(tmp_path / "v2.json", _v2_fixture(
        chords=[{"timestamp": 0.0, "chord": "Dm"}],
        bpm=98, meter=3,
        beat_times=[0.0, 1.0, 2.0], beat_indexes=[0, 0, 0],
    ))

    track = _load_track(path)
    assert track.active_chord_track_id == "chordino"
    assert track.active_rhythm_track_id == "qm_barbeattracker"
    assert track.bpm == 98
    assert track.meter_signature == 3


def test_unversioned_migrates_like_legacy(tmp_path):
    data = _v1_fixture()
    del data["schema_version"]
    path = _write_json(tmp_path / "no_version.json", data)

    track = _load_track(path)
    assert track.active_chord_track_id == "chordino"
    assert track.active_rhythm_track_id == "qm_barbeattracker"


def test_legacy_beat_times_do_not_require_persisted_chord_indexes(tmp_path):
    data = _v1_fixture(beat_times=[0.0, 0.5])
    del data["beat_chord_indexes"]
    path = _write_json(tmp_path / "no_indexes.json", data)

    track = _load_track(path)

    assert track.beat_times == [0.0, 0.5]
    assert track.beat_chord_indexes == [0, 0]


@pytest.mark.parametrize("missing_key", ["chord_tracks", "rhythm_tracks"])
def test_v3_requires_both_track_maps(tmp_path, missing_key):
    data = _v3_fixture()
    del data[missing_key]
    path = _write_json(tmp_path / "missing_map.json", data)

    with pytest.raises(ValueError, match=f'must contain "{missing_key}"'):
        _load_track(path)


def test_legacy_load_does_not_rewrite_file(tmp_path):
    data = _v1_fixture()
    path = _write_json(tmp_path / "v1.json", data)
    original = path.read_text()
    _load_track(path)
    assert path.read_text() == original


def test_v3_load_roundtrips_track_ids(tmp_path):
    path = _write_json(tmp_path / "v3.json", _v3_fixture(
        chord_tracks={
            "chordino": {"chords": [{"timestamp": 0.0, "chord": "A"}], "metadata": {"model": "vamp"}},
        },
        rhythm_tracks={
            "qm_barbeattracker": {"bpm": 100, "meter_signature": 4, "beat_times": [0.0], "beat_numbers": [1], "metadata": {}},
        },
    ))

    track = _load_track(path)
    assert track.active_chord_track_id == "chordino"
    assert track.active_rhythm_track_id == "qm_barbeattracker"
    assert track.chord_track_metadata("chordino") == {"model": "vamp"}


def test_v3_loads_existing_btc_track(tmp_path):
    path = _write_json(tmp_path / "btc.json", _v3_fixture(
        chord_tracks={
            "btc": {"chords": [{"timestamp": 0.0, "chord": "C:maj"}], "metadata": {"engine": "BTC"}},
        },
        rhythm_tracks={},
    ))

    track = _load_track(path)
    assert "btc" in track.available_chord_track_ids
    assert track.chord_track_metadata("btc") == {"engine": "BTC"}


def test_v3_empty_rhythm_tracks_roundtrip_stays_empty(tmp_path):
    path = _write_json(tmp_path / "empty_rhythm.json", _v3_fixture(
        chord_tracks={
            "chordino": {"chords": [{"timestamp": 0.0, "chord": "C"}], "metadata": {}},
        },
        rhythm_tracks={},
    ))

    track = _load_track(path)
    out = tmp_path / "out.json"
    track.save_to_file(str(out))

    raw = json.loads(Path(out).read_text())
    assert raw["rhythm_tracks"] == {}


def test_v3_save_does_not_persist_beat_chord_indexes(tmp_path):
    track = ChordData()
    track.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "A"}])
    track.set_rhythm_track("qm_barbeattracker", bpm=120, beat_times=[0.0, 1.0])
    path = str(tmp_path / "out.json")
    track.save_to_file(path)

    raw = json.loads(Path(path).read_text())
    assert raw["schema_version"] == 3
    assert "beat_chord_indexes" not in raw


# ── save writes v3 ────────────────────────────────────────────────────


def test_save_writes_v3_structure(tmp_path):
    track = ChordData()
    track.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "C"}])
    track.set_rhythm_track("qm_barbeattracker", bpm=120, beat_times=[0.0, 0.5])
    path = str(tmp_path / "v3.json")
    track.save_to_file(path)

    raw = json.loads(Path(path).read_text())
    assert raw["schema_version"] == 3
    assert "chord_tracks" in raw
    assert "rhythm_tracks" in raw
    assert "chordino" in raw["chord_tracks"]
    assert raw["chord_tracks"]["chordino"]["chords"][0]["chord"] == "C"


def test_save_roundtrip_preserves_foreign_tracks(tmp_path):
    track = ChordData()
    track.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "C"}])
    track.set_chord_track("pytorch", [{"timestamp": 0.0, "chord": "D"}],
                          metadata={"framework": "torch"})
    track.set_rhythm_track("qm_barbeattracker", bpm=120, beat_times=[0.0])
    track.set_rhythm_track("custom", bpm=100, beat_times=[0.0, 1.0])
    path = str(tmp_path / "out.json")
    track.save_to_file(path)

    loaded = _load_track(path)
    assert "chordino" in loaded.available_chord_track_ids
    assert "pytorch" in loaded.available_chord_track_ids
    assert loaded.chord_track_metadata("pytorch") == {"framework": "torch"}
    assert "madmom" not in loaded.available_chord_track_ids
    assert "qm_barbeattracker" in loaded.available_rhythm_track_ids
    assert "custom" in loaded.available_rhythm_track_ids


def test_save_roundtrip_preserves_user_data_transpose_prefer_flats(tmp_path):
    track = ChordData()
    track.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "C"}])
    track.set_rhythm_track("qm_barbeattracker", bpm=120, beat_times=[0.0])
    track.transpose(3)
    track.set_prefer_flats(False)
    track.user_data = {"key": "value"}
    path = str(tmp_path / "out.json")
    track.save_to_file(path)

    loaded = _load_track(path)
    assert loaded.transpose_semitones == 3
    assert loaded.prefer_flats is False
    assert loaded.user_data == {"key": "value"}


# ── track selection ───────────────────────────────────────────────────


def test_default_active_chord_is_chordino_then_first(tmp_path):
    path = _write_json(tmp_path / "v3.json", _v3_fixture(
        chord_tracks={
            "custom": {"chords": [{"timestamp": 0.0, "chord": "A"}], "metadata": {}},
            "chordino": {"chords": [{"timestamp": 0.0, "chord": "B"}], "metadata": {}},
            "another": {"chords": [{"timestamp": 0.0, "chord": "C"}], "metadata": {}},
        },
    ))
    track = _load_track(path)
    assert track.active_chord_track_id == "chordino"


def test_named_defaults_win_when_added_after_foreign_tracks():
    track = ChordData()
    track.set_chord_track("pytorch", [{"timestamp": 0.0, "chord": "A"}])
    track.set_rhythm_track("pytorch", bpm=90, beat_times=[0.0])

    track.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "C"}])
    track.set_rhythm_track("qm_barbeattracker", bpm=120, beat_times=[0.0])

    assert track.active_chord_track_id == "chordino"
    assert track.active_rhythm_track_id == "qm_barbeattracker"


def test_adding_named_default_does_not_override_explicit_selection():
    track = ChordData()
    track.set_chord_track("pytorch", [{"timestamp": 0.0, "chord": "A"}])
    track.set_rhythm_track("pytorch", bpm=90, beat_times=[0.0])
    track.select_chord_track("pytorch")
    track.select_rhythm_track("pytorch")

    track.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "C"}])
    track.set_rhythm_track("qm_barbeattracker", bpm=120, beat_times=[0.0])

    assert track.active_chord_track_id == "pytorch"
    assert track.active_rhythm_track_id == "pytorch"


def test_select_chord_track_switches_active():
    track = ChordData()
    track.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "C"}])
    track.set_chord_track("madmom", [{"timestamp": 0.0, "chord": "G"}])
    assert track.active_chord_track_id == "chordino"
    assert track.get_chords() == [(0.0, "C")]

    track.select_chord_track("madmom")
    assert track.active_chord_track_id == "madmom"
    assert track.get_chords() == [(0.0, "G")]


def test_select_rhythm_track_switches_active():
    track = ChordData()
    track.set_rhythm_track("qm_barbeattracker", bpm=120, beat_times=[0.0, 0.5])
    track.set_rhythm_track("manual", bpm=90, beat_times=[0.0, 0.67])
    assert track.active_rhythm_track_id == "qm_barbeattracker"
    assert track.bpm == 120

    track.select_rhythm_track("manual")
    assert track.active_rhythm_track_id == "manual"
    assert track.bpm == 90
    assert track.beat_times == [0.0, 0.67]


def test_available_track_ids():
    track = ChordData()
    track.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "C"}])
    track.set_chord_track("madmom", [{"timestamp": 0.0, "chord": "D"}])
    track.set_rhythm_track("qm_barbeattracker", bpm=120, beat_times=[0.0])
    track.set_rhythm_track("librosa", bpm=100, beat_times=[0.0])

    chord_ids = track.available_chord_track_ids
    assert chord_ids[0] == "chordino"
    assert "madmom" in chord_ids

    rhythm_ids = track.available_rhythm_track_ids
    assert rhythm_ids[0] == "qm_barbeattracker"
    assert "librosa" in rhythm_ids


def test_select_unknown_track_raises():
    track = ChordData()
    track.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "C"}])
    with pytest.raises(ValueError, match="not available"):
        track.select_chord_track("nonexistent")


# ── compatibility API ─────────────────────────────────────────────────


def test_set_base_chords_is_chordino_compat_path():
    track = ChordData()
    track.set_base_chords([{"timestamp": 0.0, "chord": "Am"}])
    assert track.active_chord_track_id == "chordino"
    assert track.get_chords() == [(0.0, "Am")]


def test_bpm_property_after_set_base_chords_preserved():
    track = ChordData()
    track.bpm = 140
    track.set_base_chords([{"timestamp": 0.0, "chord": "G"}])
    assert track.bpm == 140


def test_get_chords_per_beat_recomputes_on_track_switch():
    track = ChordData()
    track.set_chord_track("chordino", [
        {"timestamp": 0.0, "chord": "C"}, {"timestamp": 2.0, "chord": "G"}
    ])
    track.set_rhythm_track("qm_barbeattracker", bpm=120, beat_times=[0.0, 1.0, 2.0],
                           beat_numbers=[1, 2, 3])

    assert track.get_chords_per_beat() == [(0.0, "C"), (1.0, "C"), (2.0, "G")]

    track.select_chord_track("chordino")
    assert track.get_chords_per_beat() == [(0.0, "C"), (1.0, "C"), (2.0, "G")]


# ── v3 validation ─────────────────────────────────────────────────────


def test_v3_rejects_non_dict_chord_tracks(tmp_path):
    data = _v3_fixture(chord_tracks="not_a_dict")
    path = _write_json(tmp_path / "bad.json", data)
    with pytest.raises(ValueError, match="chord_tracks must be an object"):
        _load_track(path)


def test_v3_rejects_empty_track_id(tmp_path):
    data = _v3_fixture(chord_tracks={"": {"chords": [], "metadata": {}}})
    path = _write_json(tmp_path / "bad.json", data)
    with pytest.raises(ValueError, match="chord_tracks key must be a non-empty string"):
        _load_track(path)


def test_v3_rejects_non_dict_track_entry(tmp_path):
    data = _v3_fixture(chord_tracks={"x": "not_an_object"})
    path = _write_json(tmp_path / "bad.json", data)
    with pytest.raises(ValueError, match="chord_tracks"):
        _load_track(path)


def test_v3_rejects_non_dict_rhythm_tracks(tmp_path):
    data = _v3_fixture(rhythm_tracks=[])
    path = _write_json(tmp_path / "bad.json", data)
    with pytest.raises(ValueError, match="rhythm_tracks must be an object"):
        _load_track(path)


def test_v3_rejects_rhythm_non_dict_entry(tmp_path):
    data = _v3_fixture(rhythm_tracks={"x": "bad"})
    path = _write_json(tmp_path / "bad.json", data)
    with pytest.raises(ValueError, match="rhythm_tracks"):
        _load_track(path)


def test_v3_rejects_negative_timestamp_in_chord_track(tmp_path):
    data = _v3_fixture(chord_tracks={
        "chordino": {"chords": [{"timestamp": -1.0, "chord": "C"}], "metadata": {}},
    })
    path = _write_json(tmp_path / "bad.json", data)
    with pytest.raises(ValueError, match="negative timestamp"):
        _load_track(path)


def test_v3_rejects_non_finite_rhythm_values(tmp_path):
    data = _v3_fixture(rhythm_tracks={
        "qm_barbeattracker": {
            "bpm": float("inf"), "meter_signature": 4,
            "beat_times": [0.0], "beat_numbers": [1], "metadata": {},
        },
    })
    path = _write_json(tmp_path / "bad.json", data)
    with pytest.raises(ValueError, match="bpm must be positive"):
        _load_track(path)


def test_v3_preserves_unknown_metadata(tmp_path):
    data = _v3_fixture(
        chord_tracks={
            "chordino": {
                "chords": [{"timestamp": 0.0, "chord": "C"}],
                "metadata": {"confidence": 0.95, "extra": [1, 2, 3]},
            },
        },
        rhythm_tracks={
            "qm_barbeattracker": {
                "bpm": 120, "meter_signature": 4,
                "beat_times": [0.0], "beat_numbers": [1],
                "metadata": {"analyzer": "librosa"},
            },
        },
    )
    path = _write_json(tmp_path / "v3.json", data)
    track = _load_track(path)
    assert track.chord_track_metadata("chordino") == {"confidence": 0.95, "extra": [1, 2, 3]}
    assert track.rhythm_track_metadata("qm_barbeattracker") == {"analyzer": "librosa"}


# ── atomic roundtrip ──────────────────────────────────────────────────


def test_v3_atomic_save_no_tmp_leftover(tmp_path):
    track = ChordData()
    track.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "A"}])
    track.set_rhythm_track("qm_barbeattracker", bpm=120, beat_times=[0.0])
    json_path = str(tmp_path / "out.json")
    track.save_to_file(json_path)
    assert not os.path.exists(json_path + ".tmp")
    assert os.path.exists(json_path)


# ── empty tracks rejection ────────────────────────────────────────────


def test_set_chord_track_with_empty_id_raises():
    track = ChordData()
    with pytest.raises(ValueError, match="non-empty string"):
        track.set_chord_track("", [{"timestamp": 0.0, "chord": "C"}])


def test_set_rhythm_track_with_empty_id_raises():
    track = ChordData()
    with pytest.raises(ValueError, match="non-empty string"):
        track.set_rhythm_track("", bpm=120)


# ── setter validation ──────────────────────────────────────────────────


def test_set_chord_track_rejects_non_list_chords():
    track = ChordData()
    with pytest.raises(ValueError, match="chords must be a list"):
        track.set_chord_track("x", "not_a_list")


def test_set_chord_track_rejects_invalid_entry():
    track = ChordData()
    with pytest.raises(ValueError, match="invalid or negative timestamp"):
        track.set_chord_track("x", [{"timestamp": -1, "chord": "C"}])


def test_set_chord_track_rejects_non_finite_timestamp():
    track = ChordData()
    with pytest.raises(ValueError, match="invalid or negative timestamp"):
        track.set_chord_track("x", [{"timestamp": float("nan"), "chord": "C"}])


def test_set_chord_track_rejects_empty_chord_label():
    track = ChordData()
    with pytest.raises(ValueError, match="empty or missing chord"):
        track.set_chord_track("x", [{"timestamp": 0.0, "chord": ""}])


def test_set_chord_track_metadata_none_becomes_empty_dict():
    track = ChordData()
    track.set_chord_track("x", [{"timestamp": 0.0, "chord": "C"}], metadata=None)
    assert track.chord_track_metadata("x") == {}


def test_track_read_apis_return_isolated_copies():
    track = ChordData()
    track.set_chord_track(
        "x", [{"timestamp": 0.0, "chord": "C"}], metadata={"model": "one"}
    )
    track.set_rhythm_track(
        "y", bpm=120, beat_times=[0.0], metadata={"model": "two"}
    )

    chords = track.chord_track_chords("x")
    rhythm = track.rhythm_track_data("y")
    chord_metadata = track.chord_track_metadata("x")
    chords[0]["chord"] = "G"
    rhythm["beat_times"].append(1.0)
    chord_metadata["model"] = "changed"

    assert track.chord_track_chords("x") == [{"timestamp": 0.0, "chord": "C"}]
    assert track.rhythm_track_data("y")["beat_times"] == [0.0]
    assert track.chord_track_metadata("x") == {"model": "one"}


def test_set_chord_track_rejects_non_dict_metadata():
    track = ChordData()
    with pytest.raises(ValueError, match="metadata must be an object"):
        track.set_chord_track("x", [{"timestamp": 0.0, "chord": "C"}], metadata=[])


def test_set_rhythm_track_rejects_negative_bpm():
    track = ChordData()
    with pytest.raises(ValueError, match="bpm must be a positive finite number"):
        track.set_rhythm_track("x", bpm=-1)


def test_set_rhythm_track_rejects_non_integer_meter():
    track = ChordData()
    with pytest.raises(ValueError, match="meter_signature must be a positive integer"):
        track.set_rhythm_track("x", bpm=120, meter_signature="4/4")


def test_set_rhythm_track_metadata_none_becomes_empty_dict():
    track = ChordData()
    track.set_rhythm_track("x", bpm=120, metadata=None)
    assert track.rhythm_track_metadata("x") == {}


# ── v3 requires fields ─────────────────────────────────────────────────


def test_v3_rejects_chord_track_missing_chords(tmp_path):
    data = _v3_fixture(chord_tracks={"x": {}})
    path = _write_json(tmp_path / "bad.json", data)
    with pytest.raises(ValueError, match='must contain "chords"'):
        _load_track(path)


def test_v3_rejects_rhythm_track_missing_bpm(tmp_path):
    data = _v3_fixture(rhythm_tracks={
        "x": {"meter_signature": 4, "beat_times": [], "beat_numbers": []},
    })
    path = _write_json(tmp_path / "bad.json", data)
    with pytest.raises(ValueError, match='must contain "bpm"'):
        _load_track(path)


def test_v3_accepts_null_bpm_and_meter(tmp_path):
    data = _v3_fixture(
        chord_tracks={"chordino": {"chords": [{"timestamp": 0.0, "chord": "C"}], "metadata": {}}},
        rhythm_tracks={
            "qm_barbeattracker": {
                "bpm": None, "meter_signature": None,
                "beat_times": [], "beat_numbers": [], "metadata": {},
            },
        },
    )
    path = _write_json(tmp_path / "ok.json", data)
    track = _load_track(path)
    assert track.bpm is None
    assert track.meter_signature is None


# ── player track state and selection ───────────────────────────────────


def test_player_analysis_track_state(tmp_path):
    from chordflask.mp4playerflask import MP4PlayerFlask
    from chordflask.filerepr import FileRepr

    media = tmp_path / "song.mp4"
    media.write_bytes(b"not used")
    json_dir = tmp_path / ".chordflask"
    json_dir.mkdir()
    track = ChordData()
    track.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "C"}])
    track.set_chord_track(
        "custom",
        [{"timestamp": 0.0, "chord": "G"}],
        metadata={"display_name": " My Analyzer "},
    )
    track.set_chord_track(
        "fallback", [{"timestamp": 0.0, "chord": "F"}],
        metadata={"display_name": ["not", "text"]},
    )
    track.set_rhythm_track("qm_barbeattracker", bpm=120, beat_times=[0.0])
    track.save_to_file(str(json_dir / "song.json"))

    fr = FileRepr(str(media), datapath=str(json_dir))
    player = MP4PlayerFlask(fr)
    state = player.analysis_track_state()
    assert state["active_chord_track_id"] == "chordino"
    assert state["active_rhythm_track_id"] == "qm_barbeattracker"
    names = {
        item["id"]: item["display_name"]
        for item in state["available_chord_tracks"]
    }
    assert names == {
        "chordino": "Chordino",
        "custom": "My Analyzer",
        "fallback": "fallback",
    }


def test_player_select_analysis_tracks_soft_fallback(tmp_path):
    from chordflask.mp4playerflask import MP4PlayerFlask
    from chordflask.filerepr import FileRepr

    media = tmp_path / "song.mp4"
    media.write_bytes(b"not used")
    json_dir = tmp_path / ".chordflask"
    json_dir.mkdir()
    track = ChordData()
    track.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "C"}])
    track.set_rhythm_track("qm_barbeattracker", bpm=120, beat_times=[0.0])
    track.save_to_file(str(json_dir / "song.json"))

    fr = FileRepr(str(media), datapath=str(json_dir))
    player = MP4PlayerFlask(fr)
    player.select_analysis_tracks(chord_track_id="nonexistent", soft_fallback=True)
    assert player.chord_data.active_chord_track_id == "chordino"


def test_player_select_analysis_tracks_strict_raises(tmp_path):
    from chordflask.mp4playerflask import MP4PlayerFlask
    from chordflask.filerepr import FileRepr

    media = tmp_path / "song.mp4"
    media.write_bytes(b"not used")
    json_dir = tmp_path / ".chordflask"
    json_dir.mkdir()
    track = ChordData()
    track.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "C"}])
    track.set_rhythm_track("qm_barbeattracker", bpm=120, beat_times=[0.0])
    track.save_to_file(str(json_dir / "song.json"))

    fr = FileRepr(str(media), datapath=str(json_dir))
    player = MP4PlayerFlask(fr)
    with pytest.raises(ValueError, match="not available"):
        player.select_analysis_tracks(chord_track_id="nonexistent", soft_fallback=False)


# ── legacy API save/reload roundtrip ────────────────────────────────────


def test_legacy_setters_survive_save_reload(tmp_path):
    track = ChordData()
    track.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "C"}])
    track.set_rhythm_track("qm_barbeattracker", bpm=120, beat_times=[0.0])
    track.bpm = 90
    track.meter_signature = 3
    track.set_beats([0.0, 0.667, 1.333])
    track.set_beat_numbers([1, 2, 3])
    track.user_data = {"mood": "happy"}
    path = str(tmp_path / "out.json")
    track.save_to_file(path)

    loaded = _load_track(path)
    assert loaded.bpm == 90
    assert loaded.meter_signature == 3
    assert loaded.beat_times == [0.0, 0.667, 1.333]
    assert loaded.beat_numbers == [1, 2, 3]
    assert loaded.user_data == {"mood": "happy"}


def test_set_base_chords_beat_times_survives_save_reload(tmp_path):
    track = ChordData()
    track.set_base_chords(
        [{"timestamp": 0.0, "chord": "C"}, {"timestamp": 2.0, "chord": "G"}],
        beat_times=[0.0, 1.0, 2.0, 3.0],
    )
    path = str(tmp_path / "out.json")
    track.save_to_file(path)

    loaded = _load_track(path)
    assert loaded.get_chords() == [(0.0, "C"), (2.0, "G")]
    assert loaded.beat_times == [0.0, 1.0, 2.0, 3.0]


def test_load_v3_clears_stale_dimension(tmp_path):
    data = _v3_fixture(
        chord_tracks={
            "chordino": {"chords": [{"timestamp": 0.0, "chord": "C"}], "metadata": {}},
        },
    )
    path = _write_json(tmp_path / "only_chords.json", data)
    track = ChordData()
    track.set_rhythm_track("stale", bpm=99, beat_times=[0.0])
    track.load_from_file(path)
    assert track.active_chord_track_id == "chordino"
    assert track.bpm is None
    assert track.beat_times == []
    assert track.available_rhythm_track_ids == []


# ── centralized default track identifiers ────────────────────────────


def test_default_track_identifiers_are_centralized():
    import chordflask_base.model as chorddata

    assert chorddata.DEFAULT_CHORD_TRACK == "chordino"
    assert chorddata.DEFAULT_RHYTHM_TRACK == "qm_barbeattracker"


def test_chord_default_selection_uses_configured_identity(monkeypatch):
    import chordflask_base.model as chorddata

    track = ChordData()
    monkeypatch.setattr(chorddata, "DEFAULT_CHORD_TRACK", "my-engine")

    track.set_chord_track("other", [{"timestamp": 0.0, "chord": "C"}])
    assert track.active_chord_track_id == "other"

    track.set_chord_track("my-engine", [{"timestamp": 0.0, "chord": "G"}])
    assert track.active_chord_track_id == "my-engine"
    assert track.available_chord_track_ids[0] == "my-engine"


def test_rhythm_default_selection_uses_configured_identity(monkeypatch):
    import chordflask_base.model as chorddata

    track = ChordData()
    monkeypatch.setattr(chorddata, "DEFAULT_RHYTHM_TRACK", "my-rhythm")

    track.set_rhythm_track(
        "other-rhythm", bpm=120, meter_signature=4,
        beat_times=[0.0, 0.5], beat_numbers=[1, 2],
    )
    assert track.active_rhythm_track_id == "other-rhythm"

    track.set_rhythm_track(
        "my-rhythm", bpm=100, meter_signature=4,
        beat_times=[0.0, 0.6], beat_numbers=[1, 2],
    )
    assert track.active_rhythm_track_id == "my-rhythm"
    assert track.available_rhythm_track_ids[0] == "my-rhythm"
