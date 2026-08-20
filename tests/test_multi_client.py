"""Multi-browser client isolation for ChordFlask.

Each browser cookie jar maps to one server-side ClientState. These tests prove
that two independent clients cannot interfere with each other's playback,
display, editing, or serving state, while genuinely shared resources (the
analysis queue) remain shared and deduplicated.
"""

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
FLASK_DIR = REPO_ROOT / "flask"

if str(FLASK_DIR) not in sys.path:
    sys.path.insert(0, str(FLASK_DIR))

import client_state
from chordflask import CLIENT_COOKIE, FlaskMP4App
from chordflask_base import ChordData, DEMUCS_STEM_NAMES
from filerepr import FileRepr
from mp4playerflask import STEMS_AUDIO_SET_ID


@pytest.fixture(autouse=True)
def isolate_default_analysis_queue(monkeypatch, tmp_path):
    monkeypatch.setenv("CHORDFLASK_QUEUE_DIR", str(tmp_path / "default-queue"))


def _make_client(app, token):
    app.clients.get_or_create(token)
    client = app.app.test_client()
    client.set_cookie(CLIENT_COOKIE, token)
    return client


def _write_song(tmp_path, name, chord="C", content=None, stems=False):
    media = tmp_path / name
    media.write_bytes(content if content is not None else name.encode())
    file_repr = FileRepr(str(media), datapath=str(tmp_path / ".chordflask"), create=True)
    cd = ChordData()
    cd.set_chord_track("chordino", [{"timestamp": 0.0, "chord": chord}])
    cd.set_rhythm_track(
        "qm_barbeattracker", bpm=120, meter_signature=4,
        beat_times=[0.0, 0.5, 1.0, 1.5], beat_numbers=[1, 2, 3, 4],
    )
    if stems:
        cd.set_audio_track(STEMS_AUDIO_SET_ID, _stem_set())
    cd.save_to_file(file_repr.get("json"))
    return media


def _stem_set():
    rel = Path(".chordflask") / "stems" / "demucs" / "htdemucs" / "song" / "generation"
    tracks = {}
    for index, stem in enumerate(DEMUCS_STEM_NAMES):
        tracks[stem] = {
            "path": str(rel / f"{stem}.flac"),
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
                    "bass": 0, "drums": 0, "other": 0, "vocals": 0,
                },
            },
            "source_timeline": {"available": False},
        },
    }


def _write_flacs(tmp_path):
    rel = tmp_path / ".chordflask" / "stems" / "demucs" / "htdemucs" / "song" / "generation"
    rel.mkdir(parents=True, exist_ok=True)
    for stem in DEMUCS_STEM_NAMES:
        (rel / f"{stem}.flac").write_bytes(f"{stem}-flac".encode())


# ── 1-4: independent media serving and playback/display state ─────────


def test_two_clients_serve_independent_media(tmp_path):
    app = FlaskMP4App()
    _write_song(tmp_path, "a.mp3")
    _write_song(tmp_path, "b.mp3")
    a = _make_client(app, "client-a")
    b = _make_client(app, "client-b")

    assert a.post("/load_file", json={"dirname": str(tmp_path), "filename": "a.mp3"}).status_code == 200
    assert b.post("/load_file", json={"dirname": str(tmp_path), "filename": "b.mp3"}).status_code == 200

    assert a.get("/video").get_data() == b"a.mp3"
    assert b.get("/video").get_data() == b"b.mp3"


def test_positions_are_independent(tmp_path):
    app = FlaskMP4App()
    a = _make_client(app, "client-a")
    b = _make_client(app, "client-b")

    a.post("/set_position", json={"position": 12.0})
    b.post("/set_position", json={"position": 99.0})

    assert app.clients.get("client-a").current_position == 12.0
    assert app.clients.get("client-b").current_position == 99.0


def test_transpose_display_tracks_unicode_are_independent(tmp_path):
    app = FlaskMP4App()
    _write_song(tmp_path, "a.mp3")
    _write_song(tmp_path, "b.mp3")
    a = _make_client(app, "client-a")
    b = _make_client(app, "client-b")
    a.post("/load_file", json={"dirname": str(tmp_path), "filename": "a.mp3"})
    b.post("/load_file", json={"dirname": str(tmp_path), "filename": "b.mp3"})

    a.post("/update_semitones", json={"semitones": 3})
    a.post("/update_display_options", json={"prefer_flats": False, "repeat_mode": "chords"})
    a.post("/toggle_unicode", json={"use_unicode": True})

    state_a = app.clients.get("client-a")
    state_b = app.clients.get("client-b")
    assert state_a.semitones == 3
    assert state_a.prefer_flats is False
    assert state_a.repeat_mode == "chords"
    assert state_a.use_unicode is True
    # Client B retains defaults untouched by client A.
    assert state_b.semitones == 0
    assert state_b.prefer_flats is True
    assert state_b.repeat_mode == "changes"
    assert state_b.use_unicode is False


# ── 10: stem serving is client-specific ───────────────────────────────


def test_stem_serving_uses_correct_client_media(tmp_path):
    app = FlaskMP4App()
    _write_song(tmp_path, "with-stems.mp3", stems=True)
    _write_song(tmp_path, "plain.mp3")
    _write_flacs(tmp_path)
    a = _make_client(app, "client-a")
    b = _make_client(app, "client-b")

    a.post("/load_file", json={"dirname": str(tmp_path), "filename": "with-stems.mp3"})
    b.post("/load_file", json={"dirname": str(tmp_path), "filename": "plain.mp3"})

    assert a.get("/stem/vocals").status_code == 200
    assert a.get("/stem/vocals").get_data() == b"vocals-flac"
    assert b.get("/stem/vocals").status_code == 404


# ── 11: reanalysis active-media validation is client-specific ─────────


def test_reanalysis_active_media_is_client_specific(tmp_path):
    app = FlaskMP4App()
    _write_song(tmp_path, "a.mp3")
    _write_song(tmp_path, "b.mp3")
    a = _make_client(app, "client-a")
    b = _make_client(app, "client-b")
    a.post("/load_file", json={"dirname": str(tmp_path), "filename": "a.mp3"})
    b.post("/load_file", json={"dirname": str(tmp_path), "filename": "b.mp3"})

    cross = b.post("/reanalyze", json={"dirname": str(tmp_path), "filename": "a.mp3"})
    assert cross.status_code == 409
    assert "not the active file" in cross.get_json()["error"]

    own = a.post("/reanalyze", json={"dirname": str(tmp_path), "filename": "a.mp3"})
    assert own.status_code == 200


# ── 12: shared analysis queue still deduplicates ──────────────────────


def test_shared_queue_deduplicates_jobs(tmp_path):
    app = FlaskMP4App()
    (tmp_path / "song.mp3").write_bytes(b"media")
    a = _make_client(app, "client-a")
    b = _make_client(app, "client-b")

    first = a.post("/load_file", json={"dirname": str(tmp_path), "filename": "song.mp3"})
    second = b.post("/load_file", json={"dirname": str(tmp_path), "filename": "song.mp3"})

    assert first.get_json()["status"] == "queued"
    assert second.get_json()["status"] == "already_queued"
    assert len(app.analysis_queue.status()["pending"]) == 1


# ── 13: unknown cookie gets a fresh state ─────────────────────────────


def test_unknown_cookie_gets_a_fresh_state(tmp_path):
    app = FlaskMP4App()
    client = app.app.test_client()
    client.set_cookie(CLIENT_COOKIE, "bogus-token")

    response = client.get("/video")

    assert response.status_code == 404
    set_cookie = response.headers.get("Set-Cookie", "")
    assert CLIENT_COOKIE in set_cookie
    assert "bogus-token" not in set_cookie
    assert app.clients.get("bogus-token") is None


# ── 14: stale client states are swept ─────────────────────────────────


def _stale_timestamp():
    return time.monotonic() - client_state.TTL_SECONDS - 100


def test_stale_client_states_are_swept(monkeypatch):
    registry = client_state.ClientRegistry()
    stale = registry.get_or_create("stale")
    active = registry.get_or_create("active")
    stale.last_used = _stale_timestamp()

    monkeypatch.setattr(client_state, "SWEEP_THRESHOLD", 0)
    monkeypatch.setattr(client_state, "SWEEP_INTERVAL_SECONDS", 0)
    registry._last_sweep = 0.0

    registry.sweep(exclude_id="active")

    assert registry.get("stale") is None
    assert registry.get("active") is active


def test_sweep_keeps_currently_resolved_client(monkeypatch):
    registry = client_state.ClientRegistry()
    active = registry.get_or_create("active")
    active.last_used = _stale_timestamp()

    monkeypatch.setattr(client_state, "SWEEP_THRESHOLD", 0)
    monkeypatch.setattr(client_state, "SWEEP_INTERVAL_SECONDS", 0)
    registry._last_sweep = 0.0

    registry.sweep(exclude_id="active")

    assert registry.get("active") is active


# ── 15: same-song editing conflict returns 409 ────────────────────────


def _grid_chord(response, beat_index):
    grid = response.get_json()["edit_grid"]
    return next(
        cell["chord"]
        for row in grid["rows"]
        for cell in row
        if cell["beat_index"] == beat_index
    )


def test_concurrent_editing_of_same_song_returns_409(tmp_path):
    app = FlaskMP4App()
    _write_song(tmp_path, "song.mp3")
    setup = _make_client(app, "setup-client")
    setup.post("/load_file", json={"dirname": str(tmp_path), "filename": "song.mp3"})
    payload = {"dirname": str(tmp_path), "filename": "song.mp3"}
    assert setup.post("/start_chord_editing", json=payload).status_code == 200

    a = _make_client(app, "client-a")
    b = _make_client(app, "client-b")
    a.post("/load_file", json={"dirname": str(tmp_path), "filename": "song.mp3"})
    b.post("/load_file", json={"dirname": str(tmp_path), "filename": "song.mp3"})

    assert a.post("/edit_chord", json={**payload, "beat_index": 1, "chord": "F"}).status_code == 200

    conflict = b.post("/edit_chord", json={**payload, "beat_index": 2, "chord": "G"})
    assert conflict.status_code == 409
    assert conflict.get_json()["error"] == "Edited chords changed on disk; reload and re-edit."

    json_path = FileRepr(
        str(tmp_path / "song.mp3"), datapath=str(tmp_path / ".chordflask")
    ).get("json")
    stored = ChordData(json_path)
    chords = stored.chord_track_chords("user_edited")
    assert any(entry["chord"] == "F" for entry in chords)
    assert not any(entry["chord"] == "G" for entry in chords)

    losing_state = app.clients.get("client-b")
    assert losing_state.player.chord_data.chord_track_chords("user_edited") == chords
    assert losing_state.player.chord_data.active_chord_track_id == "user_edited"
    assert losing_state.player.chord_data.active_rhythm_track_id == "qm_barbeattracker"
    assert losing_state.json_mtime_ns == Path(json_path).stat().st_mtime_ns

    display = b.post(
        "/set_position",
        json={"position": 0.5, "include_edit_grid": True},
    )
    assert display.status_code == 200
    assert _grid_chord(display, 1) == "F"
    assert _grid_chord(display, 2) != "G"


def test_stale_start_editing_reloads_disk_and_preserves_existing_selection(tmp_path):
    app = FlaskMP4App()
    _write_song(tmp_path, "song.mp3")
    a = _make_client(app, "client-a")
    b = _make_client(app, "client-b")
    payload = {"dirname": str(tmp_path), "filename": "song.mp3"}
    a.post("/load_file", json=payload)
    b.post("/load_file", json=payload)

    assert a.post("/start_chord_editing", json=payload).status_code == 200
    assert a.post(
        "/edit_chord", json={**payload, "beat_index": 1, "chord": "F"}
    ).status_code == 200

    conflict = b.post("/start_chord_editing", json=payload)

    assert conflict.status_code == 409
    losing_state = app.clients.get("client-b")
    assert losing_state.player.chord_data.active_chord_track_id == "chordino"
    assert losing_state.player.chord_data.active_rhythm_track_id == "qm_barbeattracker"
    assert any(
        entry["chord"] == "F"
        for entry in losing_state.player.chord_data.chord_track_chords("user_edited")
    )
    json_path = losing_state.file_repr.get("json")
    assert losing_state.json_mtime_ns == Path(json_path).stat().st_mtime_ns


def test_stale_reset_reloads_winner_and_preserves_edited_selection(tmp_path):
    app = FlaskMP4App()
    _write_song(tmp_path, "song.mp3")
    setup = _make_client(app, "setup-client")
    payload = {"dirname": str(tmp_path), "filename": "song.mp3"}
    setup.post("/load_file", json=payload)
    assert setup.post("/start_chord_editing", json=payload).status_code == 200

    a = _make_client(app, "client-a")
    b = _make_client(app, "client-b")
    a.post("/load_file", json=payload)
    b.post("/load_file", json=payload)
    assert a.post(
        "/edit_chord", json={**payload, "beat_index": 1, "chord": "F"}
    ).status_code == 200

    conflict = b.post("/reset_edited_chords", json=payload)

    assert conflict.status_code == 409
    losing_state = app.clients.get("client-b")
    assert losing_state.player.chord_data.active_chord_track_id == "user_edited"
    assert losing_state.player.chord_data.active_rhythm_track_id == "qm_barbeattracker"
    display = b.post(
        "/set_position",
        json={"position": 0.5, "include_edit_grid": True},
    )
    assert display.status_code == 200
    assert _grid_chord(display, 1) == "F"


def test_stale_edit_falls_back_when_winner_removed_selected_track(tmp_path):
    app = FlaskMP4App()
    _write_song(tmp_path, "song.mp3")
    setup = _make_client(app, "setup-client")
    payload = {"dirname": str(tmp_path), "filename": "song.mp3"}
    setup.post("/load_file", json=payload)
    assert setup.post("/start_chord_editing", json=payload).status_code == 200

    a = _make_client(app, "client-a")
    b = _make_client(app, "client-b")
    a.post("/load_file", json=payload)
    b.post("/load_file", json=payload)
    assert a.post("/reset_edited_chords", json=payload).status_code == 200

    conflict = b.post(
        "/edit_chord", json={**payload, "beat_index": 2, "chord": "G"}
    )

    assert conflict.status_code == 409
    losing_state = app.clients.get("client-b")
    assert not losing_state.player.chord_data.has_chord_track("user_edited")
    assert losing_state.player.chord_data.active_chord_track_id == "chordino"
    assert losing_state.player.chord_data.active_rhythm_track_id == "qm_barbeattracker"


# ── 15c: same-song editing check+save is atomic across clients ───────


def test_path_lock_registry_keys_by_path():
    registry = client_state.PathLockRegistry()

    assert registry.get("/a/song.json") is registry.get("/a/song.json")
    assert registry.get("/a/song.json") is not registry.get("/b/song.json")


def test_concurrent_same_song_editing_no_lost_update(tmp_path, monkeypatch):
    app = FlaskMP4App()
    _write_song(tmp_path, "song.mp3")
    a = _make_client(app, "client-a")
    b = _make_client(app, "client-b")
    a.post("/load_file", json={"dirname": str(tmp_path), "filename": "song.mp3"})
    b.post("/load_file", json={"dirname": str(tmp_path), "filename": "song.mp3"})

    # Widen the check/save window so the race is exercised, not just asserted.
    real_save = ChordData.save_to_file

    def slow_save(self, file_path):
        time.sleep(0.15)
        real_save(self, file_path)

    monkeypatch.setattr(ChordData, "save_to_file", slow_save)

    barrier = threading.Barrier(2)
    results = {}

    def edit(client, key, beat, chord):
        try:
            barrier.wait(timeout=5)
        except threading.BrokenBarrierError:
            pass
        response = client.post("/edit_chord", json={
            "dirname": str(tmp_path), "filename": "song.mp3",
            "beat_index": beat, "chord": chord,
        })
        results[key] = response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(edit, a, "a", 1, "F"), pool.submit(edit, b, "b", 2, "G")]
        for future in futures:
            future.result()

    assert sorted(results.values()) == [200, 409]

    stored = ChordData(
        FileRepr(str(tmp_path / "song.mp3"), datapath=str(tmp_path / ".chordflask")).get("json")
    )
    edited = [entry["chord"] for entry in stored.chord_track_chords("user_edited")]
    assert sum(1 for chord in edited if chord in ("F", "G")) == 1


def test_concurrent_edits_of_different_songs_do_not_serialize(tmp_path, monkeypatch):
    app = FlaskMP4App()
    _write_song(tmp_path, "one.mp3")
    _write_song(tmp_path, "two.mp3")
    a = _make_client(app, "client-a")
    b = _make_client(app, "client-b")
    a.post("/load_file", json={"dirname": str(tmp_path), "filename": "one.mp3"})
    b.post("/load_file", json={"dirname": str(tmp_path), "filename": "two.mp3"})

    real_save = ChordData.save_to_file

    def slow_save(self, file_path):
        time.sleep(0.3)
        real_save(self, file_path)

    monkeypatch.setattr(ChordData, "save_to_file", slow_save)

    barrier = threading.Barrier(2)

    def edit(client, name, beat, chord):
        try:
            barrier.wait(timeout=5)
        except threading.BrokenBarrierError:
            pass
        return client.post("/edit_chord", json={
            "dirname": str(tmp_path), "filename": name,
            "beat_index": beat, "chord": chord,
        }).status_code

    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(edit, a, "one.mp3", 1, "F"),
            pool.submit(edit, b, "two.mp3", 2, "G"),
        ]
        results = [future.result() for future in futures]
    elapsed = time.monotonic() - start

    assert results == [200, 200]
    # Different songs use different per-path locks, so the two 0.3 s saves
    # overlap (~0.3 s) rather than serialize (~0.6 s).
    assert elapsed < 0.55


# ── 15b: concurrent requests to distinct clients do not leak state ────


def test_concurrent_clients_do_not_leak_state(tmp_path):
    app = FlaskMP4App()
    a = _make_client(app, "client-a")
    b = _make_client(app, "client-b")

    def hammer(client, position):
        for _ in range(50):
            client.post("/set_position", json={"position": position})

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(hammer, a, 5.0),
            pool.submit(hammer, b, 9.0),
        ]
        for future in futures:
            future.result()

    assert app.clients.get("client-a").current_position == 5.0
    assert app.clients.get("client-b").current_position == 9.0
