import fcntl
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FLASK_DIR = REPO_ROOT / "flask"

if str(FLASK_DIR) not in sys.path:
    sys.path.insert(0, str(FLASK_DIR))

import chordflask.analysis_worker as analysis_worker
from chordflask.analysis_queue import AnalysisQueue
from chordflask.analysis_worker import AnalysisWorker, WorkerSupervisor
from chordflask_base import ChordData
from chordflask.chordflask_config import ANALYSIS_DIR_NAME
from chordflask.filerepr import FileRepr


class FakeProcess:
    def __init__(self, running=True, timeout=False):
        self.returncode = None if running else 0
        self.timeout = timeout
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True

    def wait(self, timeout):
        if self.timeout and not self.killed:
            raise subprocess.TimeoutExpired("worker", timeout)
        self.returncode = 0

    def kill(self):
        self.killed = True


def _save_analysis(file_repr, *, chord="C", bpm=120):
    track = ChordData()
    track.set_chord_track(
        "chordino", [{"timestamp": 0.0, "chord": chord}]
    )
    track.set_rhythm_track(
        "qm_barbeattracker", bpm=bpm, beat_times=[0.0]
    )
    track.save_to_file(file_repr.get("json"))


def test_worker_lock_reports_running_only_while_held(tmp_path):
    queue = AnalysisQueue(tmp_path)

    assert AnalysisWorker.is_running(queue) is False

    lock_file = tmp_path / "analysis_worker.lock"
    with lock_file.open("a+") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert AnalysisWorker.is_running(queue) is True

    assert AnalysisWorker.is_running(queue) is False


def test_supervisor_starts_source_worker_and_stops_owned_child(tmp_path, monkeypatch):
    queue = AnalysisQueue(tmp_path)
    process = FakeProcess()
    commands = []

    def process_factory(command, **kwargs):
        commands.append((command, kwargs))
        return process

    monkeypatch.setattr(analysis_worker.sys, "frozen", False, raising=False)
    supervisor = WorkerSupervisor(queue, process_factory=process_factory)

    assert supervisor.start() is True
    assert commands == [(
        [sys.executable, "-m", "chordflask", "--worker"],
        {"start_new_session": True},
    )]
    assert supervisor.child_running() is True

    supervisor.stop()

    assert process.terminated is True
    assert process.killed is False


def test_supervisor_uses_frozen_executable(tmp_path, monkeypatch):
    queue = AnalysisQueue(tmp_path)
    commands = []
    monkeypatch.setattr(analysis_worker.sys, "frozen", True, raising=False)
    monkeypatch.setattr(analysis_worker.sys, "executable", "/opt/chordflask/chordflask")

    supervisor = WorkerSupervisor(
        queue,
        process_factory=lambda command, **kwargs: commands.append((command, kwargs)) or FakeProcess(),
    )

    assert supervisor.start() is True
    assert commands == [(
        ["/opt/chordflask/chordflask", "--worker"],
        {"start_new_session": True},
    )]


def test_supervisor_accepts_existing_external_worker(tmp_path):
    queue = AnalysisQueue(tmp_path)
    calls = []
    lock_file = tmp_path / "analysis_worker.lock"
    lock_file.touch()

    with lock_file.open("a+") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        supervisor = WorkerSupervisor(
            queue,
            process_factory=lambda command, **kwargs: calls.append((command, kwargs)),
        )
        assert supervisor.start() is False

    assert calls == []
    assert supervisor.child_running() is False


def test_supervisor_kills_child_that_ignores_termination(tmp_path):
    process = FakeProcess(timeout=True)
    supervisor = WorkerSupervisor(
        AnalysisQueue(tmp_path),
        process_factory=lambda command, **kwargs: process,
    )
    supervisor.start()

    supervisor.stop()

    assert process.terminated is True
    assert process.killed is True


def test_forced_reanalysis_replaces_builtins_and_preserves_other_tracks(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    analysis_dir = tmp_path / ANALYSIS_DIR_NAME
    analysis_dir.mkdir()
    current_repr = FileRepr(str(media), datapath=str(analysis_dir))

    current = ChordData()
    current.set_chord_track(
        "chordino", [{"timestamp": 0.0, "chord": "C"}]
    )
    current.set_chord_track(
        "madmom", [{"timestamp": 0.0, "chord": "Dm"}],
        metadata={"version": "1"},
    )
    current.set_chord_track(
        "pytorch", [{"timestamp": 0.0, "chord": "Em"}],
        metadata={"model": "future"},
    )
    current.set_chord_track(
        "pytorch_v2", [{"timestamp": 0.0, "chord": "F"}],
        metadata={"display_name": "PyTorch V2 (experimental)"},
    )
    current.set_chord_track(
        "reference", [{"timestamp": 0.0, "chord": "X"}],
        metadata={"display_name": "Reference", "source": "trusted-midi"},
    )
    current.set_rhythm_track(
        "qm_barbeattracker", bpm=100, beat_times=[0.0]
    )
    current.set_rhythm_track(
        "pytorch", bpm=90, beat_times=[0.0, 0.67],
        metadata={"model": "future-rhythm"},
    )
    current.user_data = {"notes": "keep"}
    current.transpose(2)
    current.set_prefer_flats(False)
    current.save_to_file(current_repr.get("json"))

    class FreshAnalyzer:
        def __init__(self, media_path, output_dir):
            self.file_repr = FileRepr(media_path, datapath=output_dir)

        def process(self):
            _save_analysis(self.file_repr, chord="G", bpm=130)

    worker = AnalysisWorker(
        queue=AnalysisQueue(tmp_path / "queue"), analyzer_cls=FreshAnalyzer
    )
    worker._analyze(str(media), force=True)

    loaded = ChordData(current_repr.get("json"))
    assert loaded.chord_track_chords("chordino") == [
        {"timestamp": 0.0, "chord": "G"}
    ]
    assert loaded.bpm == 130
    assert loaded.chord_track_chords("madmom") == [
        {"timestamp": 0.0, "chord": "Dm"}
    ]
    assert loaded.chord_track_metadata("madmom") == {"version": "1"}
    assert loaded.chord_track_chords("pytorch") == [
        {"timestamp": 0.0, "chord": "Em"}
    ]
    assert loaded.chord_track_chords("pytorch_v2") == [
        {"timestamp": 0.0, "chord": "F"}
    ]
    assert loaded.chord_track_metadata("pytorch_v2") == {
        "display_name": "PyTorch V2 (experimental)"
    }
    assert loaded.chord_track_chords("reference") == [
        {"timestamp": 0.0, "chord": "X"}
    ]
    assert loaded.chord_track_metadata("reference") == {
        "display_name": "Reference",
        "source": "trusted-midi",
    }
    assert loaded.rhythm_track_data("pytorch")["bpm"] == 90
    assert loaded.user_data == {"notes": "keep"}
    assert loaded.transpose_semitones == 2
    assert loaded.prefer_flats is False


def test_failed_forced_reanalysis_leaves_current_json_unchanged(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    analysis_dir = tmp_path / ANALYSIS_DIR_NAME
    analysis_dir.mkdir()
    current_repr = FileRepr(str(media), datapath=str(analysis_dir))
    _save_analysis(current_repr)
    original = Path(current_repr.get("json")).read_bytes()

    class InvalidAnalyzer:
        def __init__(self, media_path, output_dir):
            self.file_repr = FileRepr(media_path, datapath=output_dir)

        def process(self):
            Path(self.file_repr.get("json")).write_text(
                '{"schema_version": 3, "chord_tracks": []}',
                encoding="utf-8",
            )

    worker = AnalysisWorker(
        queue=AnalysisQueue(tmp_path / "queue"), analyzer_cls=InvalidAnalyzer
    )

    try:
        worker._analyze(str(media), force=True)
    except RuntimeError as error:
        assert "invalid chord data" in str(error).lower()
    else:
        raise AssertionError("invalid replacement analysis must fail")

    assert Path(current_repr.get("json")).read_bytes() == original
