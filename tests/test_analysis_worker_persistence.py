from pathlib import Path

from chordflask.analysis_queue import AnalysisQueue
from chordflask.analysis_worker import AnalysisWorker
from chordflask_base import ChordData


def _setup_job(tmp_path, force=False):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"test media")
    queue = AnalysisQueue(tmp_path / "queue")
    queue.enqueue(media, force=force)
    analysis_dir = tmp_path / ".chordflask"
    analysis_dir.mkdir()
    return media, queue, analysis_dir


def _write_track(path, chord, *, transpose=0, prefer_flats=True, user_data=None):
    track = ChordData(prefer_flats=prefer_flats)
    track.set_base_chords([{"timestamp": 0.0, "chord": chord}])
    track.transpose(transpose)
    track.user_data = user_data or {}
    track.save_to_file(path)
    return track


def _audio_track_set(provider, model, seed):
    return {
        "provider": provider,
        "model": model,
        "tracks": {
            stem: {
                "path": f".chordflask/stems/{model}/song/generation-{seed}/{stem}.flac",
                "format": "flac",
                "sample_rate": 44100,
                "channels": 2,
                "sample_count": 44100,
                "duration": 1.0,
                "size": 100 + index,
                "sha256": f"{seed}{index + 1:063x}",
            }
            for index, stem in enumerate(("bass", "drums", "other", "vocals"))
        },
        "metadata": {
            "source": {
                "sha256": f"{seed}a" * 32,
                "size": 1000 + seed,
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
                    "bass": 0,
                    "drums": 0,
                    "other": 0,
                    "vocals": 0,
                },
            },
            "source_timeline": {"available": False},
        },
    }


def test_worker_preserves_corrupt_existing_analysis_before_reanalysis(tmp_path):
    media, queue, analysis_dir = _setup_job(tmp_path)
    json_path = analysis_dir / "song.json"
    corrupt_contents = "{broken existing analysis"
    json_path.write_text(corrupt_contents, encoding="utf-8")

    class ValidAnalyzer:
        def __init__(self, media_path, data_dir):
            self.data_dir = Path(data_dir)

        def process(self):
            track = ChordData()
            track.set_base_chords([{"timestamp": 0.0, "chord": "C"}])
            track.save_to_file(self.data_dir / "song.json")

    worker = AnalysisWorker(queue=queue, analyzer_cls=ValidAnalyzer)
    assert worker.run_once() is True

    backups = list(analysis_dir.glob("song.corrupt-*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == corrupt_contents
    assert json_path.exists()
    assert queue.status() == {"pending": [], "failed": []}


def test_worker_keeps_corrupt_backup_when_reanalysis_fails(tmp_path):
    media, queue, analysis_dir = _setup_job(tmp_path)
    json_path = analysis_dir / "song.json"
    corrupt_contents = "{broken existing analysis"
    json_path.write_text(corrupt_contents, encoding="utf-8")

    class FailingAnalyzer:
        def __init__(self, media_path, data_dir):
            pass

        def process(self):
            raise RuntimeError("analyzer failed")

    worker = AnalysisWorker(queue=queue, analyzer_cls=FailingAnalyzer)
    assert worker.run_once() is True

    backups = list(analysis_dir.glob("song.corrupt-*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == corrupt_contents
    assert not json_path.exists()
    assert queue.status()["pending"] == []
    assert "analyzer failed" in queue.status()["failed"][0]["error"]


def test_worker_rejects_and_preserves_invalid_new_analysis(tmp_path):
    media, queue, analysis_dir = _setup_job(tmp_path)

    class InvalidAnalyzer:
        def __init__(self, media_path, data_dir):
            self.data_dir = Path(data_dir)

        def process(self):
            (self.data_dir / "song.json").write_text("{invalid", encoding="utf-8")

    worker = AnalysisWorker(queue=queue, analyzer_cls=InvalidAnalyzer)
    assert worker.run_once() is True

    assert not (analysis_dir / "song.json").exists()
    assert len(list(analysis_dir.glob("song.corrupt-*.json"))) == 1
    assert "created invalid chord data" in queue.status()["failed"][0]["error"]


def test_worker_cleans_interrupted_work_and_publishes_json_last(tmp_path):
    media, queue, analysis_dir = _setup_job(tmp_path)
    stale_analysis = analysis_dir / ".song.analyze-crashed"
    stale_reanalysis = analysis_dir / ".song.reanalyze-crashed"
    unrelated = analysis_dir / ".other.analyze-active"
    stale_analysis.mkdir()
    stale_reanalysis.mkdir()
    unrelated.mkdir()
    (stale_analysis / "partial.mp3").write_bytes(b"partial")
    (analysis_dir / "song.mp3").write_bytes(b"old partial")

    class CompleteAnalyzer:
        def __init__(self, media_path, data_dir):
            self.data_dir = Path(data_dir)

        def process(self):
            assert not stale_analysis.exists()
            assert not stale_reanalysis.exists()
            assert unrelated.exists()
            assert not (analysis_dir / "song.mp3").exists()
            _write_track(self.data_dir / "song.json", "C")
            (self.data_dir / "song.mp3").write_bytes(b"complete audio")
            (self.data_dir / "song.xml").write_text("complete xml", encoding="utf-8")

    worker = AnalysisWorker(queue=queue, analyzer_cls=CompleteAnalyzer)

    assert worker.run_once() is True
    assert (analysis_dir / "song.mp3").read_bytes() == b"complete audio"
    assert (analysis_dir / "song.xml").read_text(encoding="utf-8") == "complete xml"
    assert (analysis_dir / "song.json").exists()
    assert unrelated.exists()
    assert list(analysis_dir.glob(".song.analyze-*")) == []
    assert queue.status() == {"pending": [], "failed": []}


def test_relative_media_path_writes_to_caller_cwd_analysis_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "misc").mkdir()
    media = tmp_path / "misc" / "song.mp4"
    media.write_bytes(b"fake media")
    queue = AnalysisQueue(tmp_path / "queue")

    class RelativeMediaAnalyzer:
        def __init__(self, media_path, data_dir):
            self.data_dir = Path(data_dir)

        def process(self):
            _write_track(self.data_dir / "song.json", "C")

    worker = AnalysisWorker(queue=queue, analyzer_cls=RelativeMediaAnalyzer)
    worker._analyze("misc/song.mp4")

    expected = tmp_path / "misc" / ".chordflask" / "song.json"
    assert expected.exists()
    assert not (tmp_path / "misc" / "misc").exists()


def test_worker_failure_leaves_no_published_partial_artifacts(tmp_path):
    media, queue, analysis_dir = _setup_job(tmp_path)

    class PartialAnalyzer:
        def __init__(self, media_path, data_dir):
            self.data_dir = Path(data_dir)

        def process(self):
            (self.data_dir / "song.mp3").write_bytes(b"partial")
            raise RuntimeError("process stopped")

    worker = AnalysisWorker(queue=queue, analyzer_cls=PartialAnalyzer)

    assert worker.run_once() is True
    assert not (analysis_dir / "song.mp3").exists()
    assert not (analysis_dir / "song.json").exists()
    assert list(analysis_dir.glob(".song.analyze-*")) == []
    assert "process stopped" in queue.status()["failed"][0]["error"]


def test_forced_reanalysis_atomically_replaces_json_and_preserves_user_data(tmp_path):
    media, queue, analysis_dir = _setup_job(tmp_path, force=True)
    json_path = analysis_dir / "song.json"
    _write_track(
        json_path,
        "C",
        transpose=-2,
        prefer_flats=False,
        user_data={"transpose": -2, "notes": {"chorus": "keep this"}},
    )
    old_bytes = json_path.read_bytes()
    (analysis_dir / "song.xml").write_text("old xml", encoding="utf-8")
    (analysis_dir / "song.mid").write_bytes(b"old midi")

    class ReplacementAnalyzer:
        def __init__(self, media_path, data_dir):
            self.data_dir = Path(data_dir)

        def process(self):
            assert json_path.read_bytes() == old_bytes
            _write_track(
                self.data_dir / "song.json",
                "G",
                user_data={"generated": "must not replace user data"},
            )
            (self.data_dir / "song.xml").write_text("new xml", encoding="utf-8")
            (self.data_dir / "song.mid").write_bytes(b"new midi")

    worker = AnalysisWorker(queue=queue, analyzer_cls=ReplacementAnalyzer)

    assert worker.run_once() is True

    replacement = ChordData(str(json_path))
    assert replacement._base_chords == [{"timestamp": 0.0, "chord": "G"}]
    assert replacement.transpose_semitones == -2
    assert replacement.prefer_flats is False
    assert replacement.user_data == {
        "transpose": -2,
        "notes": {"chorus": "keep this"},
    }
    assert json_path.read_bytes() != old_bytes
    assert (analysis_dir / "song.xml").read_text(encoding="utf-8") == "new xml"
    assert (analysis_dir / "song.mid").read_bytes() == b"new midi"
    assert list(analysis_dir.glob(".song.reanalyze-*")) == []
    assert queue.status() == {"pending": [], "failed": []}


def test_worker_preserves_foreign_tracks_during_reanalysis(tmp_path):
    media, queue, analysis_dir = _setup_job(tmp_path, force=True)
    json_path = analysis_dir / "song.json"

    current = ChordData()
    current.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "C"}])
    current.set_chord_track("pytorch", [{"timestamp": 0.0, "chord": "Am"}])
    current.set_rhythm_track(
        "qm_barbeattracker", bpm=120, meter_signature=4,
        beat_times=[0.0, 0.5, 1.0], beat_numbers=[1, 2, 3],
    )
    current.set_rhythm_track(
        "custom", bpm=100, meter_signature=3,
        beat_times=[0.0, 0.6, 1.2], beat_numbers=[1, 2, 3],
    )
    current.transpose(-2)
    current.set_prefer_flats(False)
    current.user_data = {"note": "keep"}
    demucs_set = _audio_track_set("demucs", "htdemucs", 1)
    current.set_audio_track("demucs:htdemucs", demucs_set)
    reference_set = _audio_track_set("reference", "manual", 2)
    current.set_audio_track("custom:ref", reference_set)
    current.save_to_file(json_path)

    class ReplacementAnalyzer:
        def __init__(self, media_path, data_dir):
            self.data_dir = Path(data_dir)

        def process(self):
            track = ChordData()
            track.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "G"}])
            track.set_rhythm_track(
                "qm_barbeattracker", bpm=90, meter_signature=4,
                beat_times=[0.0, 0.7], beat_numbers=[1, 2],
            )
            track.save_to_file(self.data_dir / "song.json")

    worker = AnalysisWorker(queue=queue, analyzer_cls=ReplacementAnalyzer)
    assert worker.run_once() is True

    merged = ChordData(str(json_path))
    assert set(merged.available_chord_track_ids) == {"chordino", "pytorch"}
    assert merged.chord_track_chords("pytorch") == [{"timestamp": 0.0, "chord": "Am"}]
    assert merged.chord_track_chords("chordino") == [{"timestamp": 0.0, "chord": "G"}]
    assert set(merged.available_rhythm_track_ids) == {"qm_barbeattracker", "custom"}
    assert merged.rhythm_track_data("custom")["bpm"] == 100
    assert merged.rhythm_track_data("qm_barbeattracker")["bpm"] == 90
    assert merged.transpose_semitones == -2
    assert merged.prefer_flats is False
    assert merged.user_data == {"note": "keep"}
    assert merged.available_audio_track_ids == ["custom:ref", "demucs:htdemucs"]
    assert merged.audio_track_data("demucs:htdemucs") == demucs_set
    assert merged.audio_track_data("custom:ref") == reference_set


def test_failed_forced_reanalysis_keeps_old_json_and_cleans_temporary_files(tmp_path):
    media, queue, analysis_dir = _setup_job(tmp_path, force=True)
    json_path = analysis_dir / "song.json"
    _write_track(json_path, "C", user_data={"transpose": 3})
    old_bytes = json_path.read_bytes()

    class FailingAnalyzer:
        def __init__(self, media_path, data_dir):
            self.data_dir = Path(data_dir)

        def process(self):
            (self.data_dir / "partial.txt").write_text("temporary", encoding="utf-8")
            raise RuntimeError("reanalyzer failed")

    worker = AnalysisWorker(queue=queue, analyzer_cls=FailingAnalyzer)

    assert worker.run_once() is True

    assert json_path.read_bytes() == old_bytes
    assert list(analysis_dir.glob(".song.reanalyze-*")) == []
    assert "reanalyzer failed" in queue.status()["failed"][0]["error"]
    assert queue.status()["failed"][0]["force"] is True


def test_forced_reanalysis_migrates_legacy_directory_and_preserves_user_data(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"test media")
    queue = AnalysisQueue(tmp_path / "queue")
    queue.enqueue(media, force=True)
    legacy_dir = tmp_path / ".chordy"
    legacy_dir.mkdir()
    _write_track(
        legacy_dir / "song.json",
        "C",
        transpose=3,
        user_data={"transpose": 3, "notes": "keep"},
    )

    class ReplacementAnalyzer:
        def __init__(self, media_path, data_dir):
            self.data_dir = Path(data_dir)

        def process(self):
            _write_track(self.data_dir / "song.json", "G")

    worker = AnalysisWorker(queue=queue, analyzer_cls=ReplacementAnalyzer)

    assert worker.run_once() is True
    migrated_json = tmp_path / ".chordflask" / "song.json"
    migrated = ChordData(migrated_json)
    assert migrated.user_data == {"transpose": 3, "notes": "keep"}
    assert not legacy_dir.exists()


def test_forced_reanalysis_validates_before_replacing_old_json(tmp_path):
    media, queue, analysis_dir = _setup_job(tmp_path, force=True)
    json_path = analysis_dir / "song.json"
    _write_track(json_path, "C", user_data={"marker": 12.5})
    old_bytes = json_path.read_bytes()

    class InvalidAnalyzer:
        def __init__(self, media_path, data_dir):
            self.data_dir = Path(data_dir)

        def process(self):
            (self.data_dir / "song.json").write_text("{invalid", encoding="utf-8")

    worker = AnalysisWorker(queue=queue, analyzer_cls=InvalidAnalyzer)

    assert worker.run_once() is True

    assert json_path.read_bytes() == old_bytes
    assert list(analysis_dir.glob(".song.reanalyze-*")) == []
    assert "created invalid chord data" in queue.status()["failed"][0]["error"]


def test_forced_reanalysis_leaves_missing_optional_exports_unchanged(tmp_path):
    media, queue, analysis_dir = _setup_job(tmp_path, force=True)
    _write_track(analysis_dir / "song.json", "C")
    (analysis_dir / "song.xml").write_text("old xml", encoding="utf-8")
    (analysis_dir / "song.mid").write_bytes(b"old midi")

    class JsonOnlyAnalyzer:
        def __init__(self, media_path, data_dir):
            self.data_dir = Path(data_dir)

        def process(self):
            _write_track(self.data_dir / "song.json", "F")

    worker = AnalysisWorker(queue=queue, analyzer_cls=JsonOnlyAnalyzer)

    assert worker.run_once() is True
    assert (analysis_dir / "song.xml").read_text(encoding="utf-8") == "old xml"
    assert (analysis_dir / "song.mid").read_bytes() == b"old midi"
