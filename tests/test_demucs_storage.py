import os

import pytest

from chordflask_base import ChordData, ChordTrackRepository
from chordflask_demucs import storage
from chordflask_demucs.audio import AudioFacts, hash_file
from chordflask_demucs.constants import AUDIO_SET_ID, CURRENT, ERROR, STALE, TODO
from chordflask_demucs.runtime import RuntimeInfo
from chordflask_demucs.validation import build_audio_track_set, pipeline_fingerprint


def _runtime(tmp_path):
    return RuntimeInfo(tmp_path / "venv", tmp_path / "venv/bin/python", "4.0.1", "2.6.0")


def _source():
    return AudioFacts("wav", "pcm_s16le", 44100, 2, 44100, 1.0)


def _stem_facts():
    return {
        stem: AudioFacts("flac", "flac", 44100, 2, 44100, 1.0)
        for stem in ("bass", "drums", "other", "vocals")
    }


def _write_registered_set(tmp_path, monkeypatch):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"source media")
    generation = storage.stems_root(media) / "generation"
    generation.mkdir(parents=True)
    contents = {stem: f"{stem}-flac".encode() for stem in _stem_facts()}
    for stem, content in contents.items():
        (generation / f"{stem}.flac").write_bytes(content)

    runtime = _runtime(tmp_path)
    facts = _stem_facts()
    paths = {stem: generation / f"{stem}.flac" for stem in facts}
    set_data = build_audio_track_set(
        source=_source(),
        source_hash=hash_file(media),
        source_size=media.stat().st_size,
        source_timeline={"available": False},
        runtime=runtime,
        device="cpu",
        stem_paths=paths,
        stem_facts=facts,
        stem_hashes={stem: hash_file(path) for stem, path in paths.items()},
        stem_sizes={stem: path.stat().st_size for stem, path in paths.items()},
        tail_adjustments={stem: 0 for stem in facts},
        relative_to=media.parent,
    )
    data = ChordData()
    data.set_audio_track(AUDIO_SET_ID, set_data)
    ChordTrackRepository().save(data, storage.analysis_path(media))
    monkeypatch.setattr(storage, "probe_audio", lambda path: facts[path.stem])
    return media, runtime, set_data


def test_classify_distinguishes_todo_current_and_stale(tmp_path, monkeypatch):
    todo = tmp_path / "todo.mp3"
    todo.write_bytes(b"todo")
    assert storage.classify(todo).label == TODO

    media, runtime, _ = _write_registered_set(tmp_path, monkeypatch)
    current = storage.classify(media, runtime=runtime, device="cpu")
    assert current.label == CURRENT

    (storage.stems_root(media) / "generation" / "vocals.flac").write_bytes(b"VOCALS-FLAC")
    stale = storage.classify(media, runtime=runtime, device="cpu")
    assert stale.label == STALE
    assert "hash" in stale.reason


def test_malformed_analysis_is_error_and_never_replaced(tmp_path):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"source")
    path = storage.analysis_path(media)
    path.parent.mkdir()
    path.write_text("not json", encoding="utf-8")

    status = storage.classify(media)

    assert status.label == ERROR
    assert path.read_text(encoding="utf-8") == "not json"


def test_set_id_and_pipeline_are_stable(tmp_path):
    runtime = _runtime(tmp_path)
    assert storage.safe_media_key(tmp_path / "A song.mp3") == storage.safe_media_key(tmp_path / "A song.mp3")
    assert pipeline_fingerprint(runtime, device="cpu") == pipeline_fingerprint(runtime, device="cpu")


def test_media_lock_rejects_a_second_owner(tmp_path):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"source")

    with storage.media_lock(media):
        with pytest.raises(storage.DemucsBusyError):
            with storage.media_lock(media):
                pass


def _stage(tmp_path):
    stage = tmp_path / "stage"
    stage.mkdir()
    for stem in ("bass", "drums", "other", "vocals"):
        (stage / f"{stem}.flac").write_bytes(f"{stem}-flac".encode())
    return stage


def test_publish_set_preserves_existing_chord_data(tmp_path, monkeypatch):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"source media")
    current = ChordData()
    current.set_base_chords([{"timestamp": 0.0, "chord": "C"}])
    current.user_data = {"note": "keep"}
    json_path = storage.analysis_path(media)
    json_path.parent.mkdir()
    ChordTrackRepository().save(current, json_path)

    facts = _stem_facts()
    monkeypatch.setattr(storage, "probe_audio", lambda path: facts[path.stem])
    result = storage.publish_set(
        media,
        staged_dir=_stage(tmp_path),
        source=_source(),
        source_hash=hash_file(media),
        source_size=media.stat().st_size,
        source_timeline={"available": False},
        runtime=_runtime(tmp_path),
        device="cpu",
        stem_facts=facts,
        tail_adjustments={stem: 0 for stem in facts},
    )

    loaded = ChordTrackRepository().load(result)
    assert loaded.has_audio_track(AUDIO_SET_ID)
    assert loaded.user_data == {"note": "keep"}
    assert loaded._base_chords == [{"timestamp": 0.0, "chord": "C"}]
    assert storage.classify(media, runtime=_runtime(tmp_path), device="cpu").label == CURRENT


def test_json_replace_failure_leaves_old_json_unchanged(tmp_path, monkeypatch):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"source media")
    current = ChordData()
    current.set_base_chords([{"timestamp": 0.0, "chord": "C"}])
    json_path = storage.analysis_path(media)
    json_path.parent.mkdir()
    ChordTrackRepository().save(current, json_path)
    before = json_path.read_bytes()

    facts = _stem_facts()
    monkeypatch.setattr(storage, "probe_audio", lambda path: facts[path.stem])
    real_replace = os.replace

    def fail_final_json(source, destination):
        if os.fspath(destination) == os.fspath(json_path):
            raise OSError("simulated JSON publication failure")
        return real_replace(source, destination)

    monkeypatch.setattr(storage.os, "replace", fail_final_json)
    with pytest.raises(OSError, match="simulated JSON publication failure"):
        storage.publish_set(
            media,
            staged_dir=_stage(tmp_path),
            source=_source(),
            source_hash=hash_file(media),
            source_size=media.stat().st_size,
            source_timeline={"available": False},
            runtime=_runtime(tmp_path),
            device="cpu",
            stem_facts=facts,
            tail_adjustments={stem: 0 for stem in facts},
        )

    assert json_path.read_bytes() == before
    assert not ChordTrackRepository().load(json_path).has_audio_track(AUDIO_SET_ID)
