import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
FLASK_DIR = REPO_ROOT / "flask"

if str(FLASK_DIR) not in sys.path:
    sys.path.insert(0, str(FLASK_DIR))

from mido import MidiFile, tick2second
from music21 import converter

from chordanalyzer import ChordAnalysisService, ChordAnalyzer, ChordExporter
from chorddata import ChordData
from filerepr import FileRepr


class FakeConverter:
    def __init__(self):
        self.calls = []

    def ensure_mp3(self, file_repr):
        self.calls.append(file_repr.get())
        return file_repr.get("mp3")


class FakeAnalyzer:
    def __init__(self):
        self.calls = []

    def analyze(self, mp3_path, use_madmom=False):
        self.calls.append((mp3_path, use_madmom))
        chord_data = ChordData()
        chord_data.set_base_chords([
            {"timestamp": 0.0, "chord": "C"},
        ], beat_times=[0.0, 1.0])
        chord_data.bpm = 120
        return chord_data


class FakeExporter:
    def __init__(self):
        self.calls = []

    def write_midi_and_musicxml(self, chord_data, file_repr):
        self.calls.append((chord_data, file_repr.get("xml"), file_repr.get("mid")))


class FailingAnalyzer:
    def analyze(self, mp3_path, use_madmom=False):
        raise RuntimeError("analysis failed")


class FailingExporter:
    def write_midi_and_musicxml(self, chord_data, file_repr):
        raise RuntimeError("export failed")


def test_analysis_service_loads_existing_json_without_reanalysis(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"not used")
    file_repr = FileRepr(str(media), create=True)
    existing = ChordData()
    existing.set_base_chords([
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 1.0, "chord": "G"},
    ], beat_times=[0.0, 1.0])
    existing.bpm = 99
    existing.save_to_file(file_repr.get("json"))
    converter = FakeConverter()
    analyzer = FakeAnalyzer()
    exporter = FakeExporter()
    service = ChordAnalysisService(converter=converter, analyzer=analyzer, exporter=exporter)

    loaded = service.ensure_analyzed(file_repr, use_madmom=True)

    assert loaded.get_chords() == [(0.0, "C"), (1.0, "G")]
    assert loaded.bpm == 99
    assert converter.calls == []
    assert analyzer.calls == []
    assert exporter.calls == []


def test_analysis_service_generates_json_and_exports_when_missing(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"not used")
    file_repr = FileRepr(str(media), create=True)
    converter = FakeConverter()
    analyzer = FakeAnalyzer()
    exporter = FakeExporter()
    service = ChordAnalysisService(converter=converter, analyzer=analyzer, exporter=exporter)

    chord_data = service.ensure_analyzed(file_repr, use_madmom=True)

    assert converter.calls == [file_repr.get()]
    assert analyzer.calls == [(file_repr.get("mp3"), True)]
    assert exporter.calls == [(chord_data, file_repr.get("xml"), file_repr.get("mid"))]
    assert Path(file_repr.get("json")).is_file()


def test_analysis_service_uses_converter_returned_audio_path(tmp_path):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"not used")
    file_repr = FileRepr(str(media), create=True)

    class SourceConverter(FakeConverter):
        def ensure_mp3(self, file_repr):
            self.calls.append(file_repr.get())
            return file_repr.get()

    converter = SourceConverter()
    analyzer = FakeAnalyzer()
    service = ChordAnalysisService(
        converter=converter,
        analyzer=analyzer,
        exporter=FakeExporter(),
    )

    service.ensure_analyzed(file_repr)

    assert converter.calls == [str(media)]
    assert analyzer.calls == [(str(media), False)]
    assert not Path(file_repr.get("mp3")).exists()


def test_analysis_service_can_skip_midi_export(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"not used")
    file_repr = FileRepr(str(media), create=True)
    exporter = FakeExporter()
    service = ChordAnalysisService(
        converter=FakeConverter(),
        analyzer=FakeAnalyzer(),
        exporter=exporter,
    )

    service.ensure_analyzed(file_repr, export_midi=False)

    assert exporter.calls == []


def test_analysis_service_propagates_analyzer_failure(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"not used")
    file_repr = FileRepr(str(media), create=True)
    service = ChordAnalysisService(
        converter=FakeConverter(),
        analyzer=FailingAnalyzer(),
        exporter=FakeExporter(),
    )

    with pytest.raises(RuntimeError, match="analysis failed"):
        service.ensure_analyzed(file_repr)

    assert not Path(file_repr.get("json")).exists()


def test_analysis_service_writes_completion_json_only_after_exports(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"not used")
    file_repr = FileRepr(str(media), create=True)
    service = ChordAnalysisService(
        converter=FakeConverter(),
        analyzer=FakeAnalyzer(),
        exporter=FailingExporter(),
    )

    with pytest.raises(RuntimeError, match="export failed"):
        service.ensure_analyzed(file_repr)

    assert not Path(file_repr.get("json")).exists()


def test_chord_exporter_preserves_destination_and_cleans_temp_on_failure(tmp_path):
    destination = tmp_path / "song.xml"
    destination.write_text("old", encoding="utf-8")

    class FailingScore:
        def write(self, output_format, fp):
            Path(fp).write_text("partial", encoding="utf-8")
            raise RuntimeError("write failed")

    with pytest.raises(RuntimeError, match="write failed"):
        ChordExporter._ChordExporter__atomic_score_write(
            FailingScore(), "musicxml", destination
        )

    assert destination.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.glob(".song.export-*")) == []


def test_compatibility_facade_reports_analyzer_failure(tmp_path, capsys):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"not used")
    analyzer = ChordAnalyzer(str(media))
    analyzer.audio_analyzer = FailingAnalyzer()

    assert analyzer.analyze_chords() is False
    assert "Error analyzing chords: analysis failed" in capsys.readouterr().out


def test_chord_exporter_uses_chord_timestamps_for_musicxml_and_midi(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"not used")
    file_repr = FileRepr(str(media), create=True)
    chord_data = ChordData()
    chord_data.bpm = 60
    chord_data.meter_signature = 4
    chord_data.set_base_chords([
        {"timestamp": 1.5, "chord": "C"},
        {"timestamp": 3.0, "chord": "G"},
        {"timestamp": 4.25, "chord": "N"},
    ])

    ChordExporter().write_midi_and_musicxml(chord_data, file_repr)

    xml_score = converter.parse(file_repr.get("xml"))
    xml_events = list(xml_score.parts[0].flatten().notesAndRests)
    assert (round(float(xml_events[0].offset), 3), round(float(xml_events[0].quarterLength), 3)) == (0.0, 1.5)
    assert [round(float(event.offset), 3) for event in xml_score.parts[0].flatten().getElementsByClass("Chord")[:2]] == [1.5, 3.0]
    assert any(round(float(event.offset), 3) == 4.25 for event in xml_events if event.isRest)

    midi_file = MidiFile(file_repr.get("mid"))
    tempo = next(
        message.tempo
        for track in midi_file.tracks
        for message in track
        if message.type == "set_tempo"
    )
    note_on_times = []
    for track in midi_file.tracks:
        ticks = 0
        for message in track:
            ticks += message.time
            if message.type == "note_on" and message.velocity > 0:
                note_on_times.append(round(tick2second(ticks, midi_file.ticks_per_beat, tempo), 3))
    assert sorted(set(note_on_times)) == [1.5, 3.0]
    assert round(midi_file.length, 3) == 5.25


def test_chord_analyzer_defaults_to_chordflask_directory_and_delegates_process(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"not used")
    analyzer = ChordAnalyzer(str(media))
    calls = []
    expected = ChordData()
    expected.set_base_chords([
        {"timestamp": 0.0, "chord": "Am"},
    ])

    class FakeService:
        def ensure_analyzed(self, file_repr, use_madmom=False):
            calls.append((file_repr, use_madmom))
            return expected

    analyzer.analysis_service = FakeService()

    analyzer.process(use_madmom=True)

    assert analyzer.file_repr.datapath == str(tmp_path / ".chordflask")
    assert calls == [(analyzer.file_repr, True)]
    assert analyzer.chord_data is expected
