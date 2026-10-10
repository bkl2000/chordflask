"""Stem chord preparation: manager, subprocess command, routes and Prepare UI."""

import sys
import time
from pathlib import Path

import pytest

from chordflask import media_preparation
from chordflask.app import CLIENT_COOKIE, FlaskMP4App
from chordflask.stem_chord_analysis import analyze_stem_chords
from chordflask.stem_preparation import BackgroundPreparationManager
from chordflask_base import ChordTrackRepository
from tests.test_stem_chord_analysis import FakeAnalyzer, _song

CLIENT_ID = "stem-chords-client"


@pytest.fixture(autouse=True)
def isolate_queue_and_capabilities(monkeypatch, tmp_path):
    monkeypatch.setenv("CHORDFLASK_QUEUE_DIR", str(tmp_path / "queue"))
    media_preparation.clear_capability_cache()


def _capability(available=True):
    return lambda: {"available": available, "cuda": False, "reason": "missing"}


def _client():
    app = FlaskMP4App()
    client = app.app.test_client()
    app.clients.get_or_create(CLIENT_ID)
    client.set_cookie(CLIENT_COOKIE, CLIENT_ID)
    return app, client


def _load(client, directory, name="song.mp3"):
    response = client.post("/load_file", json={"dirname": str(directory), "filename": name})
    assert response.status_code == 200
    assert response.get_json()["status"] == "ready"
    return response.get_json()


def _wait_status(client, expected, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = client.get("/stem_chords_preparation_status").get_json()
        if payload["state"] == expected:
            return payload
        time.sleep(0.01)
    raise AssertionError(f"stem chord preparation did not reach {expected}")


def _body(media, stem="other"):
    return {"dirname": str(media.parent), "filename": media.name, "stem": stem}


def _manager(runner):
    return BackgroundPreparationManager(capability_probe=_capability(), runner=runner, label="Stem chords")


def _real_runner(calls=None):
    def runner(path, stem):
        if calls is not None:
            calls.append((Path(path).name, stem))
        analyze_stem_chords(path, stem, analyzer=FakeAnalyzer())
        return 0
    return runner


def _unexpected(*_args):
    raise AssertionError("preparation must not start")


def test_manager_passes_runner_args(tmp_path):
    calls = []
    manager = _manager(lambda path, stem: calls.append((path, stem)) or 0)
    assert manager.start(tmp_path / "song.mp3", "other")["status"] == "accepted"
    deadline = time.monotonic() + 5
    while manager.status(tmp_path / "song.mp3")["state"] != "ready" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert calls == [(tmp_path / "song.mp3", "other")]


def test_stem_chords_command_source_and_frozen(monkeypatch, tmp_path):
    media = tmp_path / "song.mp3"
    assert media_preparation.stem_chords_command(media, "other") == [
        sys.executable, "-m", "chordflask", "--analyze-stem", "other", str(media),
    ]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert media_preparation.stem_chords_command(media, "other") == [
        sys.executable, "--analyze-stem", "other", str(media),
    ]


def test_run_stem_chord_preparation_uses_helper(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(media_preparation, "_run_helper", lambda action, command: seen.append((action, command)) or 0)
    assert media_preparation.run_stem_chord_preparation(tmp_path / "song.mp3", "bass") == 0
    assert seen[0][0] == "Stem chords"
    assert seen[0][1][-2:] == ["bass", str(tmp_path / "song.mp3")]


def test_prepare_starts_job_and_refresh_selects_new_track(tmp_path):
    app, client = _client()
    media, json_path = _song(tmp_path)
    _load(client, tmp_path)
    calls = []
    app.stem_chords_preparation = _manager(_real_runner(calls))

    assert client.post("/prepare_stem_chords", json=_body(media)).status_code == 202
    status = _wait_status(client, "ready")
    assert status["stem"] == "other"
    assert calls == [("song.mp3", "other")]

    payload = client.post("/refresh_stem_chords", json=_body(media)).get_json()
    assert payload["active_chord_track_id"] == "chordino_stem_other"
    ids = {track["id"] for track in payload["available_chord_tracks"]}
    assert {"chordino", "user_edited", "btc", "chordino_stem_other"} <= ids
    assert ChordTrackRepository().load(json_path).user_data == {"note": "keep"}


@pytest.mark.parametrize("stem", ["guitar", "../x", "", None, 3])
def test_prepare_rejects_unknown_stem(tmp_path, stem):
    app, client = _client()
    media, _ = _song(tmp_path)
    _load(client, tmp_path)
    app.stem_chords_preparation = _manager(_unexpected)
    response = client.post("/prepare_stem_chords", json=_body(media, stem))
    assert response.status_code == 400


def test_prepare_requires_loaded_stem_set(tmp_path):
    app, client = _client()
    media, _ = _song(tmp_path, with_audio=False)
    _load(client, tmp_path)
    app.stem_chords_preparation = _manager(_unexpected)
    assert client.post("/prepare_stem_chords", json=_body(media)).status_code == 409


def test_prepare_returns_ready_for_current_track_without_recompute(tmp_path):
    app, client = _client()
    media, _ = _song(tmp_path)
    analyze_stem_chords(media, "other", analyzer=FakeAnalyzer())
    _load(client, tmp_path)
    app.stem_chords_preparation = _manager(_unexpected)
    assert client.post("/prepare_stem_chords", json=_body(media)).get_json()["status"] == "ready"
    assert client.get("/stem_chords_preparation_status").get_json()["state"] != "running"


def test_prepare_recomputes_stale_track(tmp_path):
    app, client = _client()
    media, json_path = _song(tmp_path)
    analyze_stem_chords(media, "other", analyzer=FakeAnalyzer())
    data = ChordTrackRepository().load(json_path)
    metadata = data.chord_track_metadata("chordino_stem_other")
    metadata["audio_source"]["stem_sha256"] = "f" * 64
    data.set_chord_track("chordino_stem_other", data.chord_track_chords("chordino_stem_other"), metadata=metadata)
    data.save_to_file(json_path)
    _load(client, tmp_path)
    app.stem_chords_preparation = _manager(_real_runner())
    assert client.post("/prepare_stem_chords", json=_body(media)).status_code == 202
    _wait_status(client, "ready")


def test_prepare_rejects_non_active_media_and_queued_media(tmp_path):
    app, client = _client()
    media, _ = _song(tmp_path)
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other, _ = _song(other_dir)
    _load(client, tmp_path)
    app.stem_chords_preparation = _manager(_unexpected)
    assert client.post("/prepare_stem_chords", json=_body(other)).status_code == 409
    app.analysis_queue.enqueue(media)
    assert client.post("/prepare_stem_chords", json=_body(media)).status_code == 409


def test_status_idle_without_loaded_song():
    _, client = _client()
    assert client.get("/stem_chords_preparation_status").get_json()["state"] == "idle"


def test_stem_track_write_triggers_edit_conflict(tmp_path):
    _, client = _client()
    media, _ = _song(tmp_path)
    _load(client, tmp_path)
    body = {"dirname": str(tmp_path), "filename": media.name}
    assert client.post("/start_chord_editing", json=body).status_code == 200
    time.sleep(0.01)
    analyze_stem_chords(media, "other", analyzer=FakeAnalyzer())

    response = client.post("/edit_chord", json={**body, "beat_index": 0, "chord": "G"})

    assert response.status_code == 409
    saved = ChordTrackRepository().load(tmp_path / ".chordflask" / "song.json")
    assert saved.has_chord_track("chordino_stem_other")


def _edited_on_snapshot_grid(tmp_path):
    media, json_path = _song(tmp_path)
    data = ChordTrackRepository().load(json_path)
    rhythm = data.rhythm_track_data("qm_barbeattracker")
    rhythm["beat_times"] = [t + 0.1 for t in rhythm["beat_times"]]
    data.set_rhythm_track("user_edited_rhythm", **rhythm)
    metadata = data.chord_track_metadata("user_edited")
    metadata["sources"]["rhythm"] = "user_edited_rhythm"
    data.set_chord_track("user_edited", data.chord_track_chords("user_edited"), metadata=metadata)
    data.save_to_file(json_path)
    return media


def test_refresh_without_stem_keeps_edited_selection(tmp_path):
    _, client = _client()
    media = _edited_on_snapshot_grid(tmp_path)
    assert _load(client, tmp_path)["active_chord_track_id"] == "user_edited"
    analyze_stem_chords(media, "other", analyzer=FakeAnalyzer())

    body = {"dirname": str(tmp_path), "filename": media.name}
    payload = client.post("/refresh_stem_chords", json=body).get_json()

    assert payload["active_chord_track_id"] == "user_edited"
    assert payload["active_rhythm_track_id"] == "user_edited_rhythm"
    assert "chordino_stem_other" in {track["id"] for track in payload["available_chord_tracks"]}


def test_refresh_with_stem_selects_it_on_the_qm_grid_when_edited_was_active(tmp_path):
    _, client = _client()
    media = _edited_on_snapshot_grid(tmp_path)
    _load(client, tmp_path)
    analyze_stem_chords(media, "other", analyzer=FakeAnalyzer())

    payload = client.post("/refresh_stem_chords", json=_body(media)).get_json()

    assert payload["active_chord_track_id"] == "chordino_stem_other"
    assert payload["active_rhythm_track_id"] == "qm_barbeattracker"


def test_refresh_with_missing_stem_track_keeps_selection(tmp_path):
    _, client = _client()
    media = _edited_on_snapshot_grid(tmp_path)
    _load(client, tmp_path)
    payload = client.post("/refresh_stem_chords", json=_body(media, "bass")).get_json()
    assert payload["active_chord_track_id"] == "user_edited"
