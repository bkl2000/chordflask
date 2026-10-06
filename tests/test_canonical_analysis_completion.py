"""Canonical completion is separate from valid Schema-v3 optional tracks."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from chordflask.analysis_queue import AnalysisQueue
from chordflask.analysis_service import ChordAnalysisService
from chordflask.analysis_worker import AnalysisWorker
from chordflask.app import CLIENT_COOKIE, FlaskMP4App
from chordflask.filerepr import FileRepr
from chordflask.helpers import analyze_cli
from chordflask_base import (
    DEFAULT_CHORD_TRACK,
    DEFAULT_RHYTHM_TRACK,
    ChordData,
    ChordTrackRepository,
    is_canonical_analysis_complete,
)


CASES = ["stems", "btc", "chordino", "qm", "foreign", "complete", "complete-foreign"]
COMPLETE = {"complete", "complete-foreign"}


def audio_set():
    return {
        "provider": "demucs", "model": "htdemucs",
        "tracks": {
            stem: {
                "path": f".chordflask/stems/{stem}.flac", "format": "flac",
                "sample_rate": 44100, "channels": 2, "sample_count": 44100,
                "duration": 1.0, "size": 100, "sha256": "a" * 64,
            }
            for stem in ("bass", "drums", "other", "vocals")
        },
        "metadata": {
            "source": {
                "sha256": "b" * 64, "size": 1000, "sample_rate": 44100,
                "channels": 2, "sample_count": 44100, "duration": 1.0,
            },
            "sync": {
                "reference": "canonical_extracted_audio", "start_sample": 0,
                "source_sample_count": 44100, "stem_sample_count": 44100,
                "max_tail_delta_samples": 2205,
                "tail_adjustment_samples": dict.fromkeys(("bass", "drums", "other", "vocals"), 0),
            },
            "source_timeline": {"available": False},
        },
    }


def set_chords(data, track_id):
    data.set_chord_track(track_id, [{"timestamp": 0.0, "chord": "C"}])


def set_rhythm(data, track_id):
    data.set_rhythm_track(
        track_id, bpm=120, meter_signature=4,
        beat_times=[0.0, 0.5], beat_numbers=[1, 2],
    )


def canonical_data():
    data = ChordData()
    set_chords(data, DEFAULT_CHORD_TRACK)
    set_rhythm(data, DEFAULT_RHYTHM_TRACK)
    return data


@pytest.fixture(params=CASES)
def analysis_case(request, tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDFLASK_QUEUE_DIR", str(tmp_path / "queue"))
    kind = request.param
    media = tmp_path / "song.mp4"
    media.write_bytes(b"synthetic media")
    file_repr = FileRepr(str(media), create=True)
    data = canonical_data() if kind in COMPLETE else ChordData()
    if kind == "chordino":
        set_chords(data, DEFAULT_CHORD_TRACK)
    if kind == "qm":
        set_rhythm(data, DEFAULT_RHYTHM_TRACK)
    if kind == "btc" or "foreign" in kind:
        set_chords(data, "btc")
    if kind == "stems" or "foreign" in kind:
        data.set_audio_track("demucs:htdemucs", audio_set())
    if "foreign" in kind:
        set_chords(data, "chordflask_v3")
        set_rhythm(data, "custom_rhythm")
        data.set_chord_track(
            "user_edited", [{"timestamp": 0.0, "chord": "G"}],
            metadata={"sources": {"rhythm": "custom_rhythm"}},
        )
    data.user_data = {"notes": "preserve"}
    data.transpose(2)
    data.set_prefer_flats(False)
    data.save_to_file(file_repr.get("json"))
    return SimpleNamespace(
        media=media, file_repr=file_repr, data=data, complete=kind in COMPLETE
    )


def assert_preserved(before, after):
    for track_id in before.available_chord_track_ids:
        if track_id != DEFAULT_CHORD_TRACK:
            assert after.chord_track_chords(track_id) == before.chord_track_chords(track_id)
            assert after.chord_track_metadata(track_id) == before.chord_track_metadata(track_id)
    for track_id in before.available_rhythm_track_ids:
        if track_id != DEFAULT_RHYTHM_TRACK:
            assert after.rhythm_track_data(track_id) == before.rhythm_track_data(track_id)
    for set_id in before.available_audio_track_ids:
        assert after.audio_track_data(set_id) == before.audio_track_data(set_id)
    assert after.user_data == before.user_data
    assert after.transpose_semitones == before.transpose_semitones
    assert after.prefer_flats == before.prefer_flats


def test_validity_does_not_imply_completion(analysis_case):
    case = analysis_case
    loaded = ChordTrackRepository().load(case.file_repr.get("json"))
    assert is_canonical_analysis_complete(loaded) is case.complete
    assert AnalysisWorker._json_is_valid(case.file_repr.get("json"))


def test_gui_queues_partial_analysis_without_replacing_player(analysis_case):
    case = analysis_case
    app = FlaskMP4App(roots=str(case.media.parent))
    client = app.app.test_client()
    client.set_cookie(CLIENT_COOKIE, "test-client")
    state = app.clients.get_or_create("test-client")
    previous_player = object()
    previous_file = object()
    state.player = previous_player
    state.file_repr = previous_file
    response = client.post("/load_file", json={
        "dirname": str(case.media.parent), "filename": case.media.name,
    })
    assert response.status_code == 200
    if case.complete:
        assert response.get_json()["status"] == "ready"
        assert response.get_json()["analysis_valid"] is True
        assert app.analysis_queue.status()["pending"] == []
    else:
        assert response.get_json()["status"] == "queued"
        assert response.get_json()["json_file"] is None
        assert state.player is previous_player
        assert state.file_repr is previous_file
        assert len(app.analysis_queue.status()["pending"]) == 1
    assert_preserved(case.data, ChordData(case.file_repr.get("json")))


def test_batch_skips_only_complete_analysis(analysis_case):
    case = analysis_case
    app = FlaskMP4App(roots=str(case.media.parent))
    response = app.app.test_client().post("/enqueue_batch", json={
        "dirname": str(case.media.parent), "filenames": [case.media.name], "limit": 1,
    })
    assert response.status_code == 200
    assert response.get_json()["skipped_analyzed_count"] == int(case.complete)
    assert response.get_json()["queued_count"] == int(not case.complete)


def test_worker_completes_partial_and_preserves_tracks(analysis_case):
    case = analysis_case
    calls = []

    class Analyzer:
        def __init__(self, media_path, data_dir):
            self.file_repr = FileRepr(media_path, datapath=data_dir)

        def process(self):
            calls.append(self.file_repr.get())
            canonical_data().save_to_file(self.file_repr.get("json"))

    worker = AnalysisWorker(
        queue=AnalysisQueue(case.media.parent / "queue"), analyzer_cls=Analyzer
    )
    worker.queue.enqueue(case.media)
    assert worker.run_once() is True
    assert worker.queue.status() == {"pending": [], "failed": []}
    assert calls == ([] if case.complete else [str(case.media)])
    result = ChordData(case.file_repr.get("json"))
    assert is_canonical_analysis_complete(result)
    assert_preserved(case.data, result)


def test_service_completes_partial_and_preserves_tracks(analysis_case):
    case = analysis_case
    calls = []

    class Analyzer:
        def analyze(self, audio_path, use_madmom=False):
            calls.append(audio_path)
            return canonical_data()

    converter = SimpleNamespace(ensure_mp3=lambda file_repr: file_repr.get())
    service = ChordAnalysisService(converter=converter, analyzer=Analyzer(), exporter=object())
    result = service.ensure_analyzed(case.file_repr, export_midi=False)
    assert calls == ([] if case.complete else [str(case.media)])
    assert is_canonical_analysis_complete(result)
    assert_preserved(case.data, result)
    assert_preserved(case.data, ChordData(case.file_repr.get("json")))


def test_cli_reports_incomplete_or_legacy_complete(analysis_case, capsys):
    case = analysis_case
    assert analyze_cli._chordino_status(case.media) == ("legacy" if case.complete else "todo")
    with pytest.raises(SystemExit) as result:
        analyze_cli.main(["--dry-run", str(case.media)])
    assert result.value.code == 0
    assert ("LEGACY" if case.complete else "TODO") in capsys.readouterr().out


def test_empty_canonical_tracks_count_as_complete():
    data = ChordData()
    data.set_chord_track(DEFAULT_CHORD_TRACK, [])
    data.set_rhythm_track(DEFAULT_RHYTHM_TRACK)
    assert is_canonical_analysis_complete(data)


@pytest.mark.parametrize("path", ["worker", "service"])
def test_incomplete_producer_output_does_not_replace_partial_json(tmp_path, path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"synthetic")
    file_repr = FileRepr(str(media), create=True)
    partial = ChordData()
    set_chords(partial, "btc")
    partial.save_to_file(file_repr.get("json"))
    original = Path(file_repr.get("json")).read_bytes()

    class IncompleteAnalyzer:
        def __init__(self, media_path=None, data_dir=None):
            if media_path:
                self.file_repr = FileRepr(media_path, datapath=data_dir)

        def analyze(self, *args, **kwargs):
            data = ChordData()
            set_chords(data, DEFAULT_CHORD_TRACK)
            return data

        def process(self):
            self.analyze().save_to_file(self.file_repr.get("json"))

    with pytest.raises(RuntimeError, match="complete canonical tracks"):
        if path == "worker":
            AnalysisWorker(
                queue=AnalysisQueue(tmp_path / "queue"), analyzer_cls=IncompleteAnalyzer
            )._analyze(media)
        else:
            ChordAnalysisService(
                converter=SimpleNamespace(ensure_mp3=lambda file_repr: file_repr.get()),
                analyzer=IncompleteAnalyzer(), exporter=object(),
            ).ensure_analyzed(file_repr, export_midi=False)
    assert Path(file_repr.get("json")).read_bytes() == original
    assert list(Path(file_repr.datapath).glob(".song.reanalyze-*")) == []


@pytest.mark.parametrize("path", ["worker", "service"])
def test_partial_completion_preserves_edited_qm_snapshot(tmp_path, path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"synthetic")
    file_repr = FileRepr(str(media), create=True)
    data = ChordData()
    set_rhythm(data, DEFAULT_RHYTHM_TRACK)
    data.set_chord_track(
        "user_edited", [{"timestamp": 0.0, "chord": "G"}],
        metadata={"sources": {"rhythm": DEFAULT_RHYTHM_TRACK}},
    )
    original_rhythm = data.rhythm_track_data(DEFAULT_RHYTHM_TRACK)
    data.save_to_file(file_repr.get("json"))

    class Analyzer:
        def __init__(self, media_path=None, data_dir=None):
            if media_path:
                self.file_repr = FileRepr(media_path, datapath=data_dir)

        def analyze(self, *args, **kwargs):
            return canonical_data()

        def process(self):
            self.analyze().save_to_file(self.file_repr.get("json"))

    if path == "worker":
        AnalysisWorker(queue=AnalysisQueue(tmp_path / "queue"), analyzer_cls=Analyzer)._analyze(media)
    else:
        ChordAnalysisService(
            converter=SimpleNamespace(ensure_mp3=lambda file_repr: file_repr.get()),
            analyzer=Analyzer(), exporter=object(),
        ).ensure_analyzed(file_repr, export_midi=False)
    result = ChordData(file_repr.get("json"))
    assert is_canonical_analysis_complete(result)
    assert result.chord_track_metadata("user_edited")["sources"]["rhythm"] == "user_edited_rhythm"
    assert result.rhythm_track_data("user_edited_rhythm")["beat_times"] == original_rhythm["beat_times"]
    assert result.chord_track_chords("user_edited") == data.chord_track_chords("user_edited")
