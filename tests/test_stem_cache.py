"""Optional ``--stem-cache`` browser HTTP-cache experiment for stem audio."""

import os
from pathlib import Path

import pytest


from chordflask.app import CLIENT_COOKIE, FlaskMP4App, _parse_cli_args
from chordflask_base import ChordData, DEMUCS_STEM_NAMES
from chordflask.mp4playerflask import STEMS_AUDIO_SET_ID


@pytest.fixture(autouse=True)
def isolate_default_analysis_queue(monkeypatch, tmp_path):
    monkeypatch.setenv("CHORDFLASK_QUEUE_DIR", str(tmp_path / "default-queue"))


def _stems_rel_dir():
    return Path(".chordflask") / "stems" / "demucs" / "htdemucs" / "song" / "generation"


def _audio_set():
    rel = _stems_rel_dir()
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


def _write_flac(tmp_path, stem, content=b"flac-bytes"):
    path = tmp_path / _stems_rel_dir() / f"{stem}.flac"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _write_analyzed_song(tmp_path, name="song.mp3", stems=True):
    media = tmp_path / name
    media.write_bytes(b"not decoded by this route")
    analysis_dir = tmp_path / ".chordflask"
    analysis_dir.mkdir(exist_ok=True)
    data = ChordData()
    data.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "C"}])
    data.set_rhythm_track(
        "qm_barbeattracker", bpm=120, meter_signature=4,
        beat_times=[0.0, 0.5, 1.0, 1.5], beat_numbers=[1, 2, 3, 4],
    )
    if stems:
        data.set_audio_track(STEMS_AUDIO_SET_ID, _audio_set())
    data.save_to_file(analysis_dir / f"{media.stem}.json")
    return media


def _make_client(stem_cache):
    app = FlaskMP4App(stem_cache=stem_cache)
    client = app.app.test_client()
    app.clients.get_or_create("test-client")
    client.set_cookie(CLIENT_COOKIE, "test-client")
    return app, client


def _load_stems(client, tmp_path, name="song.mp3"):
    response = client.post("/load_file", json={"dirname": str(tmp_path), "filename": name})
    assert response.status_code == 200
    payload = response.get_json()
    return payload.get("stems")


# ── CLI parsing and propagation ──────────────────────────────────────


def test_stem_cache_flag_is_parsed():
    assert _parse_cli_args(["--stem-cache"]).stem_cache is True
    assert _parse_cli_args([]).stem_cache is False


def test_stem_cache_propagates_to_app():
    assert FlaskMP4App(stem_cache=True)._FlaskMP4App__stem_cache is True
    assert FlaskMP4App()._FlaskMP4App__stem_cache is False


# ── default mode: no-store, no versions ───────────────────────────────


def test_default_mode_keeps_no_store_and_no_versions(tmp_path):
    _write_analyzed_song(tmp_path)
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(tmp_path, stem)
    _, client = _make_client(stem_cache=False)

    stems = _load_stems(client, tmp_path)
    assert "versions" not in stems

    response = client.get("/stem/vocals")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"


# ── cache mode: cacheable headers + version tokens ────────────────────


def test_cache_mode_serves_cacheable_stem_headers(tmp_path):
    _write_analyzed_song(tmp_path)
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(tmp_path, stem)
    _, client = _make_client(stem_cache=True)
    _load_stems(client, tmp_path)

    response = client.get("/stem/vocals")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, max-age=86400"
    # Werkzeug send_file conditional/range behavior remains intact.
    assert "ETag" in response.headers
    assert "Last-Modified" in response.headers
    assert "Accept-Ranges" in response.headers


def test_cache_mode_exposes_version_tokens(tmp_path):
    _write_analyzed_song(tmp_path)
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(tmp_path, stem)
    _, client = _make_client(stem_cache=True)

    stems = _load_stems(client, tmp_path)
    assert set(stems["versions"]) == set(DEMUCS_STEM_NAMES)
    for token in stems["versions"].values():
        mtime_ns, size = token.split("-")
        assert int(mtime_ns) > 0
        assert int(size) > 0


def test_unchanged_stem_has_stable_version(tmp_path):
    _write_analyzed_song(tmp_path)
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(tmp_path, stem)
    _, client = _make_client(stem_cache=True)

    first = _load_stems(client, tmp_path)
    second = _load_stems(client, tmp_path)

    assert first["versions"] == second["versions"]


def test_touched_stem_changes_version(tmp_path):
    _write_analyzed_song(tmp_path)
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(tmp_path, stem)
    _, client = _make_client(stem_cache=True)

    before = _load_stems(client, tmp_path)

    vocals = tmp_path / _stems_rel_dir() / "vocals.flac"
    os.utime(vocals, None)

    after = _load_stems(client, tmp_path)

    assert after["versions"]["vocals"] != before["versions"]["vocals"]


def test_replaced_stem_changes_version(tmp_path):
    _write_analyzed_song(tmp_path)
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(tmp_path, stem)
    _, client = _make_client(stem_cache=True)

    before = _load_stems(client, tmp_path)

    # Real Demucs-style regeneration: write a fresh file and atomically replace.
    vocals = tmp_path / _stems_rel_dir() / "vocals.flac"
    tmp = vocals.with_suffix(".flac.new")
    tmp.write_bytes(b"regenerated flac bytes of different length")
    os.replace(tmp, vocals)

    after = _load_stems(client, tmp_path)

    assert after["versions"]["vocals"] != before["versions"]["vocals"]
    # Unrelated stems keep their version.
    assert after["versions"]["drums"] == before["versions"]["drums"]


# ── Range + security unchanged in cache mode ─────────────────────────


def test_cache_mode_preserves_range_requests(tmp_path):
    _write_analyzed_song(tmp_path)
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(tmp_path, stem, content=b"0123456789" * 100)
    _, client = _make_client(stem_cache=True)
    _load_stems(client, tmp_path)

    response = client.get("/stem/vocals", headers={"Range": "bytes=0-9"})

    assert response.status_code == 206
    assert response.get_data() == b"0123456789"
    assert response.headers["Accept-Ranges"] == "bytes"
    assert response.headers["Cache-Control"] == "private, max-age=86400"


def test_cache_mode_keeps_path_security(tmp_path):
    _write_analyzed_song(tmp_path)
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(tmp_path, stem)
    _, client = _make_client(stem_cache=True)

    for name in ("..%2F..%2Fetc%2Fpasswd", "vocals%2F..%2F..", "..", "."):
        assert client.get(f"/stem/{name}").status_code == 404


# ── multi-client isolation in cache mode ─────────────────────────────


def test_cache_mode_clients_serve_own_stems(tmp_path):
    _write_analyzed_song(tmp_path, name="with-stems.mp3", stems=True)
    _write_analyzed_song(tmp_path, name="plain.mp3", stems=False)
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(tmp_path, stem)
    app = FlaskMP4App(stem_cache=True)
    a = app.app.test_client()
    b = app.app.test_client()
    app.clients.get_or_create("a")
    app.clients.get_or_create("b")
    a.set_cookie(CLIENT_COOKIE, "a")
    b.set_cookie(CLIENT_COOKIE, "b")

    a.post("/load_file", json={"dirname": str(tmp_path), "filename": "with-stems.mp3"})
    b.post("/load_file", json={"dirname": str(tmp_path), "filename": "plain.mp3"})

    assert a.get("/stem/vocals").status_code == 200
    assert b.get("/stem/vocals").status_code == 404
