import os
import fcntl
import sys
from datetime import datetime
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
FLASK_DIR = REPO_ROOT / "flask"

if str(FLASK_DIR) not in sys.path:
    sys.path.insert(0, str(FLASK_DIR))

import chordflask
from analysis_queue import AnalysisQueue
from analysis_worker import AnalysisWorker
from chorddata import ChordData
from chordflask import FlaskMP4App
from filerepr import FileRepr


@pytest.fixture(autouse=True)
def isolate_default_analysis_queue(monkeypatch, tmp_path):
    monkeypatch.setenv("CHORDFLASK_QUEUE_DIR", str(tmp_path / "default-queue"))


def make_client():
    app_wrapper = FlaskMP4App()
    return app_wrapper, app_wrapper.app.test_client()


def activate_analyzed_media(app_wrapper, tmp_path, name="song.mp4"):
    media = tmp_path / name
    media.write_bytes(b"not used")
    file_repr = FileRepr(str(media), datapath=str(tmp_path / ".chordflask"), create=True)
    chord_data = ChordData()
    chord_data.set_base_chords([{"timestamp": 0.0, "chord": "C"}])
    chord_data.save_to_file(file_repr.get("json"))
    app_wrapper.file_repr = file_repr
    return media


def test_index_route_renders():
    _, client = make_client()

    response = client.get("/")

    assert response.status_code == 200


def test_index_contains_file_autoload_logic():
    _, client = make_client()

    response = client.get("/")
    body = response.get_data(as_text=True)

    assert "function loadSelectedFile(options = {})" in body
    assert "loadFiles({ autoload: true" in body
    assert "fileTableBody" in body
    assert "openDirectory" in body
    assert "continueButton" in body
    assert "playNextFileIfContinue" in body
    assert "navigateFile(1, 'continue')" in body
    assert "queueStatus" in body
    assert "showQueueStatus" in body
    assert "localStorage" in body
    assert "pollingLeadSeconds" in body
    assert "estimatedRoundTripSeconds" in body
    assert "positionSyncPending" in body
    assert "playbackSyncGeneration" in body
    assert "refreshAnalysisQueueStatus" in body
    assert "Worker stopped" in body
    assert "failureNotice" in body
    assert "Failed: ${pathBasename(newFailure.path)}" in body
    assert "Date.now() + 8000" in body
    assert "${failed.length} analysis failed" not in body
    assert "loadRequestInFlight" in body


def test_continue_waits_for_missing_analysis_then_autoplays_new_song():
    _, client = make_client()

    body = client.get("/").get_data(as_text=True)
    queue_branch = body[
        body.index("if (data.status === 'queued'"):
        body.index("semitonesInput.value = 0;")
    ]

    assert "let pendingAnalysisLoad = null;" in body
    assert "function waitForAnalysis(dirname, filename, path, reason)" in body
    assert "function resumeAfterAnalysis(currentPaths, failed)" in body
    assert "analysisWaitReason || 'continue'" in queue_branch
    assert "setContinue(false);" not in queue_branch
    assert "waiting.reason === 'continue' && !isContinuing" in body
    assert "if (currentPaths.has(waiting.path))" in body
    assert "loadSelectedFile({" in body
    assert "autoplay: true," in body
    assert "dirname: waiting.dirname," in body
    assert "filename: waiting.filename" in body


def test_continue_stops_instead_of_skipping_failed_analysis():
    _, client = make_client()

    body = client.get("/").get_data(as_text=True)
    resume_function = body[
        body.index("function resumeAfterAnalysis"):
        body.index("function renderAnalysisQueueStatus")
    ]

    assert "failed.find(item => item.path === waiting.path)" in resume_function
    assert "setContinue(false);" in resume_function
    assert "Analysis failed: ${waiting.filename}" in resume_function
    assert "playNextFileIfContinue" not in resume_function


def test_index_contains_accessible_previous_and_next_controls():
    _, client = make_client()

    body = client.get("/").get_data(as_text=True)

    assert 'class="playback-navigation" aria-label="Playlist navigation"' in body
    assert 'id="previousFileButton"' in body
    assert 'onclick="navigateFile(-1)"' in body
    assert 'title="Previous file" aria-label="Previous file" disabled' in body
    assert 'id="nextFileButton"' in body
    assert 'onclick="navigateFile(1)"' in body
    assert 'title="Next file" aria-label="Next file" disabled' in body
    assert ".playback-navigation button:disabled" in body
    assert "width: 32px" in body
    assert "height: 28px" in body


def test_manual_navigation_uses_visible_order_and_waits_for_analysis():
    _, client = make_client()

    body = client.get("/").get_data(as_text=True)
    navigate_function = body[
        body.index("function navigateFile"):
        body.index("function playNextFileIfContinue")
    ]
    queue_start = body.index("if (data.status === 'queued'")
    queue_branch = body[queue_start:body.index("semitonesInput.value = 0;", queue_start)]

    assert "file => file.name === navigationAnchorName()" in navigate_function
    assert "currentFiles[currentIndex + offset]" in navigate_function
    assert "pendingAnalysisLoad = null;" in navigate_function
    assert "selectedFileName = targetFile.name" in navigate_function
    assert "autoplay: true, analysisWaitReason: reason" in navigate_function
    assert "analysisWaitReason || isContinuing" in queue_branch
    assert "waitForAnalysis(" in queue_branch
    assert "pendingAnalysisLoad = { dirname, filename, path, reason };" in body
    continue_start = body.index("function playNextFileIfContinue")
    continue_function = body[
        continue_start:
        body.index("document.addEventListener", continue_start)
    ]
    assert "|| isRepeating" in continue_function
    assert "|| pendingAnalysisLoad" in continue_function
    assert "|| loadRequestInFlight" in continue_function
    assert "|| loadIntentQueue.length" in continue_function


def test_navigation_buttons_follow_selected_anchor_while_loading():
    _, client = make_client()

    body = client.get("/").get_data(as_text=True)
    update_function = body[
        body.index("function updateNavigationButtons"):
        body.index("function waitForAnalysis")
    ]

    assert "selectedFileName || pendingAnalysisLoad?.filename || loadedFileName" in body
    assert "currentFiles.findIndex" in update_function
    assert "previousFileButton.disabled = currentIndex <= 0" in update_function
    assert "currentIndex >= currentFiles.length - 1" in update_function
    assert "loadRequestInFlight" not in update_function
    assert "updateNavigationButtons();" in body[
        body.index("function renderBrowserTable"):
        body.index("function renderDirectoryRow")
    ]


def test_navigation_buffers_distinct_clicks_and_coalesces_identical_targets():
    _, client = make_client()

    body = client.get("/").get_data(as_text=True)
    queue_function = body[
        body.index("function loadSelectedFile"):
        body.index("function reanalyzeCurrentFile")
    ]
    processor = body[
        body.index("function processNextLoadIntent"):
        body.index("function loadSelectedFile")
    ]
    navigate_function = body[
        body.index("function navigateFile"):
        body.index("function playNextFileIfContinue")
    ]

    assert "let activeLoadIntent = null;" in body
    assert "let loadIntentQueue = [];" in body
    assert "const previousIntent = lastQueuedIntent || activeLoadIntent" in queue_function
    assert "sameLoadIntent(intent, previousIntent)" in queue_function
    assert "loadIntentQueue.push(intent);" in queue_function
    assert "const intent = loadIntentQueue.shift();" in processor
    assert "processNextLoadIntent();" in processor
    assert "loadRequestInFlight || !loadIntentQueue.length" in processor
    assert "loadRequestInFlight" not in navigate_function


def test_file_rows_autoplay_and_wait_without_duplicate_analysis_jobs():
    _, client = make_client()

    body = client.get("/").get_data(as_text=True)
    file_rows = body[
        body.index("files.forEach(file =>"):
        body.index("function renderDirectoryRow")
    ]

    assert "selectedFileName = file.name" in file_rows
    assert "loadSelectedFile({ autoplay: true, analysisWaitReason: 'manual' })" in file_rows
    assert "queuedAnalysisPaths.has(intent.requestedPath)" in body
    assert "Already queued: ${intent.filename}" in body


def test_playlist_navigation_does_not_add_height_to_control_bar():
    _, client = make_client()

    body = client.get("/").get_data(as_text=True)
    topbar = body[body.index(".topbar {"):body.index(".status {")]
    controls = body[body.index(".controls {"):body.index(".control {")]

    assert "display: flex" in topbar
    assert "flex: 1" in topbar
    assert "text-overflow: ellipsis" in topbar
    assert ".playback-navigation" in topbar
    assert "grid-template-columns: minmax(230px, 0.48fr) minmax(0, 2fr) 128px" in controls


def test_repeated_position_returns_complete_player_payload():
    app_wrapper, client = make_client()

    class FakePlayer:
        def get_callback_output(self):
            return {"callback_output": ["grid"], "bpm": 120, "position": 0.0}

    app_wrapper.player = FakePlayer()

    response = client.post("/set_position", json={"position": 0.0})

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "callback_output": ["grid"],
        "bpm": 120,
        "position": 0.0,
    }


def test_analysis_queue_status_reports_stopped_and_running_worker(tmp_path):
    app_wrapper, client = make_client()
    app_wrapper.analysis_queue = AnalysisQueue(tmp_path / "queue")

    stopped = client.get("/analysis_queue_status").get_json()

    assert stopped == {
        "pending": [],
        "failed": [],
        "worker": {"running": False, "managed": False},
    }

    lock_file = app_wrapper.analysis_queue.queue_dir / "analysis_worker.lock"
    with lock_file.open("a+") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        running = client.get("/analysis_queue_status").get_json()

    assert running["worker"] == {"running": True, "managed": False}


def test_index_contains_accessible_file_sorting_controls():
    _, client = make_client()

    body = client.get("/").get_data(as_text=True)

    assert 'data-sort-key="name"' in body
    assert 'data-sort-key="size"' in body
    assert 'data-sort-key="modified"' in body
    assert 'aria-sort="ascending"' in body
    assert "function setSort(nextSortKey)" in body
    assert "function sortBrowserEntries()" in body
    assert "chordifier.sortKey" in body
    assert "chordifier.sortDirection" in body


def test_index_contains_small_accessible_reanalysis_control():
    _, client = make_client()

    body = client.get("/").get_data(as_text=True)

    assert 'id="reanalyzeButton"' in body
    assert 'title="Chordino/QM reanalysis of current file"' in body
    assert 'aria-label="Reanalyze with Chordino and QM"' in body
    assert "hidden disabled>↻</button>" in body
    assert "#reanalyzeButton" in body
    assert "width: 22px" in body
    assert "height: 20px" in body
    assert "window.confirm" in body
    assert "queuedAnalysisPaths.has(loadedMediaPath)" in body
    assert "loadedAnalysisValid" in body
    assert "reanalyzeButton.addEventListener('click', reanalyzeCurrentFile)" in body


def test_index_contains_analysis_track_switching_contract():
    _, client = make_client()

    body = client.get("/").get_data(as_text=True)

    assert 'id="chordTrackSelect" hidden' in body
    assert 'id="rhythmTrackSelect" hidden' in body
    assert "chordflask.chordTrackId" in body
    assert "chordflask.rhythmTrackId" in body
    assert "fetch('/update_analysis_tracks'" in body
    assert "tracks.length <= 1" in body
    assert "localStorage.setItem(storageKey, newId)" in body


def test_index_contains_audio_player_and_web_directory_browser():
    _, client = make_client()

    body = client.get("/").get_data(as_text=True)

    assert 'id="audioPlayerPanel" class="audio-player-panel" hidden' in body
    assert 'id="audioPlayer" controls' in body
    assert 'id="audioFileName"' in body
    assert 'onclick="browseDirectories()"' in body
    assert "fetch('/browse_roots'" in body
    assert "function selectMediaPlayer(mediaKind, filename)" in body
    assert "mediaKind === 'audio' ? audioPlayer : videoPlayer" in body
    assert "selectMediaPlayer(data.media_kind, filename)" in body
    assert "[videoPlayer, audioPlayer].forEach" in body
    assert 'id="batchLimit" type="number" min="1" max="500"' in body
    assert 'id="queueNextButton"' in body
    assert "function queueNextBatch()" in body
    assert "filenames: currentFiles.map(file => file.name)" in body
    assert "chordflask.batchLimit" in body


def test_list_files_returns_mp3_mp4_and_webm_entries(tmp_path):
    app_wrapper, client = make_client()
    (tmp_path / "alpha.mp4").write_bytes(b"")
    (tmp_path / "beta.webm").write_bytes(b"")
    (tmp_path / "gamma.mp3").write_bytes(b"")
    (tmp_path / "notes.txt").write_text("ignored")

    response = client.post(
        "/list_files",
        json={"dirname": str(tmp_path), "matchstring": ""},
    )

    assert response.status_code == 200
    assert response.get_json() == ["alpha.mp4 | 0M", "beta.webm | 0M", "gamma.mp3 | 0M"]
    assert str(tmp_path) in app_wrapper.stored_directories


def test_list_files_can_return_structured_entries(tmp_path):
    _, client = make_client()
    subdir = tmp_path / "beatles"
    hidden_analysis_dir = tmp_path / ".chordflask"
    legacy_analysis_dir = tmp_path / ".chordy"
    subdir.mkdir()
    hidden_analysis_dir.mkdir()
    legacy_analysis_dir.mkdir()
    media_file = tmp_path / "ALPHA.MP3"
    media_file.write_bytes(b"123")

    response = client.post(
        "/list_files",
        json={"dirname": str(tmp_path), "matchstring": "", "structured": True},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["current_dir"] == str(tmp_path)
    assert [directory["name"] for directory in payload["directories"]] == ["beatles"]
    assert payload["directories"][0]["type"] == "directory"
    assert payload["directories"][0]["mtime_epoch"] == subdir.stat().st_mtime
    files = payload["files"]
    assert files[0]["name"] == "ALPHA.MP3"
    assert files[0]["type"] == "file"
    assert files[0]["media_kind"] == "audio"
    assert files[0]["size_mb"] == 0
    assert files[0]["size_bytes"] == 3
    assert files[0]["mtime_epoch"] == media_file.stat().st_mtime
    datetime.strptime(files[0]["mtime"], "%Y-%m-%d %H:%M")


def test_list_files_prefers_mp4_then_webm_then_mp3_for_same_stem(tmp_path):
    _, client = make_client()
    for name in ("song.mp3", "song.webm", "song.mp4", "audio.mp3"):
        (tmp_path / name).write_bytes(b"media")

    response = client.post(
        "/list_files",
        json={"dirname": str(tmp_path), "matchstring": "", "structured": True},
    )

    assert [item["name"] for item in response.get_json()["files"]] == [
        "audio.mp3",
        "song.mp4",
    ]


def test_enqueue_batch_uses_submitted_gui_order_and_next_limit(tmp_path):
    app_wrapper, client = make_client()
    for name in ("a.mp4", "b.mp3", "c.webm", "done.mp4"):
        (tmp_path / name).write_bytes(b"media")
    done_repr = FileRepr(str(tmp_path / "done.mp4"), create=True)
    done = ChordData()
    done.set_base_chords([{"timestamp": 0.0, "chord": "C"}])
    done.save_to_file(done_repr.get("json"))
    app_wrapper.analysis_queue.enqueue(tmp_path / "b.mp3")

    response = client.post("/enqueue_batch", json={
        "dirname": str(tmp_path),
        "filenames": ["done.mp4", "b.mp3", "c.webm", "a.mp4"],
        "limit": 1,
    })

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "queued",
        "queued_count": 1,
        "queued_paths": [str((tmp_path / "c.webm").resolve())],
        "already_queued_count": 1,
        "skipped_analyzed_count": 1,
        "remaining_count": 1,
    }
    assert [Path(item["path"]).name for item in app_wrapper.analysis_queue.status()["pending"]] == [
        "b.mp3", "c.webm",
    ]

    next_response = client.post("/enqueue_batch", json={
        "dirname": str(tmp_path),
        "filenames": ["done.mp4", "b.mp3", "c.webm", "a.mp4"],
        "limit": 1,
    })

    assert next_response.get_json()["queued_paths"] == [str((tmp_path / "a.mp4").resolve())]
    assert next_response.get_json()["remaining_count"] == 0


def test_enqueue_batch_rejects_bad_limits_paths_and_lower_priority_media(tmp_path):
    _, client = make_client()
    (tmp_path / "song.mp4").write_bytes(b"video")
    (tmp_path / "song.mp3").write_bytes(b"audio")

    bad_limit = client.post("/enqueue_batch", json={
        "dirname": str(tmp_path), "filenames": ["song.mp4"], "limit": 0,
    })
    traversal = client.post("/enqueue_batch", json={
        "dirname": str(tmp_path), "filenames": ["../song.mp4"], "limit": 1,
    })
    lower_priority = client.post("/enqueue_batch", json={
        "dirname": str(tmp_path), "filenames": ["song.mp3"], "limit": 1,
    })

    assert bad_limit.status_code == 400
    assert traversal.status_code == 400
    assert lower_priority.status_code == 400


def test_load_file_rejects_lower_priority_same_stem_media(tmp_path):
    _, client = make_client()
    (tmp_path / "song.mp4").write_bytes(b"video")
    (tmp_path / "song.mp3").write_bytes(b"audio")

    response = client.post(
        "/load_file",
        json={"dirname": str(tmp_path), "filename": "song.mp3"},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "song.mp4 takes precedence over song.mp3"


def test_list_files_returns_not_found_for_missing_directory(tmp_path):
    _, client = make_client()

    response = client.post(
        "/list_files",
        json={"dirname": str(tmp_path / "missing"), "matchstring": ""},
    )

    assert response.status_code == 404
    assert "does not exist" in response.get_json()["error"]


def test_list_files_allows_arbitrary_accessible_directory(tmp_path):
    arbitrary = tmp_path / "arbitrary"
    arbitrary.mkdir()
    (arbitrary / "song.mp4").write_bytes(b"not used")
    _, client = make_client()

    response = client.post(
        "/list_files",
        json={"dirname": str(arbitrary), "matchstring": ""},
    )

    assert response.status_code == 200
    assert response.get_json() == ["song.mp4 | 0M"]


def test_load_file_rejects_traversal_and_unsupported_files(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (tmp_path / "outside.mp4").write_bytes(b"not used")
    (allowed / "notes.txt").write_text("not media")
    _, client = make_client()

    traversal = client.post(
        "/load_file",
        json={"dirname": str(allowed), "filename": "../outside.mp4"},
    )
    unsupported = client.post(
        "/load_file",
        json={"dirname": str(allowed), "filename": "notes.txt"},
    )

    assert traversal.status_code == 400
    assert unsupported.status_code == 400


def test_load_file_accepts_mp3_and_reports_audio_kind(tmp_path):
    app_wrapper, client = make_client()
    media = tmp_path / "song.MP3"
    media.write_bytes(b"not used")
    app_wrapper.analysis_queue = AnalysisQueue(tmp_path / "queue")

    response = client.post(
        "/load_file",
        json={"dirname": str(tmp_path), "filename": media.name},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "queued"
    assert response.get_json()["media_kind"] == "audio"
    assert app_wrapper.analysis_queue.status()["pending"][0]["path"] == str(media)


@pytest.mark.parametrize(
    ("name", "content_type"),
    [
        ("song.mp3", "audio/mpeg"),
        ("song.mp4", "video/mp4"),
        ("song.webm", "video/webm"),
    ],
)
def test_media_route_uses_source_content_type(tmp_path, name, content_type):
    app_wrapper, client = make_client()
    media = tmp_path / name
    media.write_bytes(b"media")
    app_wrapper.file_repr = FileRepr(str(media), datapath=str(tmp_path / ".chordflask"))

    response = client.get("/video")

    assert response.status_code == 200
    assert response.content_type == content_type


def test_load_file_allows_valid_media_symlink(tmp_path):
    directory = tmp_path / "directory"
    directory.mkdir()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"not used")
    (directory / "linked.mp4").symlink_to(outside)
    app_wrapper, client = make_client()
    app_wrapper.analysis_queue = AnalysisQueue(tmp_path / "queue")

    response = client.post(
        "/load_file",
        json={"dirname": str(directory), "filename": "linked.mp4"},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "queued"
    assert app_wrapper.analysis_queue.status()["pending"][0]["path"] == str(outside)


def test_routes_reject_malformed_payloads():
    _, client = make_client()

    assert client.post("/list_files", data="not json").status_code == 400
    assert client.post("/set_position", json={"position": -1}).status_code == 400
    assert client.post("/update_semitones", json={"semitones": 25}).status_code == 400
    assert client.post(
        "/update_display_options",
        json={"prefer_flats": "yes", "repeat_mode": "changes"},
    ).status_code == 400


def test_reanalyze_requires_active_file_and_valid_payload(tmp_path):
    app_wrapper, client = make_client()
    media = tmp_path / "song.mp4"
    media.write_bytes(b"not used")

    no_active = client.post(
        "/reanalyze",
        json={"dirname": str(tmp_path), "filename": media.name},
    )
    assert no_active.status_code == 409

    activate_analyzed_media(app_wrapper, tmp_path)
    assert client.post("/reanalyze", data="not json").status_code == 400
    assert client.post(
        "/reanalyze",
        json={"dirname": str(tmp_path), "filename": "../song.mp4"},
    ).status_code == 400


def test_reanalyze_rejects_media_outside_allowed_roots(tmp_path):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    app_wrapper, client = make_client()
    activate_analyzed_media(app_wrapper, allowed)
    (outside / "other.mp4").write_bytes(b"not used")
    app_wrapper.allowed_roots = [allowed.resolve()]

    response = client.post(
        "/reanalyze",
        json={"dirname": str(outside), "filename": "other.mp4"},
    )

    assert response.status_code == 403


def test_reanalyze_queues_forced_job_and_deduplicates(tmp_path):
    app_wrapper, client = make_client()
    media = activate_analyzed_media(app_wrapper, tmp_path)
    app_wrapper.analysis_queue = AnalysisQueue(tmp_path / "queue")
    payload = {"dirname": str(tmp_path), "filename": media.name}

    queued = client.post("/reanalyze", json=payload)
    duplicate = client.post("/reanalyze", json=payload)

    assert queued.status_code == 200
    assert queued.get_json()["status"] == "queued"
    assert duplicate.get_json()["status"] == "already_queued"
    pending = app_wrapper.analysis_queue.status()["pending"]
    assert len(pending) == 1
    assert pending[0]["path"] == str(media)
    assert pending[0]["force"] is True


def test_reanalyze_deduplicates_already_running_job(tmp_path):
    app_wrapper, client = make_client()
    media = activate_analyzed_media(app_wrapper, tmp_path)
    app_wrapper.analysis_queue = AnalysisQueue(tmp_path / "queue")
    app_wrapper.analysis_queue.enqueue(media, force=True)
    assert app_wrapper.analysis_queue.peek()["status"] == "processing"

    response = client.post(
        "/reanalyze",
        json={"dirname": str(tmp_path), "filename": media.name},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "already_queued"
    assert app_wrapper.analysis_queue.status()["pending"][0]["status"] == "processing"


def test_default_video_directories_include_relative_shortcuts():
    app_wrapper, _ = make_client()

    directories = app_wrapper.default_video_directories()

    assert directories[0] == "./videos"
    assert directories[1] == "../videos"
    assert str(REPO_ROOT / "videos") in directories


def test_stored_directories_include_executable_videos_for_frozen_build(monkeypatch):
    app_wrapper, _ = make_client()
    app_wrapper.is_frozen = lambda: True
    monkeypatch.setattr(sys, "executable", "/opt/chordflask/chordflask")

    directories = app_wrapper.default_video_directories()

    assert "/opt/chordflask/videos" in directories


def test_analysis_error_message_explains_broken_mp4():
    app_wrapper, _ = make_client()

    message = app_wrapper.analysis_error_message(
        "broken.mp4",
        RuntimeError("Error passing `ffmpeg -i` command output: moov atom not found"),
    )

    assert "broken.mp4" in message
    assert "not readable by ffmpeg" in message
    assert "incomplete or corrupted" in message


def test_load_file_uses_existing_json_without_starting_analysis(tmp_path, monkeypatch):
    app_wrapper, client = make_client()
    media = tmp_path / "song.mp4"
    media.write_bytes(b"not used")
    chord_dir = tmp_path / ".chordflask"
    chord_dir.mkdir()
    chord_data = ChordData()
    chord_data.set_base_chords([
        {"timestamp": 0.0, "chord": "C"},
    ])
    chord_data.save_to_file(str(chord_dir / "song.json"))
    players = []

    class FakePlayer:
        def __init__(self, file_repr, **kwargs):
            players.append((file_repr, kwargs))

        def set_prefer_flats(self, prefer_flats):
            pass

        def set_repeat_mode(self, repeat_mode):
            pass

        def analysis_track_state(self):
            return {"active_chord_track_id": None, "active_rhythm_track_id": None,
                    "available_chord_tracks": [], "available_rhythm_tracks": []}

        def select_analysis_tracks(self, chord_track_id=None, rhythm_track_id=None,
                                   soft_fallback=False):
            pass

    monkeypatch.setattr(chordflask, "MP4PlayerFlask", FakePlayer)

    response = client.post(
        "/load_file",
        json={"dirname": str(tmp_path), "filename": "song.mp4 | 0M"},
    )

    assert response.status_code == 200
    assert response.get_json()["json_file"] == str(chord_dir / "song.json")
    assert response.get_json()["analysis_valid"] is True
    assert players[0][0].get() == str(media)


def test_load_file_reads_legacy_analysis_directory(tmp_path, monkeypatch):
    app_wrapper, client = make_client()
    media = tmp_path / "song.mp4"
    media.write_bytes(b"not used")
    legacy_dir = tmp_path / ".chordy"
    legacy_dir.mkdir()
    chord_data = ChordData()
    chord_data.set_base_chords([{"timestamp": 0.0, "chord": "C"}])
    chord_data.save_to_file(str(legacy_dir / "song.json"))

    class FakePlayer:
        def __init__(self, file_repr, **kwargs):
            self.file_repr = file_repr

        def set_prefer_flats(self, prefer_flats):
            pass

        def set_repeat_mode(self, repeat_mode):
            pass

        def analysis_track_state(self):
            return {"active_chord_track_id": None, "active_rhythm_track_id": None,
                    "available_chord_tracks": [], "available_rhythm_tracks": []}

        def select_analysis_tracks(self, chord_track_id=None, rhythm_track_id=None,
                                   soft_fallback=False):
            pass

    monkeypatch.setattr(chordflask, "MP4PlayerFlask", FakePlayer)

    response = client.post(
        "/load_file",
        json={"dirname": str(tmp_path), "filename": media.name},
    )

    assert response.status_code == 200
    assert response.get_json()["json_file"] == str(legacy_dir / "song.json")
    assert app_wrapper.file_repr.datapath == str(legacy_dir)


def test_load_file_marks_invalid_existing_analysis_for_hidden_reanalyze(
    tmp_path, monkeypatch
):
    app_wrapper, client = make_client()
    media = tmp_path / "song.mp4"
    media.write_bytes(b"not used")
    chord_dir = tmp_path / ".chordflask"
    chord_dir.mkdir()
    (chord_dir / "song.json").write_text("{invalid", encoding="utf-8")

    class FakePlayer:
        def __init__(self, *args, **kwargs):
            pass

        def set_prefer_flats(self, prefer_flats):
            pass

        def set_repeat_mode(self, repeat_mode):
            pass

        def analysis_track_state(self):
            return {"active_chord_track_id": None, "active_rhythm_track_id": None,
                    "available_chord_tracks": [], "available_rhythm_tracks": []}

        def select_analysis_tracks(self, chord_track_id=None, rhythm_track_id=None,
                                   soft_fallback=False):
            pass

    monkeypatch.setattr(chordflask, "MP4PlayerFlask", FakePlayer)

    response = client.post(
        "/load_file",
        json={"dirname": str(tmp_path), "filename": media.name},
    )

    assert response.status_code == 200
    assert response.get_json()["analysis_valid"] is False
    reanalyze = client.post(
        "/reanalyze",
        json={"dirname": str(tmp_path), "filename": media.name},
    )
    assert reanalyze.status_code == 409


def test_load_file_queues_analysis_when_json_is_missing(tmp_path, monkeypatch):
    app_wrapper, client = make_client()
    media = tmp_path / "song.mp4"
    media.write_bytes(b"not used")
    app_wrapper.analysis_queue = AnalysisQueue(tmp_path / "queue")

    class FakePlayer:
        def __init__(self, *args, **kwargs):
            raise AssertionError("player should stay unchanged when analysis is queued")

    monkeypatch.setattr(chordflask, "MP4PlayerFlask", FakePlayer)

    response = client.post(
        "/load_file",
        json={"dirname": str(tmp_path), "filename": "song.mp4 | 0M"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "queued"
    assert payload["json_file"] is None
    assert app_wrapper.file_repr is None
    assert app_wrapper.analysis_queue.status()["pending"][0]["path"] == str(media)


def test_load_file_deduplicates_queued_analysis(tmp_path):
    app_wrapper, client = make_client()
    media = tmp_path / "song.mp4"
    media.write_bytes(b"not used")
    app_wrapper.analysis_queue = AnalysisQueue(tmp_path / "queue")

    client.post(
        "/load_file",
        json={"dirname": str(tmp_path), "filename": "song.mp4 | 0M"},
    )
    response = client.post(
        "/load_file",
        json={"dirname": str(tmp_path), "filename": "song.mp4 | 0M"},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "already_queued"
    assert len(app_wrapper.analysis_queue.status()["pending"]) == 1


def test_analysis_worker_processes_one_queued_file(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"not used")
    queue = AnalysisQueue(tmp_path / "queue")
    queue.enqueue(media)
    calls = []

    class FakeAnalyzer:
        def __init__(self, mp4_filename, data_dir):
            calls.append((mp4_filename, data_dir))
            self.data_dir = Path(data_dir)

        def process(self):
            chord_data = ChordData()
            chord_data.set_base_chords([
                {"timestamp": 0.0, "chord": "G"},
            ])
            chord_data.save_to_file(str(self.data_dir / "song.json"))

    worker = AnalysisWorker(queue=queue, poll_seconds=0, analyzer_cls=FakeAnalyzer)

    assert worker.run_once() is True
    assert len(calls) == 1
    assert calls[0][0] == str(media)
    assert Path(calls[0][1]).parent == tmp_path / ".chordflask"
    assert Path(calls[0][1]).name.startswith(".song.analyze-")
    assert not Path(calls[0][1]).exists()
    assert queue.status()["pending"] == []
    assert queue.status()["failed"] == []


def test_run_disables_debug_and_reloader_for_frozen_build(monkeypatch):
    app_wrapper, _ = make_client()
    app_wrapper.is_frozen = lambda: True
    calls = []

    def fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(app_wrapper.app, "run", fake_run)
    monkeypatch.delenv("CHORDIFIER_PORT", raising=False)
    monkeypatch.delenv("CHORDIFIER_DEBUG", raising=False)

    app_wrapper.run()

    assert calls == [{
        "host": "127.0.0.1",
        "port": 5000,
        "debug": False,
        "use_reloader": False,
    }]


def test_run_disables_debug_by_default_for_source_build(monkeypatch):
    app_wrapper, _ = make_client()
    calls = []

    monkeypatch.setattr(app_wrapper.app, "run", lambda **kwargs: calls.append(kwargs))
    monkeypatch.delenv("CHORDIFIER_DEBUG", raising=False)

    app_wrapper.run()

    assert calls[0]["debug"] is False


def test_run_allows_explicit_debug_on_loopback(monkeypatch):
    app_wrapper, _ = make_client()
    calls = []

    monkeypatch.setattr(app_wrapper.app, "run", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setenv("CHORDIFIER_DEBUG", "1")

    app_wrapper.run()

    assert calls[0]["debug"] is True


def test_run_rejects_debug_on_lan_bind(monkeypatch, tmp_path):
    monkeypatch.setenv("CHORDIFIER_MEDIA_ROOTS", str(tmp_path))
    monkeypatch.setenv("CHORDIFIER_DEBUG", "1")
    app_wrapper, _ = make_client()
    called = False

    def fake_run(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(app_wrapper.app, "run", fake_run)

    with pytest.raises(ValueError, match="debug mode.*loopback"):
        app_wrapper.run(listen="0.0.0.0")

    assert called is False


def test_run_accepts_port_from_environment(monkeypatch):
    app_wrapper, _ = make_client()
    calls = []

    def fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(app_wrapper.app, "run", fake_run)
    monkeypatch.setenv("CHORDIFIER_PORT", "5055")

    app_wrapper.run()

    assert calls[0]["port"] == 5055


def test_run_prints_browser_url_and_ffmpeg_status(monkeypatch, capsys):
    app_wrapper, _ = make_client()

    def fake_run(**kwargs):
        pass

    monkeypatch.setattr(app_wrapper.app, "run", fake_run)
    monkeypatch.setenv("CHORDIFIER_PORT", "5056")

    app_wrapper.run()

    output = capsys.readouterr().out
    assert "http://127.0.0.1:5056" in output
    assert "ChordFlask" in output
    assert "WARNING" not in output


def test_update_display_options_updates_player_and_rerenders():
    app_wrapper, client = make_client()
    calls = []

    class FakePlayer:
        def set_prefer_flats(self, prefer_flats):
            calls.append(("flats", prefer_flats))

        def set_repeat_mode(self, repeat_mode):
            calls.append(("repeat", repeat_mode))

        def update_position(self, position):
            calls.append(("position", position))

    app_wrapper.player = FakePlayer()
    app_wrapper.current_position = 12.5

    response = client.post(
        "/update_display_options",
        json={"prefer_flats": False, "repeat_mode": "changes"},
    )

    assert response.status_code == 200
    assert response.get_json()["success"] is True
    assert app_wrapper.prefer_flats is False
    assert app_wrapper.repeat_mode == "changes"
    assert calls == [("flats", False), ("repeat", "changes"), ("position", 12.5)]


def test_run_listens_on_loopback_by_default(monkeypatch):
    app_wrapper, _ = make_client()
    calls = []

    def fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(app_wrapper.app, "run", fake_run)
    monkeypatch.delenv("CHORDIFIER_LISTEN", raising=False)
    monkeypatch.delenv("CHORDIFIER_PORT", raising=False)

    app_wrapper.run()

    assert calls[0]["host"] == "127.0.0.1"


def test_run_accepts_listen_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("CHORDIFIER_MEDIA_ROOTS", str(tmp_path))
    app_wrapper, _ = make_client()
    calls = []

    def fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(app_wrapper.app, "run", fake_run)
    monkeypatch.setenv("CHORDIFIER_LISTEN", "0.0.0.0")

    app_wrapper.run()

    assert calls[0]["host"] == "0.0.0.0"


def test_run_listen_cli_overrides_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("CHORDIFIER_MEDIA_ROOTS", str(tmp_path))
    app_wrapper, _ = make_client()
    calls = []

    def fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(app_wrapper.app, "run", fake_run)
    monkeypatch.setenv("CHORDIFIER_LISTEN", "0.0.0.0")

    app_wrapper.run(listen="192.0.2.1")

    assert calls[0]["host"] == "192.0.2.1"


def test_run_prints_security_warning_for_lan_bind(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("CHORDIFIER_MEDIA_ROOTS", str(tmp_path))
    app_wrapper, _ = make_client()

    def fake_run(**kwargs):
        pass

    monkeypatch.setattr(app_wrapper.app, "run", fake_run)

    app_wrapper.run(listen="0.0.0.0")

    output = capsys.readouterr().out
    assert "http://0.0.0.0:5000" in output
    assert "SECURITY:" in output
    assert "No authentication" in output


def test_run_rejects_lan_bind_without_allowed_roots(monkeypatch):
    monkeypatch.delenv("CHORDIFIER_MEDIA_ROOTS", raising=False)
    app_wrapper, _ = make_client()
    called = False

    def fake_run(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(app_wrapper.app, "run", fake_run)

    with pytest.raises(ValueError, match="CHORDIFIER_MEDIA_ROOTS"):
        app_wrapper.run(listen="0.0.0.0")

    assert called is False


def test_run_no_security_warning_for_loopback(monkeypatch, capsys):
    app_wrapper, _ = make_client()

    def fake_run(**kwargs):
        pass

    monkeypatch.setattr(app_wrapper.app, "run", fake_run)

    app_wrapper.run(listen="127.0.0.1")

    output = capsys.readouterr().out
    assert "Exposed on network interface" not in output
    assert "SECURITY:" not in output
    assert "http://127.0.0.1:5000" in output


def test_allowed_roots_defaults_to_none(monkeypatch):
    monkeypatch.delenv("CHORDIFIER_MEDIA_ROOTS", raising=False)
    app_wrapper, _ = make_client()

    assert app_wrapper.allowed_roots is None


def test_browse_roots_starts_at_home_without_restrictions(monkeypatch):
    monkeypatch.delenv("CHORDIFIER_MEDIA_ROOTS", raising=False)
    _, client = make_client()

    response = client.get("/browse_roots")

    assert response.status_code == 200
    assert response.get_json()["roots"] == [{
        "type": "directory",
        "name": Path.home().resolve().name,
        "path": str(Path.home().resolve()),
        "mtime": "",
        "mtime_epoch": Path.home().resolve().stat().st_mtime,
    }]


def test_allowed_roots_parsed_from_environment(monkeypatch, tmp_path):
    root1 = tmp_path / "music"
    root2 = tmp_path / "videos"
    root1.mkdir()
    root2.mkdir()
    monkeypatch.setenv(
        "CHORDIFIER_MEDIA_ROOTS",
        f"{root1}{os.path.pathsep}{root2}",
    )
    app_wrapper, _ = make_client()

    assert app_wrapper.allowed_roots is not None
    assert len(app_wrapper.allowed_roots) == 2
    assert Path(root1) in app_wrapper.allowed_roots


def test_browse_roots_lists_only_configured_roots(monkeypatch, tmp_path):
    root1 = tmp_path / "music"
    root2 = tmp_path / "videos"
    root1.mkdir()
    root2.mkdir()
    monkeypatch.setenv(
        "CHORDIFIER_MEDIA_ROOTS",
        f"{root1}{os.path.pathsep}{root2}",
    )
    _, client = make_client()

    roots = client.get("/browse_roots").get_json()["roots"]

    assert [root["path"] for root in roots] == [str(root1), str(root2)]


def test_list_files_hides_parent_at_allowed_root(monkeypatch, tmp_path):
    root = tmp_path / "music"
    nested = root / "album"
    nested.mkdir(parents=True)
    monkeypatch.setenv("CHORDIFIER_MEDIA_ROOTS", str(root))
    _, client = make_client()

    root_payload = client.post(
        "/list_files",
        json={"dirname": str(root), "matchstring": "", "structured": True},
    ).get_json()
    nested_payload = client.post(
        "/list_files",
        json={"dirname": str(nested), "matchstring": "", "structured": True},
    ).get_json()

    assert root_payload["parent_dir"] is None
    assert nested_payload["parent_dir"] == str(root)


def test_allowed_roots_rejects_non_directory(monkeypatch):
    monkeypatch.setenv("CHORDIFIER_MEDIA_ROOTS", "/nonexistent/path")
    with pytest.raises(ValueError, match="not a directory"):
        FlaskMP4App()


def test_allowed_roots_rejects_empty_path_entry(monkeypatch, tmp_path):
    monkeypatch.setenv("CHORDIFIER_MEDIA_ROOTS", f"{tmp_path}{os.pathsep}")

    with pytest.raises(ValueError, match="empty path entry"):
        FlaskMP4App()


def test_existing_directory_accepts_path_inside_allowed_root(monkeypatch, tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    monkeypatch.setenv("CHORDIFIER_MEDIA_ROOTS", str(root))
    app_wrapper, _ = make_client()
    subdir = root / "subdir"
    subdir.mkdir()

    directory = app_wrapper._existing_directory(str(subdir))

    assert directory == subdir


def test_existing_directory_rejects_path_outside_allowed_root(monkeypatch, tmp_path):
    root = tmp_path / "allowed"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    monkeypatch.setenv("CHORDIFIER_MEDIA_ROOTS", str(root))
    app_wrapper, _ = make_client()

    try:
        app_wrapper._existing_directory(str(outside))
    except PermissionError as error:
        assert "outside allowed media roots" in str(error)
    else:
        raise AssertionError("should reject path outside allowed root")


def test_existing_directory_permissive_when_no_roots_configured(tmp_path):
    app_wrapper, _ = make_client()
    directory = tmp_path / "anydir"
    directory.mkdir()

    result = app_wrapper._existing_directory(str(directory))

    assert result == directory


def test_list_files_rejects_directory_outside_roots(monkeypatch, tmp_path):
    root = tmp_path / "allowed"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "song.mp4").write_bytes(b"x")
    monkeypatch.setenv("CHORDIFIER_MEDIA_ROOTS", str(root))
    _, client = make_client()

    response = client.post(
        "/list_files",
        json={"dirname": str(outside), "matchstring": ""},
    )

    assert response.status_code == 403
    assert "outside allowed media roots" in response.get_json()["error"]


def test_load_file_rejects_symlink_escape_outside_allowed_root(monkeypatch, tmp_path):
    root = tmp_path / "allowed"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "song.mp4").write_bytes(b"x")
    (root / "linked.mp4").symlink_to(outside / "song.mp4")
    monkeypatch.setenv("CHORDIFIER_MEDIA_ROOTS", str(root))
    _, client = make_client()

    response = client.post(
        "/load_file",
        json={"dirname": str(root), "filename": "linked.mp4"},
    )

    assert response.status_code == 403


# ── analysis tracks route tests ──────────────────────────────────────

def test_load_file_soft_fallback_for_unavailable_track_ids(tmp_path):
    app_wrapper, client = make_client()
    media = tmp_path / "song.mp4"
    media.write_bytes(b"not used")
    chord_dir = tmp_path / ".chordflask"
    chord_dir.mkdir()
    track = ChordData()
    track.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "C"}])
    track.set_rhythm_track("qm_barbeattracker", bpm=120, beat_times=[0.0])
    track.save_to_file(str(chord_dir / "song.json"))

    response = client.post(
        "/load_file",
        json={
            "dirname": str(tmp_path),
            "filename": "song.mp4 | 0M",
            "chord_track_id": "nonexistent",
            "rhythm_track_id": "also_missing",
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ready"
    assert payload["active_chord_track_id"] == "chordino"
    assert payload["active_rhythm_track_id"] == "qm_barbeattracker"


def test_update_analysis_tracks_rejects_one_valid_one_invalid(tmp_path):
    app_wrapper, client = make_client()
    activate_analyzed_media(app_wrapper, tmp_path)

    from mp4playerflask import MP4PlayerFlask
    track = ChordData(app_wrapper.file_repr.get("json"))
    track.set_chord_track("custom", [{"timestamp": 0.0, "chord": "G"}])
    track.save_to_file(app_wrapper.file_repr.get("json"))
    app_wrapper.player = MP4PlayerFlask(app_wrapper.file_repr)
    app_wrapper.player.set_prefer_flats(True)
    app_wrapper.player.set_repeat_mode("changes")

    response = client.post(
        "/update_analysis_tracks",
        json={"chord_track_id": "custom", "rhythm_track_id": "nonexistent"},
    )
    assert response.status_code == 400
    assert "not available" in response.get_json()["error"]
    assert app_wrapper.player.chord_data.active_chord_track_id == "chordino"
    assert app_wrapper.player.chord_data.active_rhythm_track_id == "qm_barbeattracker"


def test_update_analysis_tracks_success_rerenders_position(tmp_path):
    app_wrapper, client = make_client()
    activate_analyzed_media(app_wrapper, tmp_path)

    from mp4playerflask import MP4PlayerFlask
    track = ChordData(app_wrapper.file_repr.get("json"))
    track.set_chord_track("custom", [{"timestamp": 0.0, "chord": "G"}])
    track.save_to_file(app_wrapper.file_repr.get("json"))
    app_wrapper.player = MP4PlayerFlask(app_wrapper.file_repr)
    app_wrapper.player.set_prefer_flats(True)
    app_wrapper.player.set_repeat_mode("changes")
    app_wrapper.current_position = 1.25
    old_view = app_wrapper.player.playback_view
    rendered_positions = []
    app_wrapper.player.update_position = rendered_positions.append

    response = client.post(
        "/update_analysis_tracks",
        json={"chord_track_id": "custom"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["active_chord_track_id"] == "custom"
    assert app_wrapper.player.playback_view is not old_view
    assert rendered_positions == [1.25]


def test_add_foreign_track_and_select_via_api(tmp_path):
    app_wrapper, client = make_client()
    activate_analyzed_media(app_wrapper, tmp_path)

    from mp4playerflask import MP4PlayerFlask
    app_wrapper.player = MP4PlayerFlask(app_wrapper.file_repr)
    app_wrapper.player.set_prefer_flats(True)
    app_wrapper.player.set_repeat_mode("changes")

    app_wrapper.player.chord_data.set_chord_track(
        "custom", [{"timestamp": 0.0, "chord": "G"}],
        metadata={"display_name": "Custom Source"},
    )

    response = client.post(
        "/update_analysis_tracks",
        json={"chord_track_id": "custom"},
    )
    assert response.status_code == 200
    state = response.get_json()
    assert state["active_chord_track_id"] == "custom"
    tracks = state["available_chord_tracks"]
    names = {t["id"]: t["display_name"] for t in tracks}
    assert names["custom"] == "Custom Source"


def test_chord_grid_uses_compact_responsive_desktop_layout():
    _, client = make_client()

    body = client.get("/").get_data(as_text=True)
    workspace_rule = body[
        body.index(".workspace {"):
        body.index(".video-panel,")
    ]
    chord_header_rule = body[
        body.index(".chord-header {"):
        body.index(".chord-status {")
    ]
    callback_rule = body[
        body.index("#callbackContainer {"):
        body.index(".control-bar {")
    ]
    desktop_rule = body[
        body.index("@media (min-width: 801px) and (min-height: 600px)"):
        body.index("@media (max-width: 800px)")
    ]

    assert "minmax(0, 11fr) minmax(0, 9fr)" in workspace_rule
    assert "min-height: 420px" in workspace_rule
    assert "padding: 6px 12px" in chord_header_rule
    assert "padding: 8px 12px" in callback_rule
    assert "clamp(14px, min(1.35vw, 3vh), 21px)" in callback_rule
    assert "grid-template-rows: minmax(0, 1fr) auto" in desktop_rule
    assert "font-size: clamp(9px, min(2.75cqw, 3.9cqh), 21px)" in desktop_rule
    assert "@media (max-width: 800px)" in body


def test_responsive_layout_reserves_space_for_controls_and_stacks_cleanly():
    _, client = make_client()

    body = client.get("/").get_data(as_text=True)
    app_rule = body[
        body.index(".app {"):
        body.index(".topbar {")
    ]
    control_bar_rule = body[
        body.index(".control-bar {"):
        body.index(".controls {")
    ]
    desktop_rule = body[
        body.index("@media (min-width: 801px) and (min-height: 600px)"):
        body.index("@media (max-width: 800px)")
    ]
    narrow_rule = body[
        body.index("@media (max-width: 800px)"):
        body.index("@media (max-width: 640px)")
    ]

    assert "padding: 8px 0 0" in app_rule
    assert "position: fixed" not in control_bar_rule
    assert "overflow: hidden" in desktop_rule
    assert "container-type: size" in desktop_rule
    assert "grid-template-columns: 1fr" in narrow_rule
    assert "aspect-ratio: 16 / 9" in narrow_rule
    assert "min-height: 320px" in narrow_rule


def test_chord_grid_stays_plain_text_with_one_container_reference():
    _, client = make_client()

    body = client.get("/").get_data(as_text=True)

    assert '<pre id="callbackOutput"></pre>' in body
    declarations = [
        line for line in body.splitlines()
        if "callbackContainer" in line and "getElementById" in line
    ]
    assert len(declarations) == 1
