"""Stem chord track IDs, metadata and JSON-only freshness."""

import copy

import pytest

from chordflask_base import (
    ChordData,
    DEMUCS_STEM_NAMES,
    build_stem_chord_metadata,
    stem_chord_track_id,
    stem_chord_track_status,
    stem_from_track_id,
)

SET_ID = "demucs:htdemucs"
MEDIA_SHA = "a" * 64


def _audio_set():
    tracks = {}
    for index, stem in enumerate(DEMUCS_STEM_NAMES):
        tracks[stem] = {
            "path": f".chordflask/stems/demucs/htdemucs/song/generation/{stem}.flac",
            "format": "flac",
            "sample_rate": 44100,
            "channels": 2,
            "sample_count": 44100,
            "duration": 1.0,
            "size": 100 + index,
            "sha256": f"{index + 1:064x}",
        }
    return {
        "provider": "demucs",
        "model": "htdemucs",
        "tracks": tracks,
        "metadata": {
            "source": {
                "sha256": MEDIA_SHA,
                "size": 1000,
                "sample_rate": 44100,
                "channels": 2,
                "sample_count": 44100,
                "duration": 1.0,
            },
            "sync": {
                "reference": "canonical_extracted_audio",
                "start_sample": 0,
                "source_sample_count": 44100,
                "stem_sample_count": 44100,
                "max_tail_delta_samples": 2205,
                "tail_adjustment_samples": {stem: 0 for stem in DEMUCS_STEM_NAMES},
            },
            "source_timeline": {"available": False},
        },
    }


def _data(*, audio_set=None, with_audio=True, chordino_source=None):
    data = ChordData()
    source = {"sha256": MEDIA_SHA, "size": 1000}
    data.set_chord_track(
        "chordino",
        [{"timestamp": 0.0, "chord": "C"}],
        metadata={"source_media": chordino_source or source},
    )
    data.set_rhythm_track(
        "qm_barbeattracker", bpm=120, meter_signature=4,
        beat_times=[0.0, 0.5], beat_numbers=[1, 2],
    )
    registered = _audio_set()
    if with_audio:
        data.set_audio_track(SET_ID, audio_set or registered)
    other = registered["tracks"]["other"]
    data.set_chord_track(
        "chordino_stem_other",
        [{"timestamp": 0.0, "chord": "Am"}],
        metadata=build_stem_chord_metadata(
            stem="other", set_id=SET_ID, stem_entry=other,
            set_source_sha256=MEDIA_SHA, source_media=source,
        ),
    )
    data.set_chord_track("btc", [{"timestamp": 0.0, "chord": "Dm"}])
    return data


def test_track_id_roundtrip():
    assert stem_chord_track_id("other") == "chordino_stem_other"
    assert stem_from_track_id("chordino_stem_other") == "other"
    assert stem_from_track_id("chordino") is None
    assert stem_from_track_id("chordino_stem_") is None


@pytest.mark.parametrize("bad", ["", "Other", "../x", "a b", "a-b", None])
def test_track_id_rejects_unsafe_stem(bad):
    with pytest.raises(ValueError):
        stem_chord_track_id(bad)


def test_metadata_shape():
    meta = build_stem_chord_metadata(
        stem="other", set_id=SET_ID,
        stem_entry={"sha256": "b" * 64, "size": 7}, set_source_sha256=MEDIA_SHA,
        source_media={"sha256": MEDIA_SHA, "size": 9},
    )
    assert meta["display_name"] == "Chordino · Other stem"
    assert meta["engine"] == "chordino"
    assert meta["audio_source"] == {
        "kind": "stem", "set_id": SET_ID, "stem": "other",
        "stem_sha256": "b" * 64, "stem_size": 7, "set_source_sha256": MEDIA_SHA,
    }
    assert meta["source_media"] == {"sha256": MEDIA_SHA, "size": 9}
    assert meta["timeline"] == {"reference": "original", "offset_seconds": 0.0}


def test_metadata_omits_unknown_source_media():
    meta = build_stem_chord_metadata(
        stem="other", set_id=SET_ID, stem_entry={"sha256": "b" * 64, "size": 7},
        set_source_sha256=MEDIA_SHA, source_media=None,
    )
    assert "source_media" not in meta


def test_status_current():
    assert stem_chord_track_status(_data(), "chordino_stem_other") == "current"


def test_status_stale_when_stem_regenerated():
    regenerated = _audio_set()
    regenerated["tracks"]["other"]["sha256"] = "f" * 64
    data = _data(audio_set=regenerated)
    assert stem_chord_track_status(data, "chordino_stem_other") == "stale"


def test_status_stale_when_set_source_changes():
    changed = _audio_set()
    changed["metadata"]["source"]["sha256"] = "e" * 64
    data = _data(audio_set=changed)
    assert stem_chord_track_status(data, "chordino_stem_other") == "stale"


def test_status_stale_when_chordino_source_changes():
    data = _data(chordino_source={"sha256": "d" * 64, "size": 1000})
    assert stem_chord_track_status(data, "chordino_stem_other") == "stale"


def test_status_current_when_chordino_has_no_source_identity():
    data = _data()
    data.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "C"}], metadata={})
    assert stem_chord_track_status(data, "chordino_stem_other") == "current"


def test_status_stems_missing_without_audio_set():
    data = _data(with_audio=False)
    assert stem_chord_track_status(data, "chordino_stem_other") == "stems_missing"


def test_status_stale_for_malformed_audio_source():
    data = _data()
    metadata = copy.deepcopy(data.chord_track_metadata("chordino_stem_other"))
    metadata["audio_source"]["stem"] = 42
    data.set_chord_track("chordino_stem_other", [{"timestamp": 0.0, "chord": "Am"}], metadata=metadata)
    assert stem_chord_track_status(data, "chordino_stem_other") == "stale"


@pytest.mark.parametrize("track_id", ["chordino", "btc", "missing"])
def test_status_none_for_non_stem_track(track_id):
    assert stem_chord_track_status(_data(), track_id) is None
