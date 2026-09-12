"""Focused tests for on-demand Demucs stem preparation and the UI wiring."""

import threading
import time
from pathlib import Path

import pytest

from chordflask import stem_preparation
from chordflask.app import CLIENT_COOKIE, FlaskMP4App
from chordflask.mp4playerflask import STEMS_AUDIO_SET_ID
from chordflask.stem_preparation import StemPreparationManager
from chordflask_base import ChordData, DEMUCS_STEM_NAMES


TEST_CLIENT_ID = "stem-prep-client"


@pytest.fixture(autouse=True)
def isolate_default_analysis_queue(monkeypatch, tmp_path):
    monkeypatch.setenv("CHORDFLASK_QUEUE_DIR", str(tmp_path / "default-queue"))


def javascript_function(body, name):
    signatures = (f"    function {name}(", f"    async function {name}(")
    starts = [body.find(signature) for signature in signatures]
    start = min(index for index in starts if index >= 0)
    ends = [
        body.find(signature, start + 1)
        for signature in ("\n    function ", "\n    async function ")
    ]
    end = min(index for index in ends if index >= 0)
    return body[start:end if end >= 0 else len(body)]


# ── capability detection ─────────────────────────────────────────────


def _gui_probe(*, available=True, cuda=True, reason=""):
    return lambda: {"available": available, "cuda": cuda, "reason": reason}


def test_gui_capability_is_cuda_informational(monkeypatch):
    monkeypatch.setattr(
        stem_preparation,
        "probe_capability",
        lambda **kwargs: {"available": True, "cuda": False, "reason": ""},
    )
    capability = stem_preparation.gui_capability()
    assert capability["available"] is True
    assert capability["cuda"] is False

    monkeypatch.setattr(
        stem_preparation,
        "probe_capability",
        lambda **kwargs: {"available": True, "cuda": True, "reason": ""},
    )
    assert stem_preparation.gui_capability()["available"] is True

    monkeypatch.setattr(
        stem_preparation,
        "probe_capability",
        lambda **kwargs: {"available": False, "cuda": False, "reason": "missing"},
    )
    assert stem_preparation.gui_capability()["available"] is False


def test_capability_uses_producer_runtime_probe(monkeypatch):
    import chordflask_demucs.runtime as demucs_runtime

    info = demucs_runtime.RuntimeInfo(
        Path("/runtime"), Path("/runtime/bin/python"), "4.0.1", "2.10.0", True
    )
    monkeypatch.setattr(demucs_runtime, "require_runtime", lambda: info)
    monkeypatch.setattr(stem_preparation, "_capability_cache", {"at": 0.0, "value": None})

    result = stem_preparation.probe_capability(force=True)

    assert result["available"] is True
    assert result["cuda"] is True


def test_capability_unavailable_when_runtime_missing(monkeypatch):
    import chordflask_demucs.runtime as demucs_runtime

    def missing():
        raise demucs_runtime.DemucsRuntimeError("Demucs runtime not installed")

    monkeypatch.setattr(demucs_runtime, "require_runtime", missing)
    monkeypatch.setattr(stem_preparation, "_capability_cache", {"at": 0.0, "value": None})

    result = stem_preparation.probe_capability(force=True)

    assert result["available"] is False
    assert result["cuda"] is False


def test_probe_capability_is_cached(monkeypatch):
    calls = {"count": 0}

    def fake_uncached():
        calls["count"] += 1
        return {"available": True, "cuda": True, "reason": ""}

    monkeypatch.setattr(stem_preparation, "_probe_capability_uncached", fake_uncached)
    monkeypatch.setattr(
        stem_preparation, "_capability_cache", {"at": 0.0, "value": None}
    )
    assert stem_preparation.probe_capability(force=True)["available"] is True
    assert stem_preparation.probe_capability()["available"] is True
    assert calls["count"] == 1


# ── background job lifecycle ─────────────────────────────────────────


def _manager(runner, *, cuda=True, available=True):
    return StemPreparationManager(
        capability_probe=_gui_probe(available=available, cuda=cuda),
        runner=runner,
    )


def _wait_for_state(manager, media, state, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if manager.status(media)["state"] == state:
            return manager.status(media)
        time.sleep(0.01)
    raise AssertionError(f"state {state!r} not reached; last={manager.status(media)}")


def test_start_is_asynchronous_and_preparation_runs_in_background():
    gate = threading.Event()
    started = threading.Event()

    def runner(media):
        started.set()
        assert gate.wait(5)
        return 0

    manager = _manager(runner)
    media = Path("/tmp/prepare-async.mp3")

    result = manager.start(media)

    assert result["status"] == "accepted"
    assert started.wait(3)
    assert manager.status(media)["state"] == "running"
    gate.set()
    _wait_for_state(manager, media, "ready")


def test_duplicate_preparation_of_same_media_is_coalesced():
    gate = threading.Event()
    started = threading.Event()

    def runner(media):
        started.set()
        assert gate.wait(5)
        return 0

    manager = _manager(runner)
    media = Path("/tmp/prepare-duplicate.mp3")

    assert manager.start(media)["status"] == "accepted"
    assert started.wait(3)
    assert manager.start(media)["status"] == "already_running"
    gate.set()
    _wait_for_state(manager, media, "ready")


def test_different_media_is_reported_busy():
    gate = threading.Event()
    started = threading.Event()

    def runner(media):
        started.set()
        assert gate.wait(5)
        return 0

    manager = _manager(runner)
    first = Path("/tmp/prepare-first.mp3")
    second = Path("/tmp/prepare-second.mp3")

    assert manager.start(first)["status"] == "accepted"
    assert started.wait(3)
    assert manager.start(second)["status"] == "busy"
    gate.set()
    _wait_for_state(manager, first, "ready")


def test_failed_preparation_reports_error_and_allows_retry():
    gate = threading.Event()
    started = threading.Event()
    outcomes = [1, 0]

    def runner(media):
        started.set()
        assert gate.wait(5)
        return outcomes.pop(0)

    manager = _manager(runner)
    media = Path("/tmp/prepare-retry.mp3")

    assert manager.start(media)["status"] == "accepted"
    assert started.wait(3)
    gate.set()
    failure = _wait_for_state(manager, media, "error")
    assert "exit code 1" in failure["message"]

    # A later retry is allowed and can succeed.
    gate.clear()
    started.clear()
    assert manager.start(media)["status"] == "accepted"
    assert started.wait(3)
    gate.set()
    assert _wait_for_state(manager, media, "ready")["state"] == "ready"


def test_run_local_preparation_uses_auto_and_replace(monkeypatch):
    calls = {}
    import chordflask_demucs.cli as demucs_cli

    def fake_run(target, **kwargs):
        calls["target"] = target
        calls["kwargs"] = kwargs
        return 0

    monkeypatch.setattr(demucs_cli, "run", fake_run)

    result = stem_preparation.run_local_preparation(Path("/media/song.mp3"))

    assert result == 0
    assert calls["target"] == Path("/media/song.mp3")
    assert calls["kwargs"] == {"replace": True, "dry_run": False, "device": "auto"}


# ── app routes ───────────────────────────────────────────────────────


def make_client():
    app_wrapper = FlaskMP4App()
    client = app_wrapper.app.test_client()
    app_wrapper.clients.get_or_create(TEST_CLIENT_ID)
    client.set_cookie(CLIENT_COOKIE, TEST_CLIENT_ID)
    return app_wrapper, client


def _state(app_wrapper):
    return app_wrapper.clients.get_or_create(TEST_CLIENT_ID)


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


def _make_analyzed_song(tmp_path, *, name="song.mp3", with_audio=False):
    media = tmp_path / name
    media.write_bytes(b"not decoded by this route")
    analysis_dir = tmp_path / ".chordflask"
    analysis_dir.mkdir(exist_ok=True)
    data = ChordData()
    data.set_base_chords([{"timestamp": 0.0, "chord": "C"}])
    if with_audio:
        data.set_audio_track(STEMS_AUDIO_SET_ID, _audio_set(_stems_rel_dir()))
    data.save_to_file(analysis_dir / f"{media.stem}.json")
    return media


def _load(client, tmp_path, name="song.mp3"):
    return client.post("/load_file", json={"dirname": str(tmp_path), "filename": name})


def _install_manager(app_wrapper, runner, *, available=True, cuda=True):
    app_wrapper.stem_preparation = StemPreparationManager(
        capability_probe=_gui_probe(available=available, cuda=cuda),
        runner=runner,
    )


def _success_runner(media):
    return 0


def test_prepare_route_accepts_and_runs_in_background(tmp_path):
    app_wrapper, client = make_client()
    _make_analyzed_song(tmp_path)
    _load(client, tmp_path)
    gate = threading.Event()
    started = threading.Event()

    def runner(media):
        started.set()
        assert gate.wait(5)
        return 0

    _install_manager(app_wrapper, runner)

    response = client.post(
        "/prepare_stems", json={"dirname": str(tmp_path), "filename": "song.mp3"}
    )

    assert response.status_code == 202
    assert response.get_json()["status"] == "accepted"
    assert started.wait(3)
    status = client.get("/stem_preparation_status").get_json()
    assert status["state"] == "running"
    gate.set()


def test_prepare_route_reports_already_running(tmp_path):
    app_wrapper, client = make_client()
    _make_analyzed_song(tmp_path)
    _load(client, tmp_path)
    gate = threading.Event()
    started = threading.Event()

    def runner(media):
        started.set()
        assert gate.wait(5)
        return 0

    _install_manager(app_wrapper, runner)
    body = {"dirname": str(tmp_path), "filename": "song.mp3"}

    assert client.post("/prepare_stems", json=body).status_code == 202
    assert started.wait(3)
    duplicate = client.post("/prepare_stems", json=body)
    assert duplicate.status_code == 200
    assert duplicate.get_json()["status"] == "already_running"
    gate.set()


def test_prepare_route_unavailable_when_runtime_missing(tmp_path):
    app_wrapper, client = make_client()
    _make_analyzed_song(tmp_path)
    _load(client, tmp_path)
    _install_manager(app_wrapper, _success_runner, available=False)

    response = client.post(
        "/prepare_stems", json={"dirname": str(tmp_path), "filename": "song.mp3"}
    )

    assert response.status_code == 409
    assert response.get_json()["status"] == "unavailable"


def test_prepare_route_available_without_cuda(tmp_path):
    app_wrapper, client = make_client()
    _make_analyzed_song(tmp_path)
    _load(client, tmp_path)
    _install_manager(app_wrapper, _success_runner, available=True, cuda=False)

    response = client.post(
        "/prepare_stems", json={"dirname": str(tmp_path), "filename": "song.mp3"}
    )

    assert response.status_code == 202
    assert response.get_json()["status"] == "accepted"


def test_prepare_route_ready_when_stems_already_exist(tmp_path):
    app_wrapper, client = make_client()
    _make_analyzed_song(tmp_path, with_audio=True)
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(tmp_path, stem)
    _load(client, tmp_path)
    _install_manager(app_wrapper, _success_runner)

    response = client.post(
        "/prepare_stems", json={"dirname": str(tmp_path), "filename": "song.mp3"}
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "ready"


def test_prepare_route_rejects_invalid_or_foreign_paths(tmp_path):
    app_wrapper, client = make_client()
    _make_analyzed_song(tmp_path)
    _load(client, tmp_path)
    _install_manager(app_wrapper, _success_runner)

    traversal = client.post(
        "/prepare_stems", json={"dirname": str(tmp_path), "filename": "../song.mp3"}
    )
    assert traversal.status_code == 400

    missing = client.post(
        "/prepare_stems", json={"dirname": str(tmp_path / "nope"), "filename": "song.mp3"}
    )
    assert missing.status_code == 404

    other = tmp_path / "other.mp3"
    other.write_bytes(b"other")
    not_active = client.post(
        "/prepare_stems", json={"dirname": str(tmp_path), "filename": "other.mp3"}
    )
    assert not_active.status_code == 409


def test_prepare_route_requires_loaded_active_media(tmp_path):
    app_wrapper, client = make_client()
    _make_analyzed_song(tmp_path)
    _install_manager(app_wrapper, _success_runner)

    response = client.post(
        "/prepare_stems", json={"dirname": str(tmp_path), "filename": "song.mp3"}
    )

    assert response.status_code == 409


def test_stem_preparation_status_reports_idle_then_ready(tmp_path):
    app_wrapper, client = make_client()
    _make_analyzed_song(tmp_path)
    _load(client, tmp_path)
    gate = threading.Event()
    started = threading.Event()

    def runner(media):
        started.set()
        assert gate.wait(5)
        return 0

    _install_manager(app_wrapper, runner)

    idle = client.get("/stem_preparation_status").get_json()
    assert idle["state"] == "idle"
    assert idle["available"] is True

    client.post("/prepare_stems", json={"dirname": str(tmp_path), "filename": "song.mp3"})
    assert started.wait(3)
    gate.set()
    deadline = time.monotonic() + 5
    state = None
    while time.monotonic() < deadline:
        state = client.get("/stem_preparation_status").get_json()["state"]
        if state == "ready":
            break
        time.sleep(0.01)
    assert state == "ready"


def test_refresh_stems_makes_prepared_set_visible_without_playback_change(tmp_path):
    app_wrapper, client = make_client()
    _make_analyzed_song(tmp_path)
    _load(client, tmp_path)
    client.post("/set_position", json={"position": 12.5})

    json_path = tmp_path / ".chordflask" / "song.json"
    data = ChordData()
    data.load_from_file(json_path)
    data.set_audio_track(STEMS_AUDIO_SET_ID, _audio_set(_stems_rel_dir()))
    data.save_to_file(json_path)
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(tmp_path, stem)

    response = client.post(
        "/refresh_stems", json={"dirname": str(tmp_path), "filename": "song.mp3"}
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["stems"]["set_id"] == STEMS_AUDIO_SET_ID
    assert payload["stems"]["stems"] == list(DEMUCS_STEM_NAMES)
    assert _state(app_wrapper).current_position == 12.5


def test_failed_preparation_does_not_expose_partial_stems(tmp_path):
    app_wrapper, client = make_client()
    _make_analyzed_song(tmp_path)
    _load(client, tmp_path)

    def failing_runner(media):
        return 1

    _install_manager(app_wrapper, failing_runner)
    client.post("/prepare_stems", json={"dirname": str(tmp_path), "filename": "song.mp3"})
    deadline = time.monotonic() + 5
    state = None
    while time.monotonic() < deadline:
        state = client.get("/stem_preparation_status").get_json()["state"]
        if state == "error":
            break
        time.sleep(0.01)
    assert state == "error"

    refreshed = client.post(
        "/refresh_stems", json={"dirname": str(tmp_path), "filename": "song.mp3"}
    )
    assert refreshed.status_code == 200
    assert refreshed.get_json()["stems"] is None


def test_refresh_stems_requires_active_media(tmp_path):
    app_wrapper, client = make_client()
    _make_analyzed_song(tmp_path)
    response = client.post(
        "/refresh_stems", json={"dirname": str(tmp_path), "filename": "song.mp3"}
    )
    assert response.status_code == 409


# ── existing producer/CLI behavior is unchanged ──────────────────────


def test_demucs_cli_defaults_unchanged():
    from chordflask_demucs.cli import build_parser

    parser = build_parser()
    actions = {action.dest: action for action in parser._actions}
    assert actions["device"].default == "auto"
    option_strings = {
        option for action in parser._actions for option in action.option_strings
    }
    assert {"--replace", "--dry-run", "--device"} <= option_strings
    assert actions["target"].type is Path


# ── template contract ────────────────────────────────────────────────


def _index_body(client):
    return client.get("/").get_data(as_text=True)


def test_theme_selector_moved_to_second_row():
    _, client = make_client()
    body = _index_body(client)

    title_row = body[body.index('class="chord-title-row"'):body.index('class="chord-tools-row"')]
    tools_row = body[
        body.index('class="chord-tools-row"'):body.index('class="stem-toggles"')
    ]

    assert 'id="chordThemeSelect"' not in title_row
    assert 'id="chordThemeSelect"' in tools_row
    # Theme selector stays immediately before the Edit/Save actions.
    assert tools_row.index('id="chordThemeSelect"') < tools_row.index('class="chord-actions"')


def test_theme_selector_is_available_on_desktop_and_phone_css():
    _, client = make_client()
    body = _index_body(client)

    # Base layout hides the selector; desktop and phone media queries show it.
    assert "#desktopSplitter,\n    #chordThemeSelect {\n      display: none;\n    }" in body
    assert "@media (min-width: 1024px), (max-width: 640px)" in body
    assert "#chordThemeSelect {\n        display: inline-block;" in body
    # The phone layout hides Changes so the theme selector takes its place.
    phone = body[body.index("@media (max-width: 640px) {"):]
    assert "#repeatDisplayButton {\n        display: none;\n      }" in phone


def test_theme_selector_behavior_unchanged():
    _, client = make_client()
    body = _index_body(client)

    assert "const themeKey = 'chordflask.chordTheme';" in body
    assert "themeSelect.value = readPreference(themeKey) === 'light' ? 'light' : 'dark';" in body
    assert "panel.classList.toggle('chord-light', themeActive() && themeSelect.value === 'light');" in body
    assert "function themeActive() {" in body
    assert "return desktop.matches || phone.matches;" in body
    assert "savePreference(themeKey, themeSelect.value);" in body
    theme_select = body[body.index('id="chordThemeSelect"'):]
    theme_select = theme_select[: theme_select.index("</select>")]
    assert '<option value="dark" selected>Dark</option>' in theme_select
    assert '<option value="light">Light</option>' in theme_select


def test_prepare_button_and_js_contract():
    _, client = make_client()
    body = _index_body(client)

    assert 'id="prepareStemsButton"' in body
    assert 'onclick="prepareStems()"' in body
    assert ">Prepare</button>" in body
    assert 'aria-label="Prepare vocal and instrument stems"' in body
    for name in (
        "function prepareStems()",
        "function refreshStemPreparationState()",
        "function finishStemPreparation()",
        "function updatePrepareStemsButton()",
    ):
        assert name in body

    finish = javascript_function(body, "finishStemPreparation")
    # Completion must reveal the existing controls, never auto-activate them.
    assert "updateStemsAvailability(data.stems);" in finish
    assert "activateStems" not in finish
    assert "toggleStems" not in finish
    assert "video.play" not in finish

    prepare = javascript_function(body, "prepareStems")
    assert "fetch('/prepare_stems'" in prepare
    assert "fetch('/stem_preparation_status'" in body
    assert "fetch('/refresh_stems'" in body


def test_prepare_is_desktop_only():
    _, client = make_client()
    body = _index_body(client)

    assert "let desktopStemPrepare = window.matchMedia('(min-width: 1024px)');" in body

    update = javascript_function(body, "updatePrepareStemsButton")
    assert "desktopStemPrepare.matches" in update

    refresh = javascript_function(body, "refreshStemPreparationState")
    assert "if (!desktopStemPrepare.matches)" in refresh
    # The mobile early-return happens before any capability request.
    assert refresh.index("!desktopStemPrepare.matches") < refresh.index(
        "fetch('/stem_preparation_status'"
    )

    prepare = javascript_function(body, "prepareStems")
    assert "if (!desktopStemPrepare.matches) return;" in prepare

    # Leaving desktop cancels polling through the breakpoint listener.
    assert "desktopStemPrepare.addEventListener('change'" in body


def test_existing_stem_playback_controls_unchanged():
    _, client = make_client()
    body = _index_body(client)

    assert 'onclick="toggleStems()"' in body
    assert "function activateStems()" in body
    assert "function stemDriftCheck()" in body
    assert "function toggleStem(name)" in body
    assert body.count('id="stemMixerSlider"') == 1
