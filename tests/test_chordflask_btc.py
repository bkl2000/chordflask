"""Tests for the public ``chordflask_btc`` package (BTC track + dispatch)."""

import json
from pathlib import Path

import pytest

from chordflask_btc import analyze, schema
from chordflask_btc.runtime import detect_btc_runtime, wrapper_path

REPO_ROOT = Path(__file__).resolve().parents[1]

_COMPLETE_RUNTIME = {
    "venv": "/x/venv",
    "checkpoint": "/x/model/btc_model_large_voca.pt",
    "wrapper": "/x/venv/bin/btc-predict-raw",
    "complete": True,
    "missing": [],
}


# ── schema helpers ────────────────────────────────────────────────────


def _v3_data(**overrides):
    data = {
        "schema_version": 3,
        "prefer_flats": True,
        "transpose": 0,
        "user_data": {"saved_transpose": 2},
        "chord_tracks": {
            "chordino": {"chords": [{"timestamp": 0.0, "chord": "C"}], "metadata": {}},
            "madmom": {"chords": [{"timestamp": 0.0, "chord": "G"}], "metadata": {"display_name": "Madmom"}},
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
    data.update(overrides)
    return data


def _sample_chords():
    return [
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 1.0, "chord": "Am"},
        {"timestamp": 2.0, "chord": "N"},
    ]


def _write_analysis(media: Path, data=None) -> Path:
    json_path = schema.analysis_json_path(media)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(data if data is not None else _v3_data()), encoding="utf-8")
    return json_path


# ── BTC track write ───────────────────────────────────────────────────


def test_btc_track_roundtrip(tmp_path):
    media = tmp_path / "Song [abc].mp4"
    media.write_bytes(b"fake-media")
    _write_analysis(media)

    btc_chords = [
        {"timestamp": 0.0, "chord": "N"},
        {"timestamp": 2.69, "chord": "F#7"},
        {"timestamp": 4.09, "chord": "Bmaj7"},
    ]
    btc_metadata = {
        "display_name": "BTC",
        "engine": "BTC-ISMIR19",
        "vocabulary": "large-170",
        "model_sha256": "a" * 64,
        "media_sha256": "b" * 64,
        "experimental": True,
    }
    json_path = schema.write_btc_track(media, btc_chords, btc_metadata)

    reloaded, _ = schema.load_analysis(media)
    assert schema.BTC_TRACK_ID in reloaded["chord_tracks"]
    assert reloaded["chord_tracks"][schema.BTC_TRACK_ID]["chords"] == btc_chords
    assert reloaded["chord_tracks"][schema.BTC_TRACK_ID]["metadata"] == btc_metadata
    assert "chordino" in reloaded["chord_tracks"]
    assert reloaded["rhythm_tracks"] == _v3_data()["rhythm_tracks"]
    assert json_path == schema.analysis_json_path(media)


def test_btc_track_existing_requires_replace(tmp_path):
    media = tmp_path / "Song [abc].mp4"
    media.write_bytes(b"fake-media")
    _write_analysis(media)

    schema.write_btc_track(media, _sample_chords(), {"display_name": "BTC"})
    with pytest.raises(schema.SchemaV3Error, match="--replace"):
        schema.write_btc_track(media, _sample_chords(), {"display_name": "BTC"})


def test_btc_track_coexists_and_preserves_rhythm():
    data = _v3_data()
    original_rhythm = data["rhythm_tracks"]
    updated = schema.insert_btc_track(data, _sample_chords(), {"display_name": "BTC"})

    assert updated is not data
    assert schema.BTC_TRACK_ID in updated["chord_tracks"]
    assert "chordino" in updated["chord_tracks"]
    assert "madmom" in updated["chord_tracks"]
    assert updated["rhythm_tracks"] == original_rhythm
    assert schema.BTC_TRACK_ID not in data["chord_tracks"]


# ── conservative user dispatch ───────────────────────────────────────


def _patch_runtime(monkeypatch):
    monkeypatch.setattr("chordflask_btc.analyze.detect_btc_runtime", lambda: dict(_COMPLETE_RUNTIME))
    monkeypatch.setattr("chordflask_btc.analyze.model_sha256", lambda: "a" * 64)


def test_analyze_btc_file_skips_missing_analysis(monkeypatch, capsys, tmp_path):
    _patch_runtime(monkeypatch)
    media = tmp_path / "song.mp3"
    media.write_bytes(b"x")

    code = analyze.analyze_btc_file(media, replace=False)

    assert code == 0
    assert "SKIP: no ChordFlask analysis" in capsys.readouterr().out


def test_analyze_btc_file_predicts_existing_analysis(monkeypatch, capsys, tmp_path):
    _patch_runtime(monkeypatch)
    media = tmp_path / "song.mp3"
    media.write_bytes(b"x")
    _write_analysis(media)

    seen = {}

    def fake_predict(media_path, *, replace=False):
        seen["replace"] = replace
        return {"status": "predicted", "events": 3}

    monkeypatch.setattr("chordflask_btc.analyze.predict_btc_media", fake_predict)

    code = analyze.analyze_btc_file(media, replace=True)

    assert code == 0
    assert seen == {"replace": True}
    assert "OK: 3 events" in capsys.readouterr().out


def test_analyze_btc_directory_dry_run_no_side_effects(monkeypatch, capsys, tmp_path):
    _patch_runtime(monkeypatch)
    media = tmp_path / "song.mp3"
    media.write_bytes(b"x")
    _write_analysis(media)

    monkeypatch.setattr(
        "chordflask_btc.analyze.predict_btc_media",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not predict in dry-run")),
    )

    code = analyze.analyze_btc_directory(tmp_path, dry_run=True, replace=False)

    assert code == 0
    out = capsys.readouterr().out
    assert "ANALYZE" in out
    assert "would analyze: 1" in out


def test_analyze_btc_directory_isolates_file_check_errors(
    monkeypatch, capsys, tmp_path
):
    _patch_runtime(monkeypatch)
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"bad")
    good = tmp_path / "good.mp3"
    good.write_bytes(b"good")
    _write_analysis(bad)
    _write_analysis(good)

    def classify(media, model_hash):
        if media.name == "bad.mp3":
            raise OSError("media became unreadable")
        return analyze.CLASS_STALE, "use --replace"

    monkeypatch.setattr("chordflask_btc.analyze.classify_btc_file", classify)

    code = analyze.analyze_btc_directory(tmp_path, dry_run=False, replace=False)

    assert code == 1
    captured = capsys.readouterr()
    assert "bad.mp3" in captured.out
    assert "media became unreadable" in captured.err
    assert "STALE: use --replace" in captured.out
    assert "failed:      1" in captured.out


def test_analyze_btc_missing_runtime_exits_two(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        "chordflask_btc.analyze.detect_btc_runtime",
        lambda: {"venv": "", "checkpoint": "", "wrapper": "", "complete": False, "missing": ["checkpoint (/x)"]},
    )
    media = tmp_path / "song.mp3"
    media.write_bytes(b"x")

    code = analyze.analyze_btc_file(media, replace=False)

    assert code == 2
    err = capsys.readouterr().err
    assert "optional BTC runtime" in err
    assert "make btc-check" in err
    assert "make setup-btc BTC_ACKNOWLEDGE_WEIGHTS=1" in err
    assert "--analyzer chordino" in err


def test_analyze_btc_invalid_analysis_suggests_validation(
    monkeypatch, capsys, tmp_path
):
    _patch_runtime(monkeypatch)
    media = tmp_path / "song.mp3"
    media.write_bytes(b"x")
    _write_analysis(media, data={"schema_version": 3, "chord_tracks": "bad"})

    code = analyze.analyze_btc_file(media, replace=False)

    assert code == 0
    output = capsys.readouterr().out
    assert "invalid ChordFlask analysis" in output
    assert f"chordflask-maintain validate {tmp_path}" in output


def test_analyze_btc_model_check_failure_suggests_runtime_diagnostic(
    monkeypatch, capsys, tmp_path
):
    _patch_runtime(monkeypatch)
    media = tmp_path / "song.mp3"
    media.write_bytes(b"x")
    _write_analysis(media)
    monkeypatch.setattr(
        "chordflask_btc.analyze.model_sha256",
        lambda: (_ for _ in ()).throw(OSError("checkpoint unreadable")),
    )

    code = analyze.analyze_btc_file(media, replace=False)

    assert code == 1
    err = capsys.readouterr().err
    assert "checkpoint unreadable" in err
    assert "make btc-check" in err


def test_analyze_btc_file_dry_run_exits_two(monkeypatch, capsys, tmp_path):
    _patch_runtime(monkeypatch)
    media = tmp_path / "song.mp3"
    media.write_bytes(b"x")

    code = analyze.analyze_btc(media, replace=False, dry_run=True)

    assert code == 2
    assert "--dry-run requires a directory" in capsys.readouterr().err


# ── framework boundary ───────────────────────────────────────────────


def test_chordflask_btc_orchestration_does_not_import_torch():
    package = REPO_ROOT / "chordflask_btc"
    sources = [
        p.read_text(encoding="utf-8")
        for p in package.glob("*.py")
    ]
    combined = "\n".join(sources)
    assert "import torch" not in combined
    assert "from torch" not in combined
    assert "chordflask_training" not in combined
    assert "from chordflask_base import" in combined


def test_runtime_resolves_installed_wrapper():
    # wrapper_path() resolves through CHORDFLASK_BTC_VENV (default
    # ~/.venvs/chordflask-btc), never a private source-tree script.
    assert wrapper_path().name == "btc-predict-raw"
    assert ".venvs/chordflask-btc" in str(wrapper_path())


def test_runtime_requires_executable_wrapper(monkeypatch, tmp_path):
    btc_dir = tmp_path / "btc"
    btc_dir.mkdir()
    (btc_dir / "predict_raw.py").write_text("# stub\n")
    (btc_dir / "btc_model_large_voca.pt").write_bytes(b"checkpoint")
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").write_text("python")
    wrapper = venv / "bin" / "btc-predict-raw"
    wrapper.write_text("#!/bin/sh\n")
    wrapper.chmod(0o644)
    monkeypatch.setenv("CHORDFLASK_BTC_DIR", str(btc_dir))
    monkeypatch.setenv("CHORDFLASK_BTC_VENV", str(venv))

    state = detect_btc_runtime()

    assert state["complete"] is False
    assert any("executable wrapper" in item for item in state["missing"])


def test_predict_raw_uses_only_verified_default_checkpoint():
    raw = (REPO_ROOT / "chordflask_btc" / "model" / "predict_raw.py").read_text(
        encoding="utf-8"
    )

    # No unverified --model override may bypass the SHA-256 provenance check.
    assert "add_argument(\"--model\"" not in raw
    assert "args.model" not in raw
    assert "DEFAULT_CHECKPOINT" in raw
    assert "weights_only=False" in raw


def test_btc_track_id_uses_shared_schema():
    import chordflask_base

    assert schema.BTC_TRACK_ID == chordflask_base.BTC_TRACK_ID
    assert schema.SCHEMA_VERSION == chordflask_base.SCHEMA_VERSION
