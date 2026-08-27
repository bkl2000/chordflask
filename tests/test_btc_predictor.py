"""Tests for BTC single-file inference, idempotency, and error handling."""

import json
import stat
from pathlib import Path

import pytest

from chordflask_btc.predictor import BtcPredictionError, predict_btc_media
from chordflask_btc.schema import ANALYSIS_DIR_NAME, BTC_TRACK_ID


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _runtime(tmp_path, wrapper_script, checkpoint=b"fake-checkpoint"):
    btc_dir = tmp_path / "btc"
    btc_dir.mkdir()
    (btc_dir / "predict_raw.py").write_text("# stub\n")
    (btc_dir / "btc_model_large_voca.pt").write_bytes(checkpoint)

    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").write_text("#!/bin/sh\n")
    _write_executable(venv / "bin" / "btc-predict-raw", wrapper_script)
    return btc_dir, venv


def _make_media(tmp_path, stem="song", with_analysis=True, media_bytes=b"media-bytes"):
    videos = tmp_path / "videos"
    videos.mkdir(exist_ok=True)
    media = videos / f"{stem}.mp3"
    media.write_bytes(media_bytes)
    if with_analysis:
        data_dir = videos / ANALYSIS_DIR_NAME
        data_dir.mkdir(exist_ok=True)
        analysis = {
            "schema_version": 3,
            "prefer_flats": True,
            "transpose": 0,
            "user_data": {},
            "chord_tracks": {
                "chordino": {
                    "chords": [{"timestamp": 0.0, "chord": "C"}],
                    "metadata": {},
                }
            },
            "rhythm_tracks": {
                "qm_barbeattracker": {
                    "bpm": 120.0,
                    "meter_signature": 4,
                    "beat_times": [0.0, 0.5, 1.0],
                    "beat_numbers": [1, 2, 3],
                    "metadata": {},
                }
            },
        }
        (data_dir / f"{stem}.json").write_text(json.dumps(analysis), encoding="utf-8")
    return media


_WRAPPER_OK = "#!/bin/sh\necho '[{\"timestamp\": 0.0, \"chord\": \"N\"}, {\"timestamp\": 1.0, \"chord\": \"F#:7\"}]'\n"
_WRAPPER_FAIL = "#!/bin/sh\necho 'boom' >&2\nexit 1\n"


@pytest.fixture
def runtime_ok(tmp_path, monkeypatch):
    btc_dir, venv = _runtime(tmp_path, _WRAPPER_OK)
    monkeypatch.setenv("CHORDFLASK_BTC_DIR", str(btc_dir))
    monkeypatch.setenv("CHORDFLASK_BTC_VENV", str(venv))

    def _fake_decode(media_path, output_path, **kwargs):
        output_path.write_bytes(b"")

    monkeypatch.setattr(
        "chordflask_btc.predictor.decode_mono_audio", _fake_decode
    )
    return btc_dir, venv


def test_predicts_and_writes_btc_track(tmp_path, runtime_ok):
    media = _make_media(tmp_path)
    result = predict_btc_media(media)
    assert result["status"] == "predicted"
    assert result["events"] == 2

    analysis = json.loads(
        (media.parent / ANALYSIS_DIR_NAME / "song.json").read_text(encoding="utf-8")
    )
    track = analysis["chord_tracks"][BTC_TRACK_ID]
    assert [e["chord"] for e in track["chords"]] == ["N", "F#7"]
    assert track["metadata"]["display_name"] == "BTC"
    assert track["metadata"]["engine"] == "BTC-ISMIR19"
    assert track["metadata"]["vocabulary"] == "large-170"
    assert track["metadata"]["experimental"] is True
    assert len(track["metadata"]["model_sha256"]) == 64
    assert len(track["metadata"]["media_sha256"]) == 64
    assert "chordino" in analysis["chord_tracks"]
    assert analysis["rhythm_tracks"]["qm_barbeattracker"]["bpm"] == 120.0


def test_matching_hashes_skip_without_replace_and_rewrite_with_replace(tmp_path, runtime_ok):
    media = _make_media(tmp_path)
    assert predict_btc_media(media)["status"] == "predicted"

    json_path = media.parent / ANALYSIS_DIR_NAME / "song.json"
    analysis = json.loads(json_path.read_text(encoding="utf-8"))
    analysis["chord_tracks"][BTC_TRACK_ID]["chords"] = [
        {"timestamp": 0.0, "chord": "C"}
    ]
    json_path.write_text(json.dumps(analysis), encoding="utf-8")
    before = json_path.read_bytes()

    result = predict_btc_media(media)
    assert result["status"] == "skipped"
    assert result["events"] == 0
    assert json_path.read_bytes() == before

    result = predict_btc_media(media, replace=True)
    assert result == {"status": "predicted", "events": 2}
    rewritten = json.loads(json_path.read_text(encoding="utf-8"))
    assert [event["chord"] for event in rewritten["chord_tracks"][BTC_TRACK_ID]["chords"]] == [
        "N",
        "F#7",
    ]


def test_stale_requires_replace(tmp_path, runtime_ok):
    media = _make_media(tmp_path)
    assert predict_btc_media(media)["status"] == "predicted"

    media.write_bytes(b"different-media-bytes")
    with pytest.raises(BtcPredictionError, match="use --replace"):
        predict_btc_media(media)


def test_stale_with_replace_replaces(tmp_path, runtime_ok):
    media = _make_media(tmp_path)
    predict_btc_media(media)
    media.write_bytes(b"different-media-bytes")

    result = predict_btc_media(media, replace=True)
    assert result["status"] == "predicted"


def test_missing_analysis_creates_btc_file(tmp_path, runtime_ok):
    media = _make_media(tmp_path, with_analysis=False)
    result = predict_btc_media(media)
    assert result["status"] == "predicted"
    assert result["events"] == 2

    json_path = media.parent / ANALYSIS_DIR_NAME / "song.json"
    assert json_path.is_file()
    analysis = json.loads(json_path.read_text(encoding="utf-8"))
    assert analysis["schema_version"] == 3
    assert analysis["rhythm_tracks"] == {}
    assert [e["chord"] for e in analysis["chord_tracks"]["btc"]["chords"]] == ["N", "F#7"]


def test_inference_failure_leaves_json_unchanged(tmp_path, monkeypatch):
    btc_dir, venv = _runtime(tmp_path, _WRAPPER_FAIL)
    monkeypatch.setenv("CHORDFLASK_BTC_DIR", str(btc_dir))
    monkeypatch.setenv("CHORDFLASK_BTC_VENV", str(venv))

    def _fake_decode(media_path, output_path, **kwargs):
        output_path.write_bytes(b"")

    monkeypatch.setattr(
        "chordflask_btc.predictor.decode_mono_audio", _fake_decode
    )
    media = _make_media(tmp_path)

    json_path = media.parent / ANALYSIS_DIR_NAME / "song.json"
    before = json_path.read_bytes()
    with pytest.raises(BtcPredictionError, match="BTC inference failed"):
        predict_btc_media(media)
    assert json_path.read_bytes() == before


def test_missing_runtime_raises_actionable_error(tmp_path, monkeypatch):
    btc_dir = tmp_path / "btc"
    btc_dir.mkdir()
    venv = tmp_path / "venv"
    venv.mkdir()
    monkeypatch.setenv("CHORDFLASK_BTC_DIR", str(btc_dir))
    monkeypatch.setenv("CHORDFLASK_BTC_VENV", str(venv))
    media = _make_media(tmp_path)

    from chordflask_btc.runtime import BtcRuntimeError

    with pytest.raises(BtcRuntimeError, match="make setup-btc"):
        predict_btc_media(media)
