"""F9 process isolation, synthetic tracks/publication only; no inference."""

import multiprocessing as mp
from pathlib import Path
import subprocess
import sys

import pytest

from chordflask_base import (
    ChordData, ChordTrackRepository, SchemaV3Error, analysis_json_lock,
    analysis_json_path, read_analysis_json, validate_analysis, write_atomic,
)
from chordflask_btc.schema import write_btc_track

CTX = mp.get_context("spawn")
CHORDS = [{"timestamp": 0., "chord": "C"}]


def complete():
    data = ChordData()
    data.set_chord_track("chordino", CHORDS)
    data.set_rhythm_track("qm_barbeattracker", bpm=60, meter_signature=4,
                          beat_times=[0., 1.], beat_numbers=[1, 2])
    return data


def seed(tmp_path, name="song"):
    media = tmp_path / f"{name}.mp3"
    media.write_bytes(b"synthetic media")
    path = analysis_json_path(media)
    path.parent.mkdir(exist_ok=True)
    complete().save_to_file(path)
    return media


def demucs(media):
    from chordflask_demucs.audio import AudioFacts, hash_file
    from chordflask_demucs.runtime import RuntimeInfo
    from chordflask_demucs.storage import publish_set

    staged = media.parent / "staged-stems"
    staged.mkdir()
    facts = AudioFacts("flac", "flac", 44100, 2, 44100, 1.)
    stems = ("bass", "drums", "other", "vocals")
    for stem in stems:
        (staged / f"{stem}.flac").write_bytes(b"synthetic stem")
    publish_set(
        media, staged_dir=staged,
        source=AudioFacts("wav", "pcm_s16le", 44100, 2, 44100, 1.),
        source_hash=hash_file(media), source_size=media.stat().st_size,
        source_timeline={"available": False},
        runtime=RuntimeInfo(media.parent, Path(sys.executable), "4.0.1", "synthetic"),
        device="cpu", stem_facts=dict.fromkeys(stems, facts),
        tail_adjustments=dict.fromkeys(stems, 0),
    )


def canonical(media):
    from chordflask.canonical_analysis import execute_analysis
    from chordflask.filerepr import FileRepr

    def staged(fr):
        data = complete()
        data.set_chord_track("chordino", [{"timestamp": 0., "chord": "G"}])
        data.save_to_file(fr.get("json"))
    execute_analysis(FileRepr(media, create=True), staged, force=True)


def v3(media):
    # Exercise the real V3 CLI's publication with a lightweight runtime stub.
    import types
    from chordflask.helpers.analyze_cli import _run_v3

    runtime = types.ModuleType("chordflask_v3.runtime")
    runtime.require_runtime = lambda: None
    predictor = types.ModuleType("chordflask_v3.predictor")
    predictor.predict_media = lambda media: {"chords": CHORDS, "metadata": {}}
    sys.modules["chordflask_v3.runtime"] = runtime
    sys.modules["chordflask_v3.predictor"] = predictor
    assert _run_v3(media, replace=True, dry_run=False) == 0


def writer(kind, media, attempted, done):
    attempted.set()
    try:
        if kind == "btc":
            write_btc_track(media, CHORDS)
        elif kind == "demucs":
            demucs(media)
        elif kind == "canonical":
            canonical(media)
        elif kind == "v3":
            v3(media)
        else:
            path = analysis_json_path(media)
            with analysis_json_lock(path):
                data = ChordTrackRepository().load(path)
                data.set_rhythm_track("user_edited_rhythm", bpm=90, meter_signature=3,
                                      beat_times=[0., 1.], beat_numbers=[1, 2])
                data.user_data["edit"] = "survives"
                data.save_to_file(path)
    finally:
        done.set()


def launch(kind, media):
    attempted, done = CTX.Event(), CTX.Event()
    child = CTX.Process(target=writer, args=(kind, media, attempted, done))
    child.start()
    assert attempted.wait(5)
    return child, done


def reap(child):
    child.join(10)
    if child.is_alive():
        child.terminate()
        child.join(5)
        pytest.fail("synthetic process did not finish")
    assert child.exitcode == 0


@pytest.mark.parametrize("first,second", [
    ("btc", "demucs"), ("btc", "canonical"), ("rhythm", "btc"),
    ("btc", "v3"),
])
def test_same_media_publications_serialize_and_preserve_updates(tmp_path, first, second):
    media = seed(tmp_path)
    children = []
    try:
        with analysis_json_lock(analysis_json_path(media)):
            for kind in (first, second):
                child, done = launch(kind, media)
                children.append(child)
                assert not done.wait(.25), f"{kind} bypassed the shared lock"
        for child in children:
            reap(child)
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(5)
    result = ChordTrackRepository().load(analysis_json_path(media))
    if "btc" in (first, second):
        assert result.has_chord_track("btc")
    if "v3" in (first, second):
        assert result.has_chord_track("chordflask_v3")
    if "demucs" in (first, second):
        assert result.available_audio_track_ids
    if "canonical" in (first, second):
        assert result.chord_track_chords("chordino")[0]["chord"] == "G"
    if "rhythm" in (first, second):
        assert result.rhythm_track_data("user_edited_rhythm")["bpm"] == 90
        assert result.user_data["edit"] == "survives"


def test_different_media_proceed_independently(tmp_path):
    first, second = seed(tmp_path), seed(tmp_path, "other")
    with analysis_json_lock(analysis_json_path(first)):
        child, done = launch("btc", second)
        try:
            assert done.wait(5)
            reap(child)
        finally:
            if child.is_alive():
                child.terminate()
                child.join(5)


@pytest.mark.parametrize("failure", ["mutation", "validation", "replace"])
def test_failed_transaction_is_intact_and_releases_lock(tmp_path, monkeypatch, failure):
    from chordflask_base import schema

    media = seed(tmp_path)
    path = analysis_json_path(media)
    before = path.read_bytes()
    with pytest.raises((RuntimeError, SchemaV3Error, OSError)):
        with analysis_json_lock(path):
            data = read_analysis_json(path)
            if failure == "mutation":
                raise RuntimeError("failed mutation")
            if failure == "validation":
                data["chord_tracks"]["btc"] = {"chords": [{"timestamp": -1, "chord": "C"}]}
            validate_analysis(data, path)
            if failure == "replace":
                def fail(*args):
                    raise OSError("failed atomic replace")
                monkeypatch.setattr(schema.os, "replace", fail)
            write_atomic(path, data)
    assert path.read_bytes() == before
    assert not list(path.parent.glob("*.tmp"))
    monkeypatch.undo()
    child, _ = launch("btc", media)
    reap(child)
    assert ChordTrackRepository().load(path).has_chord_track("btc")


def test_aliases_and_same_stem_use_one_persistent_lock(tmp_path):
    media = seed(tmp_path)
    path = analysis_json_path(media)
    alias = tmp_path / "alias.json"
    alias.symlink_to(path)
    child = None
    try:
        with analysis_json_lock(alias):
            child, done = launch("btc", media.with_suffix(".mp4"))
            assert not done.wait(.25)
        reap(child)
    finally:
        if child is not None and child.is_alive():
            child.terminate()
            child.join(5)
    assert (path.parent / ".song.analysis.lock").is_file()


def test_base_lock_import_has_no_heavy_dependencies():
    script = """
import sys
from chordflask_base import analysis_json_lock
for name in ('flask', 'torch', 'numpy', 'librosa', 'chordflask_btc', 'chordflask_v3', 'chordflask_demucs'):
    assert name not in sys.modules, name
"""
    subprocess.run([sys.executable, "-c", script], check=True)


def stale_snapshot(path, key, barrier):
    data = read_analysis_json(path)
    barrier.wait(5)
    data["user_data"][key] = True
    validate_analysis(data, path)
    write_atomic(path, data)


@pytest.mark.parametrize("keys", [
    ("btc", "demucs_audio"), ("v3", "canonical_merge"),
    ("user_rhythm", "btc"), ("btc", "v3"),
])
def test_unlocked_atomic_snapshots_reproduce_lost_update(tmp_path, keys):
    path = analysis_json_path(seed(tmp_path))
    barrier = CTX.Barrier(2)
    children = [CTX.Process(target=stale_snapshot, args=(path, key, barrier)) for key in keys]
    try:
        for child in children:
            child.start()
        for child in children:
            reap(child)
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(5)
    assert len(read_analysis_json(path)["user_data"]) == 1


def test_compatibility_snapshot_save_rejects_concurrent_update(tmp_path):
    from chordflask.chordanalyzer import ChordAnalyzer
    from chordflask.filerepr import FileRepr

    media = seed(tmp_path)
    path = analysis_json_path(media)
    analyzer = ChordAnalyzer.__new__(ChordAnalyzer)
    analyzer.file_repr = FileRepr(media)
    analyzer.chord_data = ChordData()
    analyzer.load_chords_from_file()
    child, _ = launch("btc", media)
    reap(child)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="changed on disk"):
        analyzer.save_chords_to_file()
    assert path.read_bytes() == before
    analyzer.load_chords_from_file()
    analyzer.chord_data.user_data["edit"] = "accepted"
    analyzer.save_chords_to_file()
    result = ChordTrackRepository().load(path)
    assert result.has_chord_track("btc")
    assert result.user_data["edit"] == "accepted"


def test_successful_publication_is_atomic_and_validated(tmp_path, monkeypatch):
    from chordflask_base import schema

    media = seed(tmp_path)
    path = analysis_json_path(media)
    before = path.read_bytes()
    real_replace = schema.os.replace
    replacements = []

    def observe(source, destination):
        assert Path(destination) == path
        assert path.read_bytes() == before
        pending = read_analysis_json(source)
        validate_analysis(pending, source)
        assert "btc" in pending["chord_tracks"]
        replacements.append(source)
        return real_replace(source, destination)

    monkeypatch.setattr(schema.os, "replace", observe)
    write_btc_track(media, CHORDS)
    assert len(replacements) == 1
    assert not list(path.parent.glob("*.tmp"))


def test_flask_snapshot_rejects_external_optional_update(tmp_path):
    from flask import Flask
    from types import SimpleNamespace
    from chordflask.app import FlaskMP4App
    from chordflask.client_state import PathLockRegistry
    from chordflask.filerepr import FileRepr

    media = seed(tmp_path)
    path = analysis_json_path(media)
    wrapper = FlaskMP4App.__new__(FlaskMP4App)
    wrapper.path_locks = PathLockRegistry()
    reloaded = []
    wrapper._reload_player_chord_data = lambda *a, **k: reloaded.append(True)
    state = SimpleNamespace(
        file_repr=FileRepr(media), json_mtime_ns=path.stat().st_mtime_ns,
        player=SimpleNamespace(chord_data=ChordTrackRepository().load(path)),
    )
    state.player.chord_data.user_data["edit"] = "stale"
    child, _ = launch("btc", media)
    reap(child)
    before = path.read_bytes()
    with Flask(__name__).app_context():
        response, status = wrapper._save_player_chord_data(state, {})
    assert status == 409
    assert "reload" in response.get_json()["error"]
    assert reloaded
    assert path.read_bytes() == before


def flask_save(media, attempted, done):
    from flask import Flask
    from types import SimpleNamespace
    from chordflask.app import FlaskMP4App
    from chordflask.client_state import PathLockRegistry
    from chordflask.filerepr import FileRepr

    path = analysis_json_path(media)
    wrapper = FlaskMP4App.__new__(FlaskMP4App)
    wrapper.path_locks = PathLockRegistry()
    state = SimpleNamespace(
        file_repr=FileRepr(media), json_mtime_ns=path.stat().st_mtime_ns,
        player=SimpleNamespace(chord_data=ChordTrackRepository().load(path)),
    )
    state.player.chord_data.user_data["edit"] = "accepted"
    attempted.set()
    with Flask(__name__).app_context():
        assert wrapper._save_player_chord_data(state, {}) is None
    done.set()


def migrate(media, attempted, done):
    from chordflask_maintain.migrate import migrate_analysis_file

    attempted.set()
    assert migrate_analysis_file(analysis_json_path(media))[0] == "skip"
    done.set()


@pytest.mark.parametrize("target", [flask_save, migrate])
def test_flask_and_migration_use_shared_process_lock(tmp_path, target):
    media = seed(tmp_path)
    attempted, done = CTX.Event(), CTX.Event()
    child = CTX.Process(target=target, args=(media, attempted, done))
    try:
        with analysis_json_lock(analysis_json_path(media)):
            child.start()
            assert attempted.wait(5)
            assert not done.wait(.25)
        reap(child)
    finally:
        if child.is_alive():
            child.terminate()
            child.join(5)


def test_compatibility_process_refreshes_snapshot_for_later_save(tmp_path):
    from chordflask.chordanalyzer import ChordAnalyzer
    from chordflask.filerepr import FileRepr

    media = seed(tmp_path)
    analyzer = ChordAnalyzer.__new__(ChordAnalyzer)
    analyzer.file_repr = FileRepr(media)
    analyzer._json_snapshot = analyzer._read_json_snapshot()

    class SyntheticService:
        def ensure_analyzed(self, file_repr, use_madmom=False):
            result = complete()
            result.user_data["processed"] = True
            with analysis_json_lock(file_repr.get("json")):
                result.save_to_file(file_repr.get("json"))
            return result

    analyzer.analysis_service = SyntheticService()
    analyzer.process()
    analyzer.chord_data.user_data["later_edit"] = True
    analyzer.save_chords_to_file()
    assert ChordTrackRepository().load(analysis_json_path(media)).user_data == {
        "processed": True, "later_edit": True,
    }


def canonical_at(media, directory, attempted, done):
    from chordflask.canonical_analysis import execute_analysis
    from chordflask.filerepr import FileRepr

    attempted.set()
    execute_analysis(
        FileRepr(media, datapath=directory),
        lambda staged: complete().save_to_file(staged.get("json")), force=True,
    )
    done.set()


def test_canonical_locks_actual_json_in_custom_analysis_directory(tmp_path):
    media = seed(tmp_path)
    directory = tmp_path / "custom-analysis"
    directory.mkdir()
    path = directory / "song.json"
    complete().save_to_file(path)
    attempted, done = CTX.Event(), CTX.Event()
    child = CTX.Process(target=canonical_at, args=(media, directory, attempted, done))
    try:
        with analysis_json_lock(path):
            child.start()
            assert attempted.wait(5)
            assert not done.wait(.25)
            current = ChordTrackRepository().load(path)
            current.set_chord_track("btc", CHORDS)
            current.save_to_file(path)
        reap(child)
    finally:
        if child.is_alive():
            child.terminate()
            child.join(5)
    assert ChordTrackRepository().load(path).has_chord_track("btc")
