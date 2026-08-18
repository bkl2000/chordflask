import copy
import json

import pytest

from chordflask_base import ChordData, ChordTrackRepository


def _audio_set():
    return {
        "provider": "demucs",
        "model": "htdemucs",
        "tracks": {
            stem: {
                "path": f".chordflask/stems/demucs/htdemucs/song/generation/{stem}.flac",
                "format": "flac",
                "sample_rate": 44100,
                "channels": 2,
                "sample_count": 44100,
                "duration": 1.0,
                "size": 100 + index,
                "sha256": f"{index + 1:064x}",
            }
            for index, stem in enumerate(("bass", "drums", "other", "vocals"))
        },
        "metadata": {
            "source": {
                "sha256": "a" * 64,
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
                "tail_adjustment_samples": {
                    "bass": 0,
                    "drums": 0,
                    "other": 0,
                    "vocals": 0,
                },
            },
            "source_timeline": {"available": False},
        },
    }


def test_audio_track_set_roundtrips_as_one_id(tmp_path):
    data = ChordData()
    data.set_audio_track("demucs:htdemucs", _audio_set())
    path = tmp_path / "song.json"

    ChordTrackRepository().save(data, path)
    loaded = ChordTrackRepository().load(path)

    assert loaded.available_audio_track_ids == ["demucs:htdemucs"]
    assert loaded.has_audio_track("demucs:htdemucs")
    assert loaded.audio_track_data("demucs:htdemucs") == _audio_set()


def test_audio_track_set_data_is_deep_copied():
    original = _audio_set()
    data = ChordData()
    data.set_audio_track("demucs:htdemucs", original)
    original["tracks"]["vocals"]["path"] = "changed"

    returned = data.audio_track_data("demucs:htdemucs")
    returned["metadata"]["source"]["size"] = 2

    assert data.audio_track_data("demucs:htdemucs")["tracks"]["vocals"]["path"].endswith("/vocals.flac")
    assert data.audio_track_data("demucs:htdemucs")["metadata"]["source"]["size"] == 1000


def test_incomplete_audio_set_rejected_without_partial_mutation():
    data = ChordData()
    valid = _audio_set()
    data.set_audio_track("demucs:htdemucs", valid)
    invalid = copy.deepcopy(valid)
    del invalid["tracks"]["vocals"]

    with pytest.raises(ValueError, match="exactly"):
        data.set_audio_track("demucs:htdemucs", invalid)

    assert data.audio_track_data("demucs:htdemucs") == valid


def test_v3_without_audio_tracks_remains_valid_and_saves_empty_map(tmp_path):
    path = tmp_path / "song.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "prefer_flats": True,
                "transpose": 0,
                "user_data": {},
                "chord_tracks": {},
                "rhythm_tracks": {},
            }
        ),
        encoding="utf-8",
    )

    loaded = ChordTrackRepository().load(path)
    ChordTrackRepository().save(loaded, path)

    assert json.loads(path.read_text(encoding="utf-8"))["audio_tracks"] == {}


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("provider", "", "provider"),
        ("model", "", "model"),
        ("metadata", {}, "metadata.source"),
    ],
)
def test_audio_set_required_fields_are_validated(field, value, message):
    data = _audio_set()
    data[field] = value

    with pytest.raises(ValueError, match=message):
        ChordData().set_audio_track("demucs:htdemucs", data)
