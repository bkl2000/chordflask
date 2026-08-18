import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
FLASK_DIR = REPO_ROOT / "flask"

if str(FLASK_DIR) not in sys.path:
    sys.path.insert(0, str(FLASK_DIR))

from chordflask import FlaskMP4App
from chordflask_base import ChordData, DEMUCS_STEM_NAMES
from mp4playerflask import STEMS_AUDIO_SET_ID


@pytest.fixture(autouse=True)
def isolate_default_analysis_queue(monkeypatch, tmp_path):
    monkeypatch.setenv("CHORDFLASK_QUEUE_DIR", str(tmp_path / "default-queue"))


def _stems_rel_dir():
    return Path(".chordflask") / "stems" / "demucs" / "htdemucs" / "song" / "generation"


def _audio_set(rel_dir):
    tracks = {}
    for index, stem in enumerate(DEMUCS_STEM_NAMES):
        tracks[stem] = {
            "path": str(rel_dir / f"{stem}.flac"),
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


def _write_flac(media_root, stem, content=b"flac-bytes"):
    path = media_root / _stems_rel_dir() / f"{stem}.flac"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _write_analyzed_song(tmp_path, *, name="song.mp3", with_audio=True, set_data=None):
    media = tmp_path / name
    media.write_bytes(b"not decoded by this route")
    analysis_dir = tmp_path / ".chordflask"
    analysis_dir.mkdir(exist_ok=True)
    data = ChordData()
    if with_audio:
        data.set_audio_track(STEMS_AUDIO_SET_ID, set_data or _audio_set(_stems_rel_dir()))
    data.save_to_file(analysis_dir / f"{media.stem}.json")
    return media


def _load_song(client, tmp_path, name="song.mp3"):
    return client.post(
        "/load_file",
        json={"dirname": str(tmp_path), "filename": name},
    )


# ── audio_stems_state unit behavior ─────────────────────────────────


def test_audio_stems_state_none_without_set():
    from mp4playerflask import MP4PlayerFlask

    class _Stub:
        pass

    player = _Stub()
    player.chord_data = ChordData()
    assert MP4PlayerFlask.audio_stems_state(player) is None


def _player_stub(media):
    from filerepr import FileRepr

    class _Stub:
        pass

    player = _Stub()
    player.file_repr = FileRepr(str(media))
    player.chord_data = ChordData()
    return player


def test_audio_stems_state_reports_complete_set(tmp_path):
    from mp4playerflask import MP4PlayerFlask

    media = tmp_path / "song.mp3"
    media.write_bytes(b"media")
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(tmp_path, stem)
    player = _player_stub(media)
    player.chord_data.set_audio_track(STEMS_AUDIO_SET_ID, _audio_set(_stems_rel_dir()))
    assert MP4PlayerFlask.audio_stems_state(player) == {
        "set_id": STEMS_AUDIO_SET_ID,
        "stems": list(DEMUCS_STEM_NAMES),
    }


def test_audio_stems_state_none_when_one_flac_deleted(tmp_path):
    from mp4playerflask import MP4PlayerFlask

    media = tmp_path / "song.mp3"
    media.write_bytes(b"media")
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(tmp_path, stem)
    (tmp_path / _stems_rel_dir() / "vocals.flac").unlink()
    player = _player_stub(media)
    player.chord_data.set_audio_track(STEMS_AUDIO_SET_ID, _audio_set(_stems_rel_dir()))
    assert MP4PlayerFlask.audio_stems_state(player) is None


def test_audio_stems_state_none_when_multiple_flacs_missing(tmp_path):
    from mp4playerflask import MP4PlayerFlask

    media = tmp_path / "song.mp3"
    media.write_bytes(b"media")
    _write_flac(tmp_path, "bass")
    player = _player_stub(media)
    player.chord_data.set_audio_track(STEMS_AUDIO_SET_ID, _audio_set(_stems_rel_dir()))
    assert MP4PlayerFlask.audio_stems_state(player) is None


def test_audio_stems_state_none_for_symlink_or_outside_path(tmp_path):
    from mp4playerflask import MP4PlayerFlask

    media = tmp_path / "song.mp3"
    media.write_bytes(b"media")
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(tmp_path, stem)
    outside = tmp_path / "outside.flac"
    outside.write_bytes(b"escaped")
    vocals = tmp_path / _stems_rel_dir() / "vocals.flac"
    vocals.unlink()
    vocals.symlink_to(outside)
    assert MP4PlayerFlask.audio_stems_state(_player_stub(media)) is None

    drums = tmp_path / _stems_rel_dir() / "drums.flac"
    drums.unlink()
    outside_set = _audio_set(_stems_rel_dir())
    outside_set["tracks"]["drums"]["path"] = "../../outside.flac"
    player = _player_stub(media)
    player.chord_data._add_raw_audio_track(STEMS_AUDIO_SET_ID, outside_set)
    assert MP4PlayerFlask.audio_stems_state(player) is None


def test_audio_stems_state_none_for_malformed_stem_path(tmp_path):
    from mp4playerflask import MP4PlayerFlask

    media = tmp_path / "song.mp3"
    media.write_bytes(b"media")
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(tmp_path, stem)
    for bad_path in (None, 42, ""):
        set_data = _audio_set(_stems_rel_dir())
        set_data["tracks"]["vocals"]["path"] = bad_path
        player = _player_stub(media)
        player.chord_data._add_raw_audio_track(STEMS_AUDIO_SET_ID, set_data)
        assert MP4PlayerFlask.audio_stems_state(player) is None


def test_audio_stems_state_none_for_missing_tracks_dict():
    from mp4playerflask import MP4PlayerFlask

    class _Stub:
        pass

    player = _Stub()
    player.chord_data = ChordData()
    malformed = _audio_set(_stems_rel_dir())
    malformed["tracks"] = {}
    player.chord_data._add_raw_audio_track(STEMS_AUDIO_SET_ID, malformed)
    assert MP4PlayerFlask.audio_stems_state(player) is None


def test_audio_stems_state_none_for_non_flac_stem():
    from mp4playerflask import MP4PlayerFlask

    class _Stub:
        pass

    player = _Stub()
    player.chord_data = ChordData()
    malformed = _audio_set(_stems_rel_dir())
    malformed["tracks"]["vocals"]["format"] = "wav"
    player.chord_data._add_raw_audio_track(STEMS_AUDIO_SET_ID, malformed)
    assert MP4PlayerFlask.audio_stems_state(player) is None


# ── /load_file stems payload ─────────────────────────────────────────


def test_load_file_reports_stems_for_complete_set(tmp_path):
    _write_analyzed_song(tmp_path)
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(tmp_path, stem)
    client = FlaskMP4App().app.test_client()

    response = _load_song(client, tmp_path)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ready"
    assert payload["stems"] == {"set_id": STEMS_AUDIO_SET_ID, "stems": list(DEMUCS_STEM_NAMES)}


def test_load_file_reports_no_stems_without_audio_tracks(tmp_path):
    _write_analyzed_song(tmp_path, with_audio=False)
    client = FlaskMP4App().app.test_client()

    response = _load_song(client, tmp_path)

    assert response.status_code == 200
    assert response.get_json()["stems"] is None


def test_load_file_incomplete_set_is_unavailable(tmp_path):
    import json

    media = tmp_path / "song.mp3"
    media.write_bytes(b"not decoded by this route")
    analysis_dir = tmp_path / ".chordflask"
    analysis_dir.mkdir(exist_ok=True)
    incomplete = _audio_set(_stems_rel_dir())
    del incomplete["tracks"]["vocals"]
    raw = {
        "schema_version": 3,
        "prefer_flats": True,
        "transpose": 0,
        "user_data": {},
        "chord_tracks": {},
        "rhythm_tracks": {},
        "audio_tracks": {STEMS_AUDIO_SET_ID: incomplete},
    }
    (analysis_dir / "song.json").write_text(json.dumps(raw), encoding="utf-8")

    client = FlaskMP4App().app.test_client()
    response = _load_song(client, tmp_path)

    assert response.status_code == 200
    assert response.get_json()["stems"] is None


def test_load_file_reports_no_stems_when_flac_deleted(tmp_path):
    _write_analyzed_song(tmp_path)
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(tmp_path, stem)
    (tmp_path / _stems_rel_dir() / "vocals.flac").unlink()
    client = FlaskMP4App().app.test_client()

    response = _load_song(client, tmp_path)

    assert response.status_code == 200
    assert response.get_json()["stems"] is None


def test_stem_availability_checks_leave_json_unchanged(tmp_path):
    _write_analyzed_song(tmp_path)
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(tmp_path, stem)
    json_file = tmp_path / ".chordflask" / "song.json"
    before = json_file.read_bytes()
    client = FlaskMP4App().app.test_client()
    _load_song(client, tmp_path)
    client.get("/stem/vocals")
    (tmp_path / _stems_rel_dir() / "drums.flac").unlink()
    _load_song(client, tmp_path)
    client.get("/stem/drums")
    assert json_file.read_bytes() == before


# ── secure FLAC serving ──────────────────────────────────────────────


def test_serve_stem_returns_flac_for_valid_stem(tmp_path):
    _write_analyzed_song(tmp_path)
    content = {stem: f"{stem}-flac".encode() for stem in DEMUCS_STEM_NAMES}
    for stem, raw in content.items():
        _write_flac(tmp_path, stem, raw)
    client = FlaskMP4App().app.test_client()
    _load_song(client, tmp_path)

    for stem in DEMUCS_STEM_NAMES:
        response = client.get(f"/stem/{stem}")
        assert response.status_code == 200, response.get_data(as_text=True)
        assert response.mimetype == "audio/flac"
        assert response.get_data() == content[stem]


def test_serve_stem_rejects_unknown_stem_name(tmp_path):
    _write_analyzed_song(tmp_path)
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(tmp_path, stem)
    client = FlaskMP4App().app.test_client()
    _load_song(client, tmp_path)

    response = client.get("/stem/guitar")
    assert response.status_code == 404


def test_serve_stem_rejects_path_traversal_name(tmp_path):
    _write_analyzed_song(tmp_path)
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(tmp_path, stem)
    client = FlaskMP4App().app.test_client()
    _load_song(client, tmp_path)

    for name in ("..%2F..%2Fetc%2Fpasswd", "vocals%2F..%2F..", "..", "."):
        response = client.get(f"/stem/{name}")
        assert response.status_code == 404


def test_serve_stem_rejects_missing_flac(tmp_path):
    _write_analyzed_song(tmp_path)
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(tmp_path, stem)
    (tmp_path / _stems_rel_dir() / "vocals.flac").unlink()
    client = FlaskMP4App().app.test_client()
    _load_song(client, tmp_path)

    response = client.get("/stem/vocals")
    assert response.status_code == 404


def test_serve_stem_rejects_symlink_escape(tmp_path):
    _write_analyzed_song(tmp_path)
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(tmp_path, stem)
    outside = tmp_path / "outside.flac"
    outside.write_bytes(b"escaped")
    vocals = tmp_path / _stems_rel_dir() / "vocals.flac"
    vocals.unlink()
    vocals.symlink_to(outside)
    client = FlaskMP4App().app.test_client()
    _load_song(client, tmp_path)

    response = client.get("/stem/vocals")
    assert response.status_code == 404


def test_serve_stem_requires_loaded_song(tmp_path):
    client = FlaskMP4App().app.test_client()
    response = client.get("/stem/vocals")
    assert response.status_code == 404
