"""Tests for BTC batch discovery, classification, planning, and execution."""

import json
import stat
from pathlib import Path

import pytest

from chordflask_btc.batch import (
    CLASS_CURRENT,
    CLASS_NO_ANALYSIS,
    CLASS_STALE,
    CLASS_TODO,
    classify_btc_file,
    plan_btc_batch,
    run_btc_batch,
)
from chordflask_btc.predictor import sha256
from chordflask_btc.discovery import discover_media_directory
from chordflask_btc.schema import ANALYSIS_DIR_NAME, BTC_TRACK_ID


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write_analysis(videos: Path, stem: str, btc_track=None) -> Path:
    data_dir = videos / ANALYSIS_DIR_NAME
    data_dir.mkdir(exist_ok=True)
    analysis = {
        "schema_version": 3,
        "prefer_flats": True,
        "transpose": 0,
        "user_data": {},
        "chord_tracks": {
            "chordino": {"chords": [{"timestamp": 0.0, "chord": "C"}], "metadata": {}}
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
    if btc_track is not None:
        analysis["chord_tracks"][BTC_TRACK_ID] = btc_track
    json_path = data_dir / f"{stem}.json"
    json_path.write_text(json.dumps(analysis), encoding="utf-8")
    return json_path


# ── discovery ────────────────────────────────────────────────────────


def test_discovery_sorts_smallest_first_and_prefers_mp4(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x" * 100)
    (tmp_path / "a.mp3").write_bytes(b"y")
    (tmp_path / "b.webm").write_bytes(b"z" * 50)
    (tmp_path / "b.mp3").write_bytes(b"w")
    (tmp_path / "z.mp3").write_bytes(b"v" * 10)

    names = [p.name for p in discover_media_directory(tmp_path)]
    assert names == ["z.mp3", "b.webm", "a.mp4"]


def test_discovery_same_stem_priority(tmp_path):
    (tmp_path / "song.mp4").write_bytes(b"x" * 10)
    (tmp_path / "song.webm").write_bytes(b"x" * 9)
    (tmp_path / "song.mp3").write_bytes(b"x" * 8)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "nested.mp4").write_bytes(b"x" * 7)

    result = discover_media_directory(tmp_path)
    assert [p.name for p in result] == ["song.mp4"]


def test_discovery_tie_break_by_name(tmp_path):
    (tmp_path / "beta.mp3").write_bytes(b"x" * 5)
    (tmp_path / "alpha.mp3").write_bytes(b"x" * 5)
    (tmp_path / "Aardvark.mp3").write_bytes(b"x" * 5)

    names = [p.name for p in discover_media_directory(tmp_path)]
    assert names == ["Aardvark.mp3", "alpha.mp3", "beta.mp3"]


def test_discovery_unicode_and_spaces(tmp_path):
    (tmp_path / "Café song.mp3").write_bytes(b"x" * 3)
    (tmp_path / "Another song.mp3").write_bytes(b"x" * 4)

    names = [p.name for p in discover_media_directory(tmp_path)]
    assert names == ["Café song.mp3", "Another song.mp3"]


# ── classification ───────────────────────────────────────────────────


def _btc_track(model_hash, media_hash):
    return {
        "chords": [{"timestamp": 0.0, "chord": "C"}],
        "metadata": {"model_sha256": model_hash, "media_sha256": media_hash},
    }


def test_classify_todo(tmp_path):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"m")
    _write_analysis(tmp_path, "song")
    assert classify_btc_file(media, "a" * 64) == (CLASS_TODO, "")


def test_classify_current(tmp_path):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"m")
    media_hash = sha256(media)
    model_hash = "a" * 64
    _write_analysis(tmp_path, "song", _btc_track(model_hash, media_hash))
    assert classify_btc_file(media, model_hash) == (CLASS_CURRENT, "BTC already current")


def test_classify_stale(tmp_path):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"m")
    _write_analysis(tmp_path, "song", _btc_track("a" * 64, "b" * 64))
    assert classify_btc_file(media, "a" * 64) == (CLASS_STALE, "use --replace")


def test_classify_missing_is_todo(tmp_path):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"m")
    assert classify_btc_file(media, "a" * 64) == (CLASS_TODO, "")


def test_classify_corrupt_analysis_is_no_analysis(tmp_path):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"m")
    (tmp_path / ANALYSIS_DIR_NAME).mkdir()
    (tmp_path / ANALYSIS_DIR_NAME / "song.json").write_text("{bad", encoding="utf-8")
    classification, reason = classify_btc_file(media, "a" * 64)
    assert classification == CLASS_NO_ANALYSIS
    assert "invalid ChordFlask analysis" in reason


# ── dry-run + real batch (stubbed runtime) ───────────────────────────


_WRAPPER_OK = "#!/bin/sh\necho '[{\"timestamp\": 0.0, \"chord\": \"N\"}]'\n"


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    btc_dir = tmp_path / "btc"
    btc_dir.mkdir()
    (btc_dir / "predict_raw.py").write_text("# stub\n")
    (btc_dir / "btc_model_large_voca.pt").write_bytes(b"fake-checkpoint")
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").write_text("#!/bin/sh\n")
    _write_executable(venv / "bin" / "btc-predict-raw", _WRAPPER_OK)
    monkeypatch.setenv("CHORDFLASK_BTC_DIR", str(btc_dir))
    monkeypatch.setenv("CHORDFLASK_BTC_VENV", str(venv))

    def _fake_decode(media_path, output_path, **kwargs):
        output_path.write_bytes(b"")

    monkeypatch.setattr(
        "chordflask_btc.predictor.decode_mono_audio", _fake_decode
    )
    return btc_dir, venv


def test_dry_run_has_no_side_effects(tmp_path, runtime):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"m")
    _write_analysis(tmp_path, "song")

    plan = plan_btc_batch(tmp_path)
    assert [item["classification"] for item in plan] == [CLASS_TODO]

    analysis = json.loads(
        (tmp_path / ANALYSIS_DIR_NAME / "song.json").read_text(encoding="utf-8")
    )
    assert BTC_TRACK_ID not in analysis["chord_tracks"]


def test_batch_runs_and_reports(tmp_path, runtime):
    song = tmp_path / "song.mp3"
    song.write_bytes(b"m")
    _write_analysis(tmp_path, "song")
    no_analysis = tmp_path / "other.mp3"
    no_analysis.write_bytes(b"n")

    code = run_btc_batch(tmp_path)

    assert code == 0
    analysis = json.loads(
        (tmp_path / ANALYSIS_DIR_NAME / "song.json").read_text(encoding="utf-8")
    )
    assert BTC_TRACK_ID in analysis["chord_tracks"]


def test_batch_current_with_replace_reprocesses(tmp_path, runtime, capsys):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"m")
    _write_analysis(tmp_path, "song")
    assert run_btc_batch(tmp_path) == 0
    capsys.readouterr()

    code = run_btc_batch(tmp_path, replace=True)

    assert code == 0
    output = capsys.readouterr().out
    assert "processed:   1" in output
    assert "current:     0" in output


def test_batch_creates_btc_for_unanalyzed_file(tmp_path, runtime):
    media = tmp_path / "fresh.mp3"
    media.write_bytes(b"m")

    code = run_btc_batch(tmp_path)

    assert code == 0
    analysis = json.loads(
        (tmp_path / ANALYSIS_DIR_NAME / "fresh.json").read_text(encoding="utf-8")
    )
    assert analysis["schema_version"] == 3
    assert analysis["rhythm_tracks"] == {}
    assert BTC_TRACK_ID in analysis["chord_tracks"]


def test_batch_isolates_failures(tmp_path, monkeypatch):
    btc_dir = tmp_path / "btc"
    btc_dir.mkdir()
    (btc_dir / "predict_raw.py").write_text("# stub\n")
    (btc_dir / "btc_model_large_voca.pt").write_bytes(b"fake-checkpoint")
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").write_text("#!/bin/sh\n")
    _write_executable(venv / "bin" / "btc-predict-raw", _WRAPPER_OK)
    monkeypatch.setenv("CHORDFLASK_BTC_DIR", str(btc_dir))
    monkeypatch.setenv("CHORDFLASK_BTC_VENV", str(venv))

    from chordflask_btc.audio_encoder import AudioAnalysisError

    def _fake_decode(media_path, output_path, **kwargs):
        if "broken" in str(media_path):
            raise AudioAnalysisError("boom")
        output_path.write_bytes(b"")

    monkeypatch.setattr(
        "chordflask_btc.predictor.decode_mono_audio", _fake_decode
    )

    good = tmp_path / "good.mp3"
    good.write_bytes(b"g")
    _write_analysis(tmp_path, "good")
    bad = tmp_path / "broken.mp3"
    bad.write_bytes(b"b")
    _write_analysis(tmp_path, "broken")

    code = run_btc_batch(tmp_path)
    assert code == 1

    good_analysis = json.loads(
        (tmp_path / ANALYSIS_DIR_NAME / "good.json").read_text(encoding="utf-8")
    )
    bad_analysis = json.loads(
        (tmp_path / ANALYSIS_DIR_NAME / "broken.json").read_text(encoding="utf-8")
    )
    assert BTC_TRACK_ID in good_analysis["chord_tracks"]
    assert BTC_TRACK_ID not in bad_analysis["chord_tracks"]
