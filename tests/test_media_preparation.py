"""Focused Lyrics/BTC preparation capability, subprocess, route, and UI tests."""

import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from chordflask import media_preparation
from chordflask.app import CLIENT_COOKIE, FlaskMP4App
from chordflask.stem_preparation import BackgroundPreparationManager
from chordflask_base import ChordData


CLIENT_ID = "media-preparation-client"


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


def _song(tmp_path, name="song.mp3", *, analyzed=True, edited=False):
    media = tmp_path / name
    media.write_bytes(b"media")
    if analyzed:
        analysis_dir = tmp_path / ".chordflask"
        analysis_dir.mkdir(exist_ok=True)
        data = ChordData()
        data.set_base_chords([{"timestamp": 0.0, "chord": "C"}])
        if edited:
            data.set_rhythm_track(
                "qm_barbeattracker",
                bpm=120,
                meter_signature=4,
                beat_times=[0.0],
                beat_numbers=[1],
            )
            data.create_beat_aligned_track("user_edited")
            data.edit_chord_track_beat("user_edited", 0, "G")
        data.user_data = {"note": "keep"}
        data.save_to_file(analysis_dir / f"{media.stem}.json")
    return media


def _load(client, tmp_path, name="song.mp3"):
    response = client.post(
        "/load_file", json={"dirname": str(tmp_path), "filename": name}
    )
    assert response.status_code == 200


def _wait_status(client, endpoint, expected, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = client.get(endpoint).get_json()
        if payload["state"] == expected:
            return payload
        time.sleep(0.01)
    raise AssertionError(f"{endpoint} did not reach {expected}")


def test_source_command_prefers_current_venv_and_frozen_disables_it(
    monkeypatch, tmp_path
):
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    python = venv_bin / "python"
    python.write_text("", encoding="utf-8")
    helper = venv_bin / "chordflask-genlyrics"
    helper.write_text("#!/bin/sh\n", encoding="utf-8")
    helper.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    assert media_preparation.source_command("chordflask-genlyrics") == helper
    assert media_preparation.lyrics_capability()["available"] is True

    media_preparation.clear_capability_cache()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert media_preparation.lyrics_capability()["available"] is False


def test_missing_lyrics_helper_is_unavailable(monkeypatch):
    monkeypatch.setattr(media_preparation, "source_command", lambda _name: None)
    assert media_preparation.lyrics_capability()["available"] is False


def test_btc_capability_requires_source_helper_and_complete_lightweight_runtime(
    monkeypatch
):
    import chordflask_btc.runtime as btc_runtime

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(
        media_preparation, "source_command", lambda _name: Path("/venv/bin/analyze")
    )
    torch_before = sys.modules.get("torch")
    monkeypatch.setattr(
        btc_runtime, "detect_btc_runtime", lambda: {"complete": True, "missing": []}
    )
    assert media_preparation.btc_capability()["available"] is True
    assert sys.modules.get("torch") is torch_before

    media_preparation.clear_capability_cache()
    monkeypatch.setattr(
        btc_runtime,
        "detect_btc_runtime",
        lambda: {"complete": False, "missing": ["checkpoint"]},
    )
    assert media_preparation.btc_capability()["available"] is False

    media_preparation.clear_capability_cache()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert media_preparation.btc_capability()["available"] is False


@pytest.mark.parametrize(
    ("runner", "expected"),
    [
        (
            media_preparation.run_lyrics_preparation,
            ["/venv/bin/chordflask-genlyrics", "/music/A & B song.mp3"],
        ),
        (
            media_preparation.run_btc_preparation,
            [
                "/venv/bin/chordflask-analyze",
                "--analyzer",
                "btc",
                "/music/A & B song.mp3",
            ],
        ),
    ],
)
def test_source_helpers_use_safe_argv_without_shell(monkeypatch, runner, expected):
    calls = []

    def command(name):
        return Path("/venv/bin") / name

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(media_preparation, "source_command", command)
    monkeypatch.setattr(media_preparation.subprocess, "run", run)

    assert runner(Path("/music/A & B song.mp3")) == 0
    assert calls[0][0] == expected
    assert calls[0][1]["shell"] is False


def test_lyrics_prepare_refreshes_song_sheet_without_restart(tmp_path):
    app, client = _client()
    media = _song(tmp_path)
    _load(client, tmp_path)

    def runner(path):
        assert path == media
        path.with_suffix(".cho").write_text("{title: Song}\n[C]Hello\n", encoding="utf-8")
        return 0

    app.lyrics_preparation = BackgroundPreparationManager(
        capability_probe=_capability(), runner=runner, label="Lyrics"
    )
    body = {"dirname": str(tmp_path), "filename": media.name}
    response = client.post("/prepare_lyrics", json=body)
    assert response.status_code == 202
    _wait_status(client, "/lyrics_preparation_status", "ready")

    refreshed = client.post("/refresh_lyrics", json=body)
    assert refreshed.get_json()["song_view_available"] is True
    assert client.get("/get_song_sheet").status_code == 200


def test_btc_prepare_refreshes_tracks_and_preserves_existing_data(tmp_path):
    app, client = _client()
    media = _song(tmp_path, edited=True)
    _load(client, tmp_path)

    def runner(path):
        data = ChordData()
        json_path = path.parent / ".chordflask" / f"{path.stem}.json"
        data.load_from_file(json_path)
        data.set_chord_track("btc", [{"timestamp": 0.0, "chord": "Dm"}])
        data.save_to_file(json_path)
        return 0

    app.btc_preparation = BackgroundPreparationManager(
        capability_probe=_capability(), runner=runner, label="BTC"
    )
    body = {"dirname": str(tmp_path), "filename": media.name}
    assert client.post("/prepare_btc", json=body).status_code == 202
    _wait_status(client, "/btc_preparation_status", "ready")

    payload = client.post("/refresh_btc", json=body).get_json()
    assert {track["id"] for track in payload["available_chord_tracks"]} == {
        "chordino", "user_edited", "btc"
    }
    saved = ChordData()
    saved.load_from_file(tmp_path / ".chordflask" / "song.json")
    assert saved.user_data == {"note": "keep"}


def test_existing_lyrics_and_btc_results_are_ready_without_recomputation(tmp_path):
    app, client = _client()
    media = _song(tmp_path)
    media.with_suffix(".cho").write_text("{title: Song}\n[C]Hello\n", encoding="utf-8")
    data = ChordData()
    json_path = tmp_path / ".chordflask" / "song.json"
    data.load_from_file(json_path)
    data.set_chord_track("btc", [{"timestamp": 0.0, "chord": "Dm"}])
    data.save_to_file(json_path)
    _load(client, tmp_path)

    def unexpected(_path):
        raise AssertionError("an existing result must not start preparation")

    app.lyrics_preparation = BackgroundPreparationManager(
        capability_probe=_capability(), runner=unexpected, label="Lyrics"
    )
    app.btc_preparation = BackgroundPreparationManager(
        capability_probe=_capability(), runner=unexpected, label="BTC"
    )
    body = {"dirname": str(tmp_path), "filename": media.name}
    assert client.post("/prepare_lyrics", json=body).get_json()["status"] == "ready"
    assert client.post("/prepare_btc", json=body).get_json()["status"] == "ready"


@pytest.mark.parametrize("endpoint", ["/prepare_lyrics", "/prepare_btc"])
def test_prepare_rejects_non_active_media(endpoint, tmp_path):
    app, client = _client()
    _song(tmp_path)
    _song(tmp_path, "other.mp3")
    _load(client, tmp_path)
    manager = BackgroundPreparationManager(
        capability_probe=_capability(), runner=lambda _path: 0
    )
    app.lyrics_preparation = manager
    app.btc_preparation = manager

    response = client.post(
        endpoint, json={"dirname": str(tmp_path), "filename": "other.mp3"}
    )
    assert response.status_code == 409


def test_prepare_requires_valid_analysis_and_reports_background_failure(tmp_path):
    app, client = _client()
    media = _song(tmp_path, analyzed=False)
    _load(client, tmp_path)
    app.lyrics_preparation = BackgroundPreparationManager(
        capability_probe=_capability(), runner=lambda _path: 1, label="Lyrics"
    )
    body = {"dirname": str(tmp_path), "filename": media.name}
    assert client.post("/prepare_lyrics", json=body).status_code == 409

    ready_dir = tmp_path / "ready"
    ready_dir.mkdir()
    app, client = _client()
    media = _song(ready_dir)
    _load(client, ready_dir)
    app.lyrics_preparation = BackgroundPreparationManager(
        capability_probe=_capability(), runner=lambda _path: 1, label="Lyrics"
    )
    body = {"dirname": str(ready_dir), "filename": media.name}
    assert client.post("/prepare_lyrics", json=body).status_code == 202
    status = _wait_status(client, "/lyrics_preparation_status", "error")
    assert "exit code 1" in status["message"]


def test_prepare_group_is_compact_capability_driven_and_desktop_only():
    _, client = _client()
    body = client.get("/").get_data(as_text=True)
    assert 'id="prepareGroup" class="prepare-group" hidden' in body
    for action in ("Lyrics", "Btc", "Stems"):
        assert f'id="prepare{action}Button"' in body
    assert "action.button.hidden = !visible" in body
    assert "prepareGroup.hidden = !anyVisible" in body
    assert "let desktopPrepare = window.matchMedia('(min-width: 1024px)');" in body
    assert ".prepare-group {\n      display: none;" in body
    assert "@media (min-width: 1024px)" in body
    assert ".prepare-group:not([hidden])" in body
    assert 'id="stemsButton"' in body
    assert 'onclick="toggleStems()">STEMS</button>' in body
