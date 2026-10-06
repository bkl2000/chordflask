"""Exact media names take priority over legacy display-string decoding."""

import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from chordflask.app import FlaskMP4App
from chordflask.filerepr import FileRepr
from chordflask_base import DEFAULT_CHORD_TRACK, DEFAULT_RHYTHM_TRACK, ChordData


@pytest.fixture
def gui(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDFLASK_QUEUE_DIR", str(tmp_path / "queue"))
    app = FlaskMP4App(roots=str(tmp_path))
    return app, app.app.test_client()


def analyzed_song(root, name):
    media = root / name
    media.write_bytes(b"synthetic media")
    file_repr = FileRepr(str(media), create=True)
    data = ChordData()
    data.set_chord_track(DEFAULT_CHORD_TRACK, [{"timestamp": 0.0, "chord": "C"}])
    data.set_rhythm_track(DEFAULT_RHYTHM_TRACK, beat_times=[0.0])
    data.save_to_file(file_repr.get("json"))
    return media


@pytest.mark.parametrize("name", [
    "Artist | Title.mp3",
    "Artist.mp3 | Title.mp3",
    "Artist | Title | Live.mp3",
])
def test_load_uses_exact_pipe_filename_with_prefix_collision(tmp_path, gui, name):
    app, client = gui
    analyzed_song(tmp_path, "Artist.mp3")
    media = analyzed_song(tmp_path, name)
    response = client.post("/load_file", json={"dirname": str(tmp_path), "filename": name})
    assert response.status_code == 200
    assert response.get_json()["status"] == "ready"
    assert response.get_json()["mp4_file"] == str(media)
    assert app.analysis_queue.status()["pending"] == []
    assert client.get("/video").get_data() == media.read_bytes()


def test_literal_filename_lists_and_queues_exact_path(tmp_path, gui):
    app, client = gui
    name = "Artist | Title.mp3"
    media = tmp_path / name
    media.write_bytes(b"synthetic media")
    analyzed_song(tmp_path, "Artist.mp3")
    structured = client.post("/list_files", json={"dirname": str(tmp_path), "structured": True})
    assert name in [entry["name"] for entry in structured.get_json()["files"]]
    legacy = client.post("/list_files", json={"dirname": str(tmp_path)})
    assert f"{name} | 0M" in legacy.get_json()
    batch = client.post("/enqueue_batch", json={
        "dirname": str(tmp_path), "filenames": [name], "limit": 1,
    })
    assert batch.status_code == 200
    assert batch.get_json()["queued_paths"] == [str(media)]
    opened = client.post("/load_file", json={"dirname": str(tmp_path), "filename": name})
    assert opened.get_json()["mp4_file"] == str(media)
    assert len(app.analysis_queue.status()["pending"]) == 1


@pytest.mark.parametrize("route,manager", [
    ("/reanalyze", None),
    ("/prepare_stems", "stem_preparation"),
    ("/prepare_btc", "btc_preparation"),
    ("/prepare_lyrics", "lyrics_preparation"),
])
def test_active_media_actions_use_literal_filename(tmp_path, gui, route, manager):
    app, client = gui
    media = analyzed_song(tmp_path, "Artist | Title.mp3")
    analyzed_song(tmp_path, "Artist.mp3")
    body = {"dirname": str(tmp_path), "filename": media.name}
    assert client.post("/load_file", json=body).get_json()["status"] == "ready"
    calls = []

    def start(path):
        calls.append(path)
        return {"status": "accepted"}

    if manager:
        setattr(app, manager, SimpleNamespace(start=start))
    response = client.post(route, json=body)
    if manager:
        assert response.status_code == 202
        assert calls == [media]
    else:
        assert response.status_code == 200
        pending = app.analysis_queue.status()["pending"]
        assert pending[0]["path"] == str(media)
        assert pending[0]["force"] is True


@pytest.mark.parametrize("name", ["song.mp3", "Artist | Title.mp3"])
def test_legacy_display_fallback_preserves_full_media_name(tmp_path, gui, name):
    _, client = gui
    media = analyzed_song(tmp_path, name)
    response = client.post("/load_file", json={
        "dirname": str(tmp_path), "filename": f"{name} | 12M",
    })
    assert response.status_code == 200
    assert response.get_json()["status"] == "ready"
    assert response.get_json()["mp4_file"] == str(media)


@pytest.mark.parametrize("filename", [
    "../song.mp3", "../song.mp3 | 12M", "song.mp3 | ../12M",
    "song.txt", "song.mp3 | arbitrary", "song.mp3 | 12M.txt",
])
def test_invalid_names_do_not_resolve_by_prefix(tmp_path, gui, filename):
    app, client = gui
    analyzed_song(tmp_path, "song.mp3")
    (tmp_path / "song.txt").write_bytes(b"unsupported")
    response = client.post("/load_file", json={
        "dirname": str(tmp_path), "filename": filename,
    })
    assert response.status_code == 400
    assert app.analysis_queue.status()["pending"] == []


def test_existing_unsupported_exact_entry_does_not_fall_back(tmp_path, gui):
    app, client = gui
    analyzed_song(tmp_path, "song.mp3")
    (tmp_path / "song.mp3 | 12M").write_bytes(b"unsupported exact file")
    with pytest.raises(ValueError, match="Only .mp3"):
        app._existing_media_file(str(tmp_path), "song.mp3 | 12M")
    response = client.post("/load_file", json={
        "dirname": str(tmp_path), "filename": "song.mp3 | 12M",
    })
    assert response.status_code == 400


def test_missing_literal_filename_does_not_open_existing_prefix(tmp_path, gui):
    app, client = gui
    analyzed_song(tmp_path, "song.mp3")
    response = client.post("/load_file", json={
        "dirname": str(tmp_path), "filename": "song.mp3 | Missing.mp3",
    })
    assert response.status_code == 404
    assert app.analysis_queue.status()["pending"] == []


@pytest.mark.parametrize("names,requested,expected", [
    (["Artist.mp3", "Artist | Title.mp3"], "Artist | Title.mp3", "Artist | Title.mp3"),
    (["Artist.mp3", "Artist.mp3 | Title.mp3"], "Artist.mp3 | Title.mp3", "Artist.mp3 | Title.mp3"),
    (["first.mp3", "song.mp3"], "song.mp3 | 12M", "song.mp3"),
    (["first.mp3", "Artist | Title.mp3"], "Artist | Title.mp3 | 12M", "Artist | Title.mp3"),
    (["first.mp3", "song.mp3"], "song.mp3 | arbitrary", "first.mp3"),
    (["first.mp3", "song.mp3"], "missing.mp3", "first.mp3"),
    ([], "missing.mp3", ""),
])
def test_browser_selection_is_exact_first(gui, names, requested, expected):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js unavailable for focused browser-function execution")
    _, client = gui
    body = client.get("/").get_data(as_text=True)
    start = body.index("    function selectPreferredFile(")
    end = body.index("\n    function ", start + 1)
    function = body[start:end]
    script = "\n".join([
        "const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));",
        "let currentFiles = input.names.map(name => ({name}));",
        "let selectedFileName = '';",
        function,
        "selectPreferredFile(input.requested);",
        "process.stdout.write(JSON.stringify(selectedFileName));",
    ])
    result = subprocess.run(
        [node, "-e", script], input=json.dumps({"names": names, "requested": requested}),
        text=True, capture_output=True, check=True, timeout=5,
    )
    assert json.loads(result.stdout) == expected
