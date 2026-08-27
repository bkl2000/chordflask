import logging
import subprocess
import sys
import types
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]

import chordflask.audio_analyzer as audio_analyzer_mod
import chordflask.vamp_runtime as vamp_runtime_mod
from chordflask.chordanalyzer import AudioAnalyzer
from chordflask_base import ChordData
from chordflask.chordflask_config import ANALYSIS_SAMPLE_RATE


def test_default_analysis_profile_uses_44100_hz():
    assert ANALYSIS_SAMPLE_RATE == 44100
    assert AudioAnalyzer().sample_rate == ANALYSIS_SAMPLE_RATE
    assert ChordData().sr == ANALYSIS_SAMPLE_RATE


def test_quantize_beats_is_opt_in():
    detected_beats = [0.0, 0.51, 1.04, 1.58]
    analyzer = AudioAnalyzer()

    assert analyzer.quantize_beats is False
    assert analyzer._quantize_beats(120, detected_beats) != detected_beats
    assert len(analyzer._quantize_beats(120, detected_beats)) == len(detected_beats)


def test_qm_beatcounts_define_timestamps_bar_phase_and_tempo(monkeypatch):
    features = [
        {"timestamp": timestamp, "label": str(number)}
        for timestamp, number in [
            (0.1, 4),
            (0.6, 1),
            (1.1, 2),
            (1.6, 3),
            (2.1, 4),
            (2.6, 1),
        ]
    ]

    def collect(y, sr, plugin, output, parameters):
        assert plugin == "qm-vamp-plugins:qm-barbeattracker"
        assert output == "beatcounts"
        assert parameters == {"bpb": 4}
        return {"list": features}

    monkeypatch.setattr(audio_analyzer_mod.vamp, "collect", collect)

    bpm, beat_times, beat_numbers = AudioAnalyzer()._detect_beat_grid([0.0], 22050)

    assert bpm == 120
    assert beat_times == [0.1, 0.6, 1.1, 1.6, 2.1, 2.6]
    assert beat_numbers == [4, 1, 2, 3, 4, 1]


def test_qm_beat_grid_falls_back_for_beatless_audio(monkeypatch):
    monkeypatch.setattr(
        audio_analyzer_mod.vamp,
        "collect",
        lambda *args, **kwargs: {"list": []},
    )
    monkeypatch.setattr(
        audio_analyzer_mod,
        "detect_tempo_from_audio",
        lambda **kwargs: (90, [0.2, 0.866]),
    )

    assert AudioAnalyzer()._detect_beat_grid([0.0], 22050) == (
        90,
        [0.2, 0.866],
        [],
    )


def test_qm_meter_is_explicit_instead_of_guessed_from_beat_labels():
    analyzer = AudioAnalyzer(beats_per_bar=3)

    assert analyzer.detect_meter("not-opened.mp3") == 3


def test_feature_beat_number_parses_valid_labels():
    assert AudioAnalyzer._feature_beat_number({"label": "4"}) == 4
    assert AudioAnalyzer._feature_beat_number({"label": "1"}) == 1
    assert AudioAnalyzer._feature_beat_number({"label": "", "values": [2.0]}) == 2


def test_feature_beat_number_rejects_malformed_labels():
    assert AudioAnalyzer._feature_beat_number({"label": "not-a-number"}) is None
    assert AudioAnalyzer._feature_beat_number({"label": ""}) is None
    assert AudioAnalyzer._feature_beat_number({"label": "1.5"}) is None
    assert AudioAnalyzer._feature_beat_number({"label": "x", "values": [1.5]}) is None


def test_detect_beat_grid_skips_malformed_labels_and_warns(monkeypatch, caplog):
    features = [
        {"timestamp": 0.1, "label": "1"},
        {"timestamp": 0.6, "label": "not-a-number"},
        {"timestamp": 1.1, "label": "2"},
        {"timestamp": 1.6, "label": "3"},
    ]
    monkeypatch.setattr(
        audio_analyzer_mod.vamp,
        "collect",
        lambda *args, **kwargs: {"list": features},
    )

    with caplog.at_level(logging.WARNING):
        _, beat_times, beat_numbers = AudioAnalyzer()._detect_beat_grid([0.0], 22050)

    assert beat_times == [0.1, 1.1, 1.6]
    assert beat_numbers == [1, 2, 3]
    assert "unparseable beat-number" in caplog.text


def test_chordino_uses_the_reviewed_analysis_parameters(monkeypatch):
    def collect(y, sr, plugin, parameters):
        assert y == [0.0]
        assert sr == ANALYSIS_SAMPLE_RATE
        assert plugin == "nnls-chroma:chordino"
        assert parameters == {
            "useNNLS": 1,
            "rollon": 0.02,
            "tuningmode": 1,
        }
        return {"list": [{"timestamp": 0.0, "label": "C"}]}

    monkeypatch.setattr(audio_analyzer_mod.vamp, "collect", collect)

    chords = AudioAnalyzer()._extract_chords_vamp([0.0], ANALYSIS_SAMPLE_RATE)

    assert chords == [{"timestamp": 0.0, "chord": "C"}]


@pytest.mark.parametrize(
    ("use_madmom", "expected_track_id"),
    [(False, "chordino"), (True, "madmom")],
)
def test_analyze_labels_chord_and_rhythm_sources(
    monkeypatch, use_madmom, expected_track_id
):
    class PassThroughPostprocessor:
        @staticmethod
        def process(chords):
            return chords

    monkeypatch.setattr(audio_analyzer_mod, "require_system_ffmpeg", lambda: None)
    monkeypatch.setattr(vamp_runtime_mod, "require_vamp_plugins", lambda: None)
    monkeypatch.setattr(
        audio_analyzer_mod,
        "librosa",
        types.SimpleNamespace(
            load=lambda *args, **kwargs: ([0.0], ANALYSIS_SAMPLE_RATE),
            effects=types.SimpleNamespace(preemphasis=lambda samples: samples),
        ),
    )

    analyzer = AudioAnalyzer(postprocessor=PassThroughPostprocessor())
    monkeypatch.setattr(
        analyzer,
        "_detect_beat_grid",
        lambda samples, sample_rate: (120, [0.0, 0.5], [1, 2]),
    )
    monkeypatch.setattr(
        analyzer,
        "_extract_chords_vamp",
        lambda samples, sample_rate: [{"timestamp": 0.0, "chord": "C"}],
    )
    monkeypatch.setattr(
        analyzer,
        "_extract_chords_madmom",
        lambda path: [{"timestamp": 0.0, "chord": "Dm"}],
    )

    result = analyzer.analyze("song.mp3", use_madmom=use_madmom)

    assert result.available_chord_track_ids == [expected_track_id]
    assert result.available_rhythm_track_ids == ["qm_barbeattracker"]


def test_madmom_conversion_checks_ffmpeg_and_removes_temporary_file(tmp_path, monkeypatch):
    features = types.ModuleType("madmom.features")
    chords = types.ModuleType("madmom.features.chords")
    chords.CRFChordRecognitionProcessor = object
    monkeypatch.setitem(sys.modules, "madmom", types.ModuleType("madmom"))
    monkeypatch.setitem(sys.modules, "madmom.features", features)
    monkeypatch.setitem(sys.modules, "madmom.features.chords", chords)
    wav_path = tmp_path / "temporary.wav"

    class TemporaryFile:
        name = str(wav_path)

        def __enter__(self):
            wav_path.touch()
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(audio_analyzer_mod.tempfile, "NamedTemporaryFile", lambda **kwargs: TemporaryFile())

    def fail_ffmpeg(*args, **kwargs):
        assert kwargs["check"] is True
        raise subprocess.CalledProcessError(1, args[0], stderr="invalid input")

    monkeypatch.setattr(audio_analyzer_mod.subprocess, "run", fail_ffmpeg)

    try:
        AudioAnalyzer()._extract_chords_madmom("broken.mp3")
    except RuntimeError as error:
        assert "invalid input" in str(error)
    else:
        raise AssertionError("ffmpeg failure must be propagated")

    assert not wav_path.exists()
