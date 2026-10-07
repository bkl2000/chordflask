"""Cross-process canonical execution contracts, using only synthetic analysis."""

import fcntl
import multiprocessing as mp
from pathlib import Path

import pytest

from chordflask.analysis_queue import AnalysisQueue
from chordflask.analysis_service import ChordAnalysisService
from chordflask.analysis_worker import AnalysisWorker
from chordflask.canonical_analysis import media_analysis_lock
from chordflask.filerepr import FileRepr
from chordflask_base import ChordData, ChordTrackRepository

CTX = mp.get_context("fork")


def complete():
    data = ChordData()
    data.set_chord_track("chordino", [{"timestamp": 0., "chord": "C"}])
    data.set_rhythm_track("qm_barbeattracker", bpm=60, meter_signature=4,
                          beat_times=[0., 1.], beat_numbers=[1, 2])
    return data


def partial(path):
    data = ChordData()
    data.set_chord_track("btc", [{"timestamp": 0., "chord": "G"}])
    data.save_to_file(path)


@pytest.fixture
def synthetic(monkeypatch, tmp_path):
    from chordflask.audio_analyzer import AudioAnalyzer
    from chordflask.chord_exporter import ChordExporter

    monkeypatch.setenv("CHORDFLASK_QUEUE_DIR", str(tmp_path / "queue"))
    monkeypatch.setattr(AudioAnalyzer, "analyze", lambda *a, **k: complete())

    def export(self, data, fr):
        Path(fr.get("xml")).write_text("complete XML")
    monkeypatch.setattr(ChordExporter, "write_midi_and_musicxml", export)


def invoke(kind, media, label, attempted, done, results):
    try:
        attempted.set()
        if kind == "worker":
            AnalysisWorker(queue=AnalysisQueue(media.parent / "queue"))._analyze(media)
        elif kind == "cli":
            from chordflask.helpers.analyze_cli import _run_chordino
            assert _run_chordino(media, replace=True, dry_run=False) == 0
        elif kind == "service":
            ChordAnalysisService().ensure_analyzed(FileRepr(media, create=True))
        else:
            from chordflask.helpers.export_cli import main
            try:
                main(["--format", "markdown", str(media)])
            except SystemExit as status:
                assert status.code == 0
        results.put((label, "ok"))
    except Exception as error:
        results.put((label, str(error)))
    finally:
        done.set()


def launch(kind, media, label, results):
    attempted, done = CTX.Event(), CTX.Event()
    process = CTX.Process(name=label, target=invoke,
                          args=(kind, media, label, attempted, done, results))
    process.start()
    assert attempted.wait(5)
    return process, done


def reap(process):
    process.join(5)
    if process.is_alive():
        process.terminate()
        process.join(5)
        pytest.fail("synthetic child failed to finish")
    assert process.exitcode == 0


@pytest.mark.parametrize("first_kind,second_kind", [
    ("worker", "cli"), ("cli", "cli"), ("worker", "service"), ("worker", "export"),
])
def test_same_media_serializes_and_keeps_live_workdir(
    tmp_path, monkeypatch, synthetic, first_kind, second_kind,
):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"current source")
    fr = FileRepr(media, create=True)
    if first_kind == "cli":
        complete().save_to_file(fr.get("json"))
    abandoned = Path(fr.datapath) / ".song.analyze-other-owner"
    abandoned.mkdir()
    results, stages = CTX.Queue(), CTX.Queue()
    entered = {name: CTX.Event() for name in ("first", "second")}
    releases = {name: CTX.Event() for name in entered}
    original = ChordAnalysisService.analyze_staged

    def block(self, staged, *args):
        name = mp.current_process().name
        stages.put((name, staged.datapath))
        entered[name].set()
        assert releases[name].wait(10)
        return original(self, staged, *args)
    monkeypatch.setattr(ChordAnalysisService, "analyze_staged", block)
    first = second = None
    try:
        first, first_done = launch(first_kind, media, "first", results)
        assert entered["first"].wait(5)
        _, directory = stages.get(timeout=5)
        workdir = Path(directory)
        assert workdir.is_dir()
        lock = Path(fr.datapath) / ".song.analysis.lock"
        with lock.open("a+") as handle:
            with pytest.raises(BlockingIOError):
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        second, second_done = launch(second_kind, media, "second", results)
        assert not entered["second"].wait(.2)
        assert not second_done.is_set()
        assert workdir.is_dir() and abandoned.is_dir()
        # Optional/user writer is deliberately outside the canonical lock.
        if not Path(fr.get("json")).exists():
            partial(fr.get("json"))
        data = ChordTrackRepository().load(fr.get("json"))
        data.set_chord_track("new_optional", [{"timestamp": 0., "chord": "Am"}])
        data.user_data = {"notes": "added while second waits"}
        data.save_to_file(fr.get("json"))
        releases["first"].set()
        assert first_done.wait(5)
        releases["second"].set()
        assert second_done.wait(5)
        reap(first)
        reap(second)
        assert sorted(results.get(timeout=5) for _ in range(2)) == [("first", "ok"), ("second", "ok")]
        final = ChordTrackRepository().load(fr.get("json"))
        assert final.has_chord_track("new_optional")
        assert final.user_data == {"notes": "added while second waits"}
        assert not workdir.exists() and abandoned.exists()
        assert list(Path(fr.datapath).glob(".song.reanalyze-*")) == []
        assert list(Path(fr.datapath).glob(".song.analyze-*")) == [abandoned]
    finally:
        for release in releases.values():
            release.set()
        for process in (first, second):
            if process is not None and process.is_alive():
                process.terminate()
                process.join(5)


def test_different_media_can_analyze_independently(tmp_path, monkeypatch, synthetic):
    media = [tmp_path / f"song{i}.mp3" for i in range(2)]
    for path in media:
        path.write_bytes(b"current")
    entered = {name: CTX.Event() for name in ("first", "second")}
    release = CTX.Event()
    original = ChordAnalysisService.analyze_staged

    def block(self, staged, *args):
        entered[mp.current_process().name].set()
        assert release.wait(10)
        return original(self, staged, *args)
    monkeypatch.setattr(ChordAnalysisService, "analyze_staged", block)
    results = CTX.Queue()
    children = []
    try:
        for kind, path, name in zip(("worker", "service"), media, entered, strict=True):
            process, _ = launch(kind, path, name, results)
            children.append(process)
        assert all(event.wait(5) for event in entered.values())
        release.set()
        for process in children:
            reap(process)
        assert sorted(results.get(timeout=5) for _ in children) == [("first", "ok"), ("second", "ok")]
    finally:
        release.set()
        for process in children:
            if process.is_alive():
                process.terminate()
                process.join(5)


def test_failed_first_releases_lock_preserves_prior_json_and_artifacts(
    tmp_path, monkeypatch, synthetic,
):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"current")
    fr = FileRepr(media, create=True)
    partial(fr.get("json"))
    prior = Path(fr.get("json")).read_bytes()
    Path(fr.get("mp3")).write_bytes(b"prior audio")
    Path(fr.get("xml")).write_bytes(b"prior XML")
    entered = {name: CTX.Event() for name in ("first", "second")}
    releases = {name: CTX.Event() for name in entered}
    original = ChordAnalysisService.analyze_staged

    def run(self, staged, *args):
        name = mp.current_process().name
        entered[name].set()
        assert releases[name].wait(10)
        if name == "first":
            Path(staged.get("mp3")).write_bytes(b"partial audio")
            Path(staged.get("xml")).write_bytes(b"partial XML")
            raise RuntimeError("synthetic conversion failure")
        return original(self, staged, *args)
    monkeypatch.setattr(ChordAnalysisService, "analyze_staged", run)
    results = CTX.Queue()
    first = second = None
    try:
        first, first_done = launch("service", media, "first", results)
        assert entered["first"].wait(5)
        second, second_done = launch("service", media, "second", results)
        assert not entered["second"].wait(.2)
        releases["first"].set()
        assert first_done.wait(5) and entered["second"].wait(5)
        assert Path(fr.get("json")).read_bytes() == prior
        assert Path(fr.get("mp3")).read_bytes() == b"prior audio"
        assert Path(fr.get("xml")).read_bytes() == b"prior XML"
        releases["second"].set()
        assert second_done.wait(5)
        reap(first)
        reap(second)
        assert sorted(results.get(timeout=5) for _ in range(2)) == [
            ("first", "synthetic conversion failure"), ("second", "ok"),
        ]
        assert not list(Path(fr.datapath).glob(".song.reanalyze-*"))
        with media_analysis_lock(media):
            pass
    finally:
        for event in releases.values():
            event.set()
        for process in (first, second):
            if process is not None and process.is_alive():
                process.terminate()
                process.join(5)


@pytest.mark.parametrize("phase", ["conversion", "analysis", "export"])
def test_service_failure_stages_all_artifacts_and_leaves_prior_state(tmp_path, phase):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"source")
    fr = FileRepr(media, create=True)
    partial(fr.get("json"))
    protected = {}
    for suffix, content in (("mp3", b"old audio"), ("xml", b"old XML"), ("mid", b"old MIDI")):
        path = Path(fr.get(suffix))
        path.write_bytes(content)
        protected[path] = content
    protected[Path(fr.get("json"))] = Path(fr.get("json")).read_bytes()

    class Converter:
        def ensure_mp3(self, staged):
            Path(staged.get("mp3")).write_bytes(b"new audio")
            if phase == "conversion":
                raise RuntimeError("conversion failure")
            return staged.get("mp3")

    class Analyzer:
        def analyze(self, audio, use_madmom=False):
            if phase == "analysis":
                raise RuntimeError("analysis failure")
            return complete()

    class Exporter:
        def write_midi_and_musicxml(self, data, staged):
            Path(staged.get("xml")).write_text("new XML")
            raise RuntimeError("export failure")

    service = ChordAnalysisService(Converter(), Analyzer(), Exporter())
    with pytest.raises(RuntimeError, match=phase + " failure"):
        service.ensure_analyzed(fr)
    assert all(path.read_bytes() == content for path, content in protected.items())
    assert not list(Path(fr.datapath).glob(".song.reanalyze-*"))
    with media_analysis_lock(media):
        pass


@pytest.mark.parametrize("force", [False, True])
def test_killed_analysis_workdir_is_removed_under_lock_on_retry(tmp_path, force):
    from chordflask.canonical_analysis import execute_analysis

    media = tmp_path / "song.mp4"
    media.write_bytes(b"source")
    fr = FileRepr(media, create=True)
    if force:
        complete().save_to_file(fr.get("json"))
    store = Path(fr.datapath)
    protected = {media: media.read_bytes()}
    for name in ("song.mp3", "song.xml", "song.mid", "song.lrc", "unrelated.txt",
                 ".song.reanalyze-abcdefgh"):
        path = store / name
        path.write_bytes(b"keep")
        protected[path] = path.read_bytes()
    if force:
        protected[Path(fr.get("json"))] = Path(fr.get("json")).read_bytes()
    for name in ("stems", ".other.analyze-abcdefgh", ".song.analyze-user-notes"):
        path = store / name / "keep.txt"
        path.parent.mkdir()
        path.write_bytes(b"keep")
        protected[path] = path.read_bytes()
    # Even an exactly matching symlink must never be followed or removed.
    link = store / ".song.analyze-abcdefgh"
    link.symlink_to(tmp_path, target_is_directory=True)
    parent, child_pipe = CTX.Pipe()

    def interrupted():
        def stage(staged):
            Path(staged.get("mp3")).write_bytes(b"incomplete")
            complete().save_to_file(staged.get("json"))
            child_pipe.send(staged.datapath)
            child_pipe.recv()
        execute_analysis(fr, stage, force=force)

    child = CTX.Process(target=interrupted)
    child.start()
    try:
        assert parent.poll(5)
        orphan = Path(parent.recv())
        assert orphan.is_dir()
        child.kill()
        child.join(5)
        assert not child.is_alive()
        assert orphan.is_dir()  # SIGKILL bypasses TemporaryDirectory cleanup.
        assert all(path.read_bytes() == content for path, content in protected.items())

        def retry(staged):
            assert not orphan.exists()
            assert link.is_symlink()
            assert all(path.read_bytes() == content for path, content in protected.items())
            complete().save_to_file(staged.get("json"))
        execute_analysis(fr, retry, force=force)
        assert not orphan.exists()
        assert ChordTrackRepository().load(fr.get("json")).has_chord_track("chordino")
    finally:
        if child.is_alive():
            child.kill()
        child.join(5)
        parent.close()
        child_pipe.close()
