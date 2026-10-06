"""Lyrics snapshot freshness without NLP inference or a real runtime rebuild."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from chordflask import media_preparation
from chordflask.app import CLIENT_COOKIE, FlaskMP4App
from chordflask.filerepr import FileRepr
from chordflask_base import ChordData
from chordflask_lyrics import freshness

ROOT = Path(__file__).resolve().parents[1]


def copy_scope(destination):
    for package in ("chordflask_lyrics", "chordflask_base"):
        shutil.copytree(ROOT / package, destination / package, ignore=shutil.ignore_patterns("__pycache__"))
    for name in freshness.CORE_FILES:
        path = destination / "chordflask" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "chordflask" / name, path)


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    source = tmp_path / "source"
    copy_scope(source)
    (source / "VERSION").write_text("0.9.18\n")
    runtime = tmp_path / "runtime"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(runtime)], check=True, timeout=10)
    python = runtime / "bin/python"
    site = Path(subprocess.run(
        [str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        capture_output=True, text=True, check=True,
    ).stdout.strip())
    copy_scope(site)
    helper = runtime / "bin/chordflask-genlyrics"
    helper.write_text(f"#!{python}\nfrom chordflask_lyrics.cli import main\nraise SystemExit(main())\n")
    helper.chmod(0o755)
    expected = freshness.fingerprint(source)
    result = subprocess.run(
        [str(python), "-I", "-B", str(ROOT / "chordflask_lyrics/freshness.py"),
         "record", "--source", str(source), "--runtime", str(runtime), "--expected", expected],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    monkeypatch.setenv("CHORDFLASK_LYRICS_VENV", str(runtime))
    monkeypatch.setenv("CHORDFLASK_QUEUE_DIR", str(tmp_path / "queue"))
    monkeypatch.setattr(media_preparation, "__file__", str(source / "chordflask/media_preparation.py"))
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    return source, runtime, site


def test_matching_snapshot_is_available(snapshot):
    source, runtime, _ = snapshot
    assert freshness.read_identity(runtime) == freshness.fingerprint(source)
    assert media_preparation.lyrics_capability()["available"] is True


def test_default_runtime_is_verified(snapshot, monkeypatch):
    _, runtime, _ = snapshot
    monkeypatch.delenv("CHORDFLASK_LYRICS_VENV")
    monkeypatch.setattr(media_preparation, "DEFAULT_LYRICS_VENV", runtime)
    assert media_preparation.lyrics_capability()["available"] is True


def test_same_version_source_edit_is_detected_immediately(snapshot):
    source, _, _ = snapshot
    assert media_preparation.lyrics_capability()["available"] is True
    path = source / "chordflask_lyrics/align.py"
    path.write_bytes(path.read_bytes() + b"\n# same-version alignment edit\n")
    assert (source / "VERSION").read_text() == "0.9.18\n"
    result = media_preparation.lyrics_capability()
    assert result["available"] is False
    assert result["needs_update"] is True
    assert "setup-lyrics.sh" in result["reason"]


@pytest.mark.parametrize("marker", [None, "invalid JSON", "[]", '{}',
                                      '{"format":true,"sha256":"' + "a" * 64 + '"}',
                                      '{"format":1,"sha256":123}',
                                      '{"format":1,"sha256":"bad"}'])
def test_missing_or_malformed_marker_requires_update(snapshot, marker):
    _, runtime, _ = snapshot
    path = runtime / freshness.MARKER_PATH
    if marker is None:
        path.unlink()
    else:
        path.write_text(marker)
    result = media_preparation.lyrics_capability()
    assert result["available"] is False
    assert result["needs_update"] is True


def test_marker_does_not_hide_installed_code_changes(snapshot):
    _, _, site = snapshot
    assert media_preparation.lyrics_capability()["available"]
    path = site / "chordflask_base/model.py"
    path.write_bytes(path.read_bytes() + b"\n# modified installed core\n")
    assert media_preparation.lyrics_capability()["needs_update"]


def test_unverifiable_interpreter_requires_update(snapshot):
    _, runtime, _ = snapshot
    (runtime / "bin/python").unlink()
    assert media_preparation.lyrics_capability()["needs_update"]


def test_unrelated_files_do_not_change_identity(snapshot):
    source, runtime, _ = snapshot
    for name in ("docs/notes.md", "tests/test_example.py", "chordflask/app.py",
                 "chordflask/templates/home.html", "chordflask_lyrics/__pycache__/generated.py",
                 "chordflask_lyrics/tests/test_internal.py", ".git/config", "data/model.pt"):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("irrelevant to Lyrics runtime")
    assert freshness.fingerprint(source) == freshness.read_identity(runtime)
    assert media_preparation.lyrics_capability()["available"]


def test_missing_scoped_source_is_unverifiable(snapshot):
    source, _, _ = snapshot
    (source / "chordflask/playbackview.py").unlink()
    assert media_preparation.lyrics_capability()["needs_update"]


def test_added_lyrics_module_changes_identity(snapshot):
    source, _, _ = snapshot
    (source / "chordflask_lyrics/new_helper.py").write_text("VALUE = 1\n")
    assert media_preparation.lyrics_capability()["needs_update"]


def test_lazy_output_parser_is_in_fingerprint_scope(snapshot):
    source, _, _ = snapshot
    path = source / "chordflask/chordpro_song.py"
    path.write_bytes(path.read_bytes() + b"\n# same-version output parser edit\n")
    assert media_preparation.lyrics_capability()["needs_update"]


def test_frozen_external_helper_behavior_does_not_import_freshness(snapshot, monkeypatch):
    _, runtime, _ = snapshot
    (runtime / freshness.MARKER_PATH).unlink()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(freshness, "check_runtime", lambda *args: pytest.fail("frozen source comparison"))
    assert media_preparation.lyrics_capability()["available"] is True


def test_source_change_during_setup_preserves_marker(snapshot):
    source, runtime, _ = snapshot
    marker = runtime / freshness.MARKER_PATH
    original = marker.read_bytes()
    expected = freshness.fingerprint(source)
    (source / "chordflask_lyrics/new_helper.py").write_text("VALUE = 1\n")
    result = subprocess.run(
        [str(runtime / "bin/python"), "-I", "-B", str(ROOT / "chordflask_lyrics/freshness.py"),
         "record", "--source", str(source), "--runtime", str(runtime), "--expected", expected],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert marker.read_bytes() == original
    assert list(marker.parent.glob(".source-identity-*")) == []


def test_failed_atomic_write_preserves_marker(snapshot, monkeypatch):
    source, runtime, _ = snapshot
    marker = runtime / freshness.MARKER_PATH
    original = marker.read_bytes()
    expected = freshness.fingerprint(source)
    monkeypatch.setattr(freshness, "installed_fingerprint", lambda: expected)

    def fail_replace(*args):
        raise OSError("replace failed")

    monkeypatch.setattr(freshness.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        freshness.record_identity(runtime, source, expected)
    assert marker.read_bytes() == original
    assert list(marker.parent.glob(".source-identity-*")) == []


def test_stale_runtime_is_blocked_before_subprocess(snapshot, monkeypatch):
    source, _, _ = snapshot
    (source / "chordflask_lyrics/new_helper.py").write_text("VALUE = 1\n")
    monkeypatch.setattr(media_preparation, "_run_helper", lambda *args: pytest.fail("stale generator ran"))
    with pytest.raises(RuntimeError, match="needs update"):
        media_preparation.run_lyrics_preparation(source / "unused.mp3")


def test_stale_gui_status_and_prepare_guidance(snapshot):
    source, runtime, _ = snapshot
    (runtime / freshness.MARKER_PATH).unlink()
    media = source / "song.mp3"
    media.write_bytes(b"synthetic media")
    file_repr = FileRepr(str(media), create=True)
    data = ChordData()
    data.set_base_chords([{"timestamp": 0.0, "chord": "C"}], beat_times=[0.0])
    data.save_to_file(file_repr.get("json"))
    app = FlaskMP4App(roots=str(source))
    client = app.app.test_client()
    body = {"dirname": str(source), "filename": media.name}
    assert client.post("/load_file", json=body).get_json()["status"] == "ready"
    status = client.get("/lyrics_preparation_status").get_json()
    assert status["available"] is False
    assert status["state"] == "unavailable"
    assert status["needs_update"] is True
    assert "setup-lyrics.sh" in status["message"]
    response = client.post("/prepare_lyrics", json=body)
    assert response.status_code == 409
    assert "needs update" in response.get_json()["error"]
    template = client.get("/").get_data(as_text=True)
    assert "action.needsUpdate = data.needs_update === true" in template
    assert "showPrepareToolbarStatus(data.message, 0)" in template

    # A previous completed job must not bypass the current freshness decision.
    token = client.get_cookie(CLIENT_COOKIE).value
    state = app.clients.get(token)
    app.lyrics_preparation._job = {
        "key": app.lyrics_preparation.media_key(media), "state": "ready", "cuda": False, "message": ""
    }
    assert state.file_repr is not None
    assert client.get("/lyrics_preparation_status").get_json()["available"] is False


def test_check_script_detects_missing_marker(snapshot):
    _, runtime, _ = snapshot
    (runtime / freshness.MARKER_PATH).unlink()
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/lyrics-check.sh")],
        env={**os.environ, "CHORDFLASK_LYRICS_VENV": str(runtime), "PYTHONDONTWRITEBYTECODE": "1"},
        text=True, capture_output=True,
    )
    assert result.returncode == 1
    assert "needs update" in result.stdout
    assert "setup-lyrics.sh" in result.stdout


def test_check_script_accepts_verified_snapshot(snapshot):
    _, runtime, site = snapshot
    # Simulate importable optional dependencies; no NLP inference runs.
    for name in ("onnxruntime", "pythainlp"):
        (site / f"{name}.py").write_text("# dependency stub\n")
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/lyrics-check.sh")],
        env={**os.environ, "CHORDFLASK_LYRICS_VENV": str(runtime), "PYTHONDONTWRITEBYTECODE": "1"},
        text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Lyrics freshness: CURRENT" in result.stdout
