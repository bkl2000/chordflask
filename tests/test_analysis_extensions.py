"""Opaque current-schema extensions: synthetic storage only, no inference."""

import copy
from pathlib import Path

import pytest

from chordflask_base import (
    ChordData, ChordTrackRepository, SchemaV3Error, analysis_json_lock,
    analysis_json_path, read_analysis_json, validate_analysis, write_atomic,
)
from chordflask_btc.schema import write_btc_track
from chordflask_maintain.migrate import migrate_analysis_file
from test_analysis_json_concurrency import CHORDS, canonical, complete, demucs, seed
from test_audio_tracks import _audio_set

EXTENSION = {"source": "test", "value": 123, "nested": [None, True, {"key": "value"}]}


@pytest.fixture
def extended(tmp_path):
    media = seed(tmp_path)
    path = analysis_json_path(media)
    raw = read_analysis_json(path)
    raw["x_external_metadata"] = copy.deepcopy(EXTENSION)
    # A legacy-looking name is opaque in CURRENT schema, not a migration field.
    raw["bpm"] = {"external": True}
    raw["chord_tracks"]["external_chords"] = copy.deepcopy(raw["chord_tracks"]["chordino"])
    raw["rhythm_tracks"]["external_rhythm"] = copy.deepcopy(raw["rhythm_tracks"]["qm_barbeattracker"])
    for collection in ("chord_tracks", "rhythm_tracks"):
        for entry in raw[collection].values():
            entry["x_track"] = copy.deepcopy(EXTENSION)
            entry["metadata"]["x_metadata"] = copy.deepcopy(EXTENSION)
    raw["chord_tracks"]["chordino"]["chords"][0]["x_event"] = EXTENSION
    audio = _audio_set()
    audio["x_audio"] = EXTENSION
    audio["metadata"]["x_metadata"] = EXTENSION
    audio["tracks"]["vocals"]["x_stem"] = EXTENSION
    raw["audio_tracks"]["external_audio"] = audio
    validate_analysis(raw, path, require_current=True)
    write_atomic(path, raw)
    return media, path, raw


def test_repository_roundtrip_retains_all_opaque_objects(extended):
    _, path, before = extended
    repository = ChordTrackRepository()
    with analysis_json_lock(path):
        repository.save(repository.load(path), path)
    assert read_analysis_json(path) == before


def test_opaque_snapshot_does_not_resurrect_removed_tracks(extended):
    _, path, _ = extended
    with analysis_json_lock(path):
        model = ChordTrackRepository().load(path)
        model.remove_chord_track("external_chords")
        model.remove_rhythm_track("external_rhythm")
        model.remove_audio_track("external_audio")
        model.save_to_file(path)
    result = read_analysis_json(path)
    assert "external_chords" not in result["chord_tracks"]
    assert "external_rhythm" not in result["rhythm_tracks"]
    assert "external_audio" not in result["audio_tracks"]
    assert result["x_external_metadata"] == EXTENSION


def test_loading_another_document_replaces_opaque_snapshot(extended, tmp_path):
    _, path, _ = extended
    normal_path = tmp_path / "normal.json"
    complete().save_to_file(normal_path)
    model = ChordTrackRepository().load(path)
    model.load_from_file(normal_path)
    model.save_to_file(normal_path)
    assert "x_external_metadata" not in read_analysis_json(normal_path)


@pytest.mark.parametrize("operation", [
    "chord", "rhythm", "btc", "btc_replace", "demucs", "demucs_replace", "canonical", "compatibility",
])
def test_production_mutations_preserve_unrelated_extensions(extended, operation, monkeypatch):
    media, path, before = extended
    if operation in ("btc", "btc_replace"):
        write_btc_track(media, CHORDS)
        if operation == "btc_replace":
            write_btc_track(media, [{"timestamp": 0., "chord": "G"}], replace=True)
    elif operation in ("demucs", "demucs_replace"):
        demucs(media)
        if operation == "demucs_replace":
            from chordflask_demucs import storage
            from chordflask_demucs.audio import AudioFacts
            monkeypatch.setattr(storage, "probe_audio", lambda path: AudioFacts(
                "flac", "flac", 44100, 2, 44100, 1.,
            ))
            demucs(media)
    elif operation == "canonical":
        canonical(media)
    elif operation == "compatibility":
        from chordflask.chordanalyzer import ChordAnalyzer
        from chordflask.filerepr import FileRepr
        analyzer = ChordAnalyzer.__new__(ChordAnalyzer)
        analyzer.file_repr = FileRepr(media)
        analyzer.chord_data = ChordData()
        analyzer.load_chords_from_file()
        analyzer.chord_data.user_data["edit"] = True
        analyzer.save_chords_to_file()
    else:
        # Exercise the shared Flask persistence boundary with real model edits.
        from flask import Flask
        from types import SimpleNamespace
        from chordflask.app import FlaskMP4App
        from chordflask.client_state import PathLockRegistry
        from chordflask.filerepr import FileRepr
        wrapper = FlaskMP4App.__new__(FlaskMP4App)
        wrapper.path_locks = PathLockRegistry()
        model = ChordTrackRepository().load(path)
        state = SimpleNamespace(file_repr=FileRepr(media),
                                json_mtime_ns=path.stat().st_mtime_ns,
                                player=SimpleNamespace(chord_data=model))
        if operation == "chord":
            model.create_beat_aligned_track("user_edited")
            model.edit_chord_track_beat("user_edited", 1, "G")
        else:
            model.bpm = 90
        with Flask(__name__).app_context():
            assert wrapper._save_player_chord_data(state, {}) is None
    after = read_analysis_json(path)
    assert after["x_external_metadata"] == EXTENSION
    assert after["bpm"] == before["bpm"]
    assert after["audio_tracks"]["external_audio"] == before["audio_tracks"]["external_audio"]
    for collection in ("chord_tracks", "rhythm_tracks"):
        for track_id, entry in before[collection].items():
            assert after[collection][track_id]["x_track"] == entry["x_track"]
            if operation != "canonical":
                assert after[collection][track_id]["metadata"] == entry["metadata"]
            if track_id.startswith("external_"):
                assert after[collection][track_id] == entry
    if operation != "canonical":
        assert after["chord_tracks"]["chordino"] == before["chord_tracks"]["chordino"]
    if operation not in ("rhythm", "canonical"):
        assert after["rhythm_tracks"] == before["rhythm_tracks"]
    if operation == "chord":
        assert after["chord_tracks"]["user_edited"]["chords"][-1]["chord"] == "G"
    if operation == "rhythm":
        assert after["rhythm_tracks"]["qm_barbeattracker"]["bpm"] == 90


def test_current_maintenance_is_byte_identical(extended):
    _, path, _ = extended
    original = path.read_bytes()
    assert migrate_analysis_file(path) == ("skip", "already schema 3")
    assert path.read_bytes() == original


def test_actual_flask_chord_edit_routes_preserve_extensions(tmp_path):
    from chordflask.analysis_queue import AnalysisQueue
    from test_chord_editing import make_client, _activate_editable, _payload, _state
    wrapper, client = make_client()
    wrapper.analysis_queue = AnalysisQueue(tmp_path / "queue")
    _activate_editable(wrapper, tmp_path)
    state = _state(wrapper)
    path = Path(state.file_repr.get("json"))
    raw = read_analysis_json(path)
    raw["x_external_metadata"] = EXTENSION
    raw["chord_tracks"]["chordino"]["x_track"] = EXTENSION
    write_atomic(path, raw)
    state.player.reload_chord_data()
    state.json_mtime_ns = path.stat().st_mtime_ns
    assert client.post("/start_chord_editing", json=_payload(tmp_path)).status_code == 200
    assert client.post("/edit_chord", json=_payload(
        tmp_path, beat_index=0, chord="G",
    )).status_code == 200
    after = read_analysis_json(path)
    assert after["x_external_metadata"] == EXTENSION
    assert after["chord_tracks"]["chordino"] == raw["chord_tracks"]["chordino"]
    assert after["rhythm_tracks"] == raw["rhythm_tracks"]


@pytest.mark.parametrize("version", [None, 1, 2])
def test_migration_consumes_legacy_fields_but_retains_extensions(tmp_path, version):
    path = tmp_path / "song.json"
    legacy = {"base_chords": CHORDS, "bpm": 60, "meter_signature": 4,
              "beat_times": [0., 1.], "beat_numbers": [1, 2],
              "x_external_metadata": EXTENSION}
    if version is not None:
        legacy["schema_version"] = version
    write_atomic(path, legacy)
    assert migrate_analysis_file(path)[0] == "ok"
    result = read_analysis_json(path)
    assert result["x_external_metadata"] == EXTENSION
    assert "base_chords" not in result and "bpm" not in result
    assert result["chord_tracks"]["chordino"]["chords"] == CHORDS
    assert validate_analysis(result, require_current=True) == "current"


@pytest.mark.parametrize("mutation", [
    lambda data: data.update(schema_version=99),
    lambda data: data.update(transpose=True),
    lambda data: data["chord_tracks"]["chordino"].update(metadata=[]),
    lambda data: data["rhythm_tracks"]["qm_barbeattracker"].update(beat_times=[-1]),
    lambda data: data["audio_tracks"]["external_audio"]["tracks"]["vocals"].update(size=-1),
])
def test_extensions_do_not_bypass_schema_validation(extended, mutation):
    _, path, raw = extended
    original = path.read_bytes()
    mutation(raw)
    with pytest.raises(SchemaV3Error):
        validate_analysis(raw, path)
    assert path.read_bytes() == original


@pytest.mark.parametrize("failure", ["validation", "serialization", "replace", "mutation"])
def test_model_failure_keeps_original_and_releases_lock(extended, monkeypatch, failure):
    from chordflask_base import schema
    _, path, _ = extended
    original = path.read_bytes()
    with pytest.raises((ValueError, TypeError, OSError, RuntimeError)):
        with analysis_json_lock(path):
            model = ChordTrackRepository().load(path)
            if failure == "mutation":
                raise RuntimeError("mutation failed")
            if failure == "validation":
                model.transpose(True)
            elif failure == "serialization":
                model._opaque_document["x_external_metadata"] = {"bad": float("nan")}
            else:
                def fail(*args):
                    raise OSError("replace failed")
                monkeypatch.setattr(schema.os, "replace", fail)
            model.save_to_file(path)
    assert path.read_bytes() == original
    assert not list(path.parent.glob("*.tmp"))
    monkeypatch.undo()
    with analysis_json_lock(path):
        ChordTrackRepository().load(path).save_to_file(path)


def test_normal_document_has_same_json_semantics(tmp_path):
    path = tmp_path / "normal.json"
    complete().save_to_file(path)
    before = read_analysis_json(path)
    ChordTrackRepository().load(path).save_to_file(path)
    assert read_analysis_json(path) == before


def test_roundtrip_publication_is_atomic(extended, monkeypatch):
    from chordflask_base import schema
    _, path, before = extended
    original = path.read_bytes()
    replace = schema.os.replace
    observed = []

    def observe(source, destination):
        assert Path(destination) == path
        assert path.read_bytes() == original
        assert read_analysis_json(source) == before
        validate_analysis(read_analysis_json(source), source, require_current=True)
        observed.append(True)
        replace(source, destination)

    monkeypatch.setattr(schema.os, "replace", observe)
    ChordTrackRepository().load(path).save_to_file(path)
    assert observed == [True]
    assert not list(path.parent.glob("*.tmp"))
