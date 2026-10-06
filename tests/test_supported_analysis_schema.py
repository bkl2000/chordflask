"""Neutral storage validation, migration policy and producer boundary regressions."""

import json
import subprocess
import sys

import pytest

from chordflask_base import (
    AnalysisMigrationRequired, ChordTrackRepository, SchemaV3Error,
    analysis_json_path, is_canonical_analysis_complete, load_analysis, validate_analysis,
)
from chordflask_maintain.migrate import MigrationFileError, migrate_analysis_file
from chordflask_maintain.validate import validate_file


def legacy(version=2):
    return {"schema_version": version, "base_chords": [{"timestamp": 0, "chord": "C"}],
            "bpm": 60, "meter_signature": 4, "beat_times": [0, 1], "beat_numbers": [1, 2]}


def current():
    return {"schema_version": 3, "chord_tracks": {}, "rhythm_tracks": {}}


def write(tmp_path, data):
    media = tmp_path / "song.mp3"
    path = analysis_json_path(media)
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data))
    return media, path


@pytest.mark.parametrize("data, status", [(current(), "current"), (legacy(), "migratable"),
                                         (legacy(1), "migratable"),
                                         ({"base_chords": []}, "migratable")])
def test_validator_repository_and_check_agree_without_writing(tmp_path, data, status):
    media, path = write(tmp_path, data)
    original = path.read_bytes()
    assert validate_analysis(data, path) == status
    ChordTrackRepository().load(path)
    kind, guidance = validate_file(path)
    assert kind == "valid"
    assert (guidance is not None) == (status == "migratable")
    assert load_analysis(media, require_current=False)[0] == data
    assert path.read_bytes() == original
    if status == "migratable":
        with pytest.raises(AnalysisMigrationRequired, match="migrate-schema"):
            load_analysis(media)
        with pytest.raises(AnalysisMigrationRequired):
            validate_analysis(data, require_current=True)
    else:
        assert load_analysis(media)[0] == data


@pytest.mark.parametrize("data", [
    [], {"schema_version": 99}, {"schema_version": True}, {"schema_version": 3.0},
    {"schema_version": 3, "chord_tracks": {}},
    {**current(), "audio_tracks": {"stems": {}}},
    {**legacy(), "beat_times": [1, 0]},
])
def test_invalid_unsupported_data_rejected_by_every_storage_boundary(tmp_path, data):
    media, path = write(tmp_path, data)
    original = path.read_bytes()
    with pytest.raises(SchemaV3Error):
        validate_analysis(data, path)
    with pytest.raises(ValueError):
        ChordTrackRepository().load(path)
    assert validate_file(path)[0] == "invalid"
    with pytest.raises(SchemaV3Error):
        load_analysis(media)
    with pytest.raises(MigrationFileError):
        migrate_analysis_file(path)
    assert path.read_bytes() == original


def test_explicit_migration_makes_legacy_ready_for_producer_updates(tmp_path):
    media, path = write(tmp_path, legacy())
    assert migrate_analysis_file(path)[0] == "ok"
    data, _ = load_analysis(media)
    assert validate_analysis(data) == "current"
    assert is_canonical_analysis_complete(ChordTrackRepository().load(path))
    assert migrate_analysis_file(path) == ("skip", "already schema 3")


def test_optional_only_validity_does_not_imply_canonical_completion(tmp_path):
    from chordflask_btc.schema import insert_btc_track

    data = insert_btc_track(current(), [{"timestamp": 0, "chord": "C"}])
    _, path = write(tmp_path, data)
    assert validate_analysis(data) == "current"
    assert not is_canonical_analysis_complete(ChordTrackRepository().load(path))


def test_btc_and_compatibility_exports_use_neutral_functions():
    from chordflask_btc import batch, predictor, schema

    assert schema.load_analysis is batch.load_analysis is predictor.load_analysis is load_analysis
    assert schema.validate_analysis is validate_analysis


def test_btc_legacy_guidance_requests_migration_not_validation(tmp_path, monkeypatch, capsys):
    from chordflask_btc import analyze

    media, _ = write(tmp_path, legacy())
    media.write_bytes(b"synthetic")
    monkeypatch.setattr(analyze, "require_btc_runtime_user", lambda: 0)
    monkeypatch.setattr(analyze, "model_sha256", lambda: "unused")
    assert analyze.analyze_btc_file(media, replace=False) == 0
    text = capsys.readouterr().out
    assert "requires migration" in text
    assert "chordflask-maintain migrate-schema" in text
    assert "chordflask-maintain validate" not in text


def test_neutral_validation_imports_no_optional_or_heavy_packages():
    result = subprocess.run(
        [sys.executable, "-B", "-c", "import sys; from chordflask_base import validate_analysis; "
         "validate_analysis({'schema_version':3,'chord_tracks':{},'rhythm_tracks':{}}); "
         "assert not any(n.split('.')[0] in {'chordflask_btc','torch','flask','numpy'} "
         "for n in sys.modules); "
         "assert not any(n.startswith('chordflask_') and n.split('.')[0] != 'chordflask_base' "
         "for n in sys.modules)"], capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_btc_directory_requests_migration_for_legacy(tmp_path, monkeypatch, capsys):
    from chordflask_btc import analyze

    media, _ = write(tmp_path, legacy())
    media.write_bytes(b"synthetic")
    monkeypatch.setattr(analyze, "require_btc_runtime_user", lambda: 0)
    monkeypatch.setattr(analyze, "model_sha256", lambda: "unused")
    assert analyze.analyze_btc_directory(tmp_path, dry_run=True, replace=False) == 0
    text = capsys.readouterr().out
    assert "chordflask-maintain migrate-schema" in text
    assert "chordflask-maintain validate" not in text
