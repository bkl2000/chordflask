"""Current-source audio across worker, converter, service and CLI paths."""

import os
from pathlib import Path

import pytest

from chordflask import media_converter
from chordflask.analysis_queue import AnalysisQueue
from chordflask.analysis_worker import AnalysisWorker
from chordflask.audio_analyzer import AudioAnalyzer
from chordflask.chord_exporter import ChordExporter
from chordflask.chordanalyzer import ChordAnalyzer
from chordflask.filerepr import FileRepr
from chordflask.helpers import analyze_cli, export_cli
from chordflask_base import ChordTrackRepository


@pytest.fixture
def audio_runtime(monkeypatch, tmp_path):
    """Use real orchestration with synthetic decoding and analysis."""
    monkeypatch.setenv("CHORDFLASK_QUEUE_DIR", str(tmp_path / "queue"))
    converted = []
    analyzed = []

    class Video:
        def __init__(self, path):
            self.content = Path(path).read_bytes()
            self.audio = self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def write_audiofile(self, path):
            converted.append(self.content)
            Path(path).write_bytes(b"audio:" + self.content)

    def analyze(self, path, use_madmom=False):
        from chordflask_base import ChordData

        analyzed.append(Path(path).read_bytes())
        data = ChordData()
        data.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "C"}])
        data.set_rhythm_track(
            "qm_barbeattracker", bpm=120, meter_signature=4,
            beat_times=[0.0, 0.5], beat_numbers=[1, 2],
        )
        return data

    monkeypatch.setattr(media_converter, "require_system_ffmpeg", lambda: None)
    monkeypatch.setattr(media_converter, "VideoFileClip", Video)
    monkeypatch.setattr(AudioAnalyzer, "analyze", analyze)
    monkeypatch.setattr(
        ChordExporter, "write_midi_and_musicxml", lambda *args: None
    )
    return converted, analyzed


def worker_for(tmp_path):
    return AnalysisWorker(
        queue=AnalysisQueue(tmp_path / "queue"), analyzer_cls=ChordAnalyzer
    )


@pytest.mark.parametrize("suffix", [".mp4", ".webm"])
@pytest.mark.parametrize("replacement", ["size", "mtime", "unchanged"])
def test_forced_analysis_converts_current_source(
    tmp_path, audio_runtime, suffix, replacement
):
    converted, analyzed = audio_runtime
    media = tmp_path / f"song{suffix}"
    media.write_bytes(b"A")
    worker = worker_for(tmp_path)
    worker._analyze(media)
    file_repr = FileRepr(str(media))
    assert Path(file_repr.get("mp3")).read_bytes() == b"audio:A"

    data = ChordTrackRepository().load(file_repr.get("json"))
    data.set_chord_track(
        "btc", [{"timestamp": 0.0, "chord": "G"}], metadata={"keep": True}
    )
    data.user_data = {"notes": "keep"}
    data.save_to_file(file_repr.get("json"))
    unrelated = tmp_path / ".chordflask" / "unrelated.mp3"
    unrelated.write_bytes(b"leave alone")
    stamp = media.stat()
    if replacement == "size":
        media.write_bytes(b"source B with different size")
        os.utime(media, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        assert media.stat().st_size != stamp.st_size
        assert media.stat().st_mtime_ns == stamp.st_mtime_ns
    elif replacement == "mtime":
        media.write_bytes(b"B")
        os.utime(media, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000_000))
        assert media.stat().st_size == stamp.st_size
        assert media.stat().st_mtime_ns != stamp.st_mtime_ns
    current = media.read_bytes()

    worker._analyze(media, force=True)

    assert converted == [b"A", current]
    assert analyzed == [b"audio:A", b"audio:" + current]
    assert Path(file_repr.get("mp3")).read_bytes() == b"audio:" + current
    result = ChordTrackRepository().load(file_repr.get("json"))
    assert result.chord_track_metadata("btc") == {"keep": True}
    assert result.user_data == {"notes": "keep"}
    assert unrelated.read_bytes() == b"leave alone"
    assert list(Path(file_repr.datapath).glob(".song.reanalyze-*")) == []


def test_cli_replace_converts_current_source(tmp_path, audio_runtime):
    converted, analyzed = audio_runtime
    media = tmp_path / "song.mp4"
    media.write_bytes(b"A")
    worker_for(tmp_path)._analyze(media)
    media.write_bytes(b"B")

    with pytest.raises(SystemExit) as result:
        analyze_cli.main(["--replace", str(media)])

    assert result.value.code == 0
    assert converted == [b"A", b"B"]
    assert analyzed == [b"audio:A", b"audio:B"]


@pytest.mark.parametrize("path", ["service", "export"])
def test_direct_analysis_reconverts_existing_mp3(tmp_path, audio_runtime, path):
    converted, analyzed = audio_runtime
    media = tmp_path / "song.mp4"
    media.write_bytes(b"B")
    file_repr = FileRepr(str(media), create=True)
    Path(file_repr.get("mp3")).write_bytes(b"audio:A")

    if path == "service":
        ChordAnalyzer(str(media)).analysis_service.ensure_analyzed(file_repr)
    else:
        with pytest.raises(SystemExit) as result:
            export_cli.main(["--format", "markdown", str(media)])
        assert result.value.code == 0

    assert converted == [b"B"]
    assert analyzed == [b"audio:B"]
    assert Path(file_repr.get("mp3")).read_bytes() == b"audio:B"
    assert Path(file_repr.get("json")).is_file()


def test_original_mp3_uses_current_source(tmp_path, audio_runtime):
    converted, analyzed = audio_runtime
    media = tmp_path / "song.mp3"
    media.write_bytes(b"A")
    worker = worker_for(tmp_path)
    worker._analyze(media)
    file_repr = FileRepr(str(media))
    Path(file_repr.get("mp3")).write_bytes(b"unused derived cache")
    media.write_bytes(b"B")

    worker._analyze(media, force=True)

    assert converted == []
    assert analyzed == [b"A", b"B"]
    assert media.read_bytes() == b"B"
    assert Path(file_repr.get("mp3")).read_bytes() == b"unused derived cache"


@pytest.mark.parametrize("path", ["worker", "service"])
def test_conversion_failure_preserves_good_state(
    tmp_path, monkeypatch, audio_runtime, path
):
    converted, analyzed = audio_runtime
    media = tmp_path / "song.mp4"
    media.write_bytes(b"A")
    worker = worker_for(tmp_path)
    worker._analyze(media)
    file_repr = FileRepr(str(media))
    json_path = Path(file_repr.get("json"))
    original_json = json_path.read_bytes()
    if path == "service":
        json_path.unlink()  # Direct service only analyzes when JSON is absent.
    media.write_bytes(b"B")
    artifacts = {}
    for suffix in ("mp3", "mid", "xml"):
        artifact = Path(file_repr.get(suffix))
        if not artifact.exists():
            artifact.write_bytes(b"prior valid artifact")
        artifacts[artifact] = artifact.read_bytes()
    unrelated = Path(file_repr.datapath) / "unrelated.mp3"
    unrelated.write_bytes(b"unrelated")

    class FailingAudio:
        def write_audiofile(self, path):
            Path(path).write_bytes(b"partial corrupt audio")
            raise RuntimeError("conversion failed")

    class FailingVideo:
        audio = FailingAudio()

        def __init__(self, path):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(media_converter, "VideoFileClip", FailingVideo)
    with pytest.raises(RuntimeError, match="conversion failed"):
        if path == "worker":
            worker._analyze(media, force=True)
        else:
            ChordAnalyzer(str(media)).process()

    assert converted == [b"A"]
    assert analyzed == [b"audio:A"]
    if path == "worker":
        assert json_path.read_bytes() == original_json
    else:
        assert not json_path.exists()
    for artifact, content in artifacts.items():
        assert artifact.read_bytes() == content
    assert unrelated.read_bytes() == b"unrelated"
    assert list(Path(file_repr.datapath).glob(".song.reanalyze-*")) == []
    assert list(Path(file_repr.datapath).glob(".song.convert-*")) == []
