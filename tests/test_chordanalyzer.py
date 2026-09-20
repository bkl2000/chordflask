import logging
import subprocess
import sys
import types
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]

import chordflask.audio_analyzer as audio_analyzer_mod
import chordflask.vamp_runtime as vamp_runtime_mod
from chordflask.audio_analyzer import ORIGINAL_RHYTHM_TRACK
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


def test_existing_positional_audio_analyzer_arguments_remain_compatible(monkeypatch):
    monkeypatch.delenv("CHORDFLASK_AUTO_CORRECT_BEAT_GRID", raising=False)
    postprocessor = object()

    analyzer = AudioAnalyzer(22050, True, postprocessor, 3)

    assert analyzer.sample_rate == 22050
    assert analyzer.quantize_beats is True
    assert analyzer.postprocessor is postprocessor
    assert analyzer.beats_per_bar == 3
    assert analyzer.auto_correct_beat_grid is False


def _beat_numbers(count, beats_per_bar=4):
    return [index % beats_per_bar + 1 for index in range(count)]


def test_automatic_beat_grid_correction_is_off_by_default(monkeypatch):
    monkeypatch.delenv("CHORDFLASK_AUTO_CORRECT_BEAT_GRID", raising=False)

    analyzer = AudioAnalyzer()

    assert analyzer.auto_correct_beat_grid is False


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_automatic_beat_grid_correction_can_be_enabled_from_environment(
    monkeypatch, value
):
    monkeypatch.setenv("CHORDFLASK_AUTO_CORRECT_BEAT_GRID", value)

    assert AudioAnalyzer().auto_correct_beat_grid is True


def test_invalid_automatic_beat_grid_environment_value_is_rejected(monkeypatch):
    monkeypatch.setenv("CHORDFLASK_AUTO_CORRECT_BEAT_GRID", "sometimes")

    with pytest.raises(ValueError, match="CHORDFLASK_AUTO_CORRECT_BEAT_GRID"):
        AudioAnalyzer()


def test_automatic_and_forced_beat_quantization_are_mutually_exclusive():
    with pytest.raises(ValueError, match="cannot both be enabled"):
        AudioAnalyzer(quantize_beats=True, auto_correct_beat_grid=True)


def test_automatic_beat_grid_uses_precise_tempo_and_robust_origin():
    interval = 60 / 123.4
    jitter = [-0.006, 0.003, -0.002, 0.005, 0.0]
    beats = [
        0.237 + index * interval + jitter[index % len(jitter)]
        for index in range(80)
    ]

    corrected, result = AudioAnalyzer()._auto_correct_beats(
        beats, _beat_numbers(len(beats))
    )

    assert result["applied"] is True
    assert result["estimated_bpm"] == pytest.approx(123.4, rel=2e-3)
    assert corrected[0] != pytest.approx(beats[0])
    assert corrected[1] - corrected[0] == pytest.approx(
        60 / result["estimated_bpm"], abs=2e-6
    )
    assert len(corrected) == len(beats)


def test_automatic_beat_grid_tolerates_first_beat_and_isolated_outliers():
    beats = [0.3 + index * 0.5 for index in range(48)]
    beats[0] += 0.08
    beats[23] -= 0.06

    corrected, result = AudioAnalyzer()._auto_correct_beats(
        beats, _beat_numbers(len(beats))
    )

    assert result["applied"] is True
    assert corrected[0] == pytest.approx(0.3)
    assert corrected[23] == pytest.approx(11.8)


@pytest.mark.parametrize("change", ["missing", "additional"])
def test_automatic_beat_grid_rejects_missing_or_additional_beat(change):
    beats = [0.2 + index * 0.5 for index in range(40)]
    numbers = _beat_numbers(len(beats))
    if change == "missing":
        del beats[17]
        del numbers[17]
    else:
        beats.insert(17, beats[16] + 0.25)
        numbers.insert(17, numbers[16])
    original = list(beats)

    corrected, result = AudioAnalyzer()._auto_correct_beats(beats, numbers)

    assert result["applied"] is False
    assert corrected is beats
    assert corrected == original
    assert "missing or additional" in result["reason"]


@pytest.mark.parametrize("tempo_change", ["slow", "abrupt"])
def test_automatic_beat_grid_rejects_tempo_changes(tempo_change):
    beats = [0.2]
    for index in range(1, 80):
        if tempo_change == "slow":
            interval = 0.48 + index * 0.001
        else:
            interval = 0.48 if index < 40 else 0.54
        beats.append(beats[-1] + interval)
    original = list(beats)

    corrected, result = AudioAnalyzer()._auto_correct_beats(
        beats, _beat_numbers(len(beats))
    )

    assert result["applied"] is False
    assert corrected is beats
    assert corrected == original
    assert result["reason"] in {
        "local tempo is not constant",
        "section offsets show systematic drift",
        "grid deviation is too large",
    }


def test_automatic_beat_grid_diagnostics_include_measurements_and_limits(caplog):
    beats = [0.2 + index * 0.5 for index in range(80)]
    beats[20:60] = [timestamp + 0.06 for timestamp in beats[20:60]]
    analyzer = AudioAnalyzer()

    corrected, result = analyzer._auto_correct_beats(
        beats, _beat_numbers(len(beats))
    )
    with caplog.at_level(logging.INFO):
        analyzer._log_beat_grid_correction(result)

    assert corrected is beats
    assert result["reason"] == "section offsets show systematic drift"
    assert "section_drift=" in result["details"]
    assert "limit=" in result["details"]
    assert "median_error=" in caplog.text
    assert "p95_error=" in caplog.text
    assert "max_error=" in caplog.text
    assert "ms (" in caplog.text
    assert "% beat" in caplog.text


def test_automatic_beat_grid_rejects_too_few_and_exact_beats_unchanged():
    analyzer = AudioAnalyzer()
    short = [0.2 + index * 0.5 for index in range(15)]
    exact = [0.2 + index * 0.5 for index in range(32)]

    short_result, short_decision = analyzer._auto_correct_beats(
        short, _beat_numbers(len(short))
    )
    exact_result, exact_decision = analyzer._auto_correct_beats(
        exact, _beat_numbers(len(exact))
    )

    assert short_result is short
    assert short_decision["reason"].startswith("too few beats")
    assert exact_result is exact
    assert exact_decision["reason"] == "beats are already on an exact grid"


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


def _stub_analysis_dependencies(monkeypatch):
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

    _stub_analysis_dependencies(monkeypatch)

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
    assert result.rhythm_track_data("qm_barbeattracker") == {
        "bpm": 120,
        "meter_signature": 4,
        "beat_times": [0.0, 0.5],
        "beat_numbers": [1, 2],
        "metadata": {},
    }


def test_corrected_and_original_rhythm_tracks_survive_roundtrip(
    tmp_path, monkeypatch
):
    class PassThroughPostprocessor:
        @staticmethod
        def process(chords):
            return chords

    _stub_analysis_dependencies(monkeypatch)
    interval = 60 / 121.7
    original_times = [
        0.25 + index * interval + (0.004 if index % 2 else -0.004)
        for index in range(32)
    ]
    beat_numbers = _beat_numbers(len(original_times))
    analyzer = AudioAnalyzer(
        auto_correct_beat_grid=True,
        postprocessor=PassThroughPostprocessor(),
    )
    monkeypatch.setattr(
        analyzer,
        "_detect_beat_grid",
        lambda samples, sample_rate: (122, original_times, beat_numbers),
    )
    monkeypatch.setattr(
        analyzer,
        "_extract_chords_vamp",
        lambda samples, sample_rate: [{"timestamp": 0.0, "chord": "C"}],
    )

    result = analyzer.analyze("song.mp3")
    path = tmp_path / "analysis.json"
    result.save_to_file(path)
    loaded = ChordData()
    loaded.load_from_file(path)

    assert loaded.available_rhythm_track_ids == [
        "qm_barbeattracker",
        ORIGINAL_RHYTHM_TRACK,
    ]
    assert loaded.active_rhythm_track_id == "qm_barbeattracker"
    assert loaded.beat_times != original_times
    assert loaded.beat_numbers == beat_numbers
    loaded.select_rhythm_track(ORIGINAL_RHYTHM_TRACK)
    assert loaded.beat_times == original_times
    assert loaded.beat_numbers == beat_numbers
    assert loaded.bpm == 122


def test_rejected_automatic_correction_stores_only_unchanged_default_track(
    monkeypatch, caplog
):
    class PassThroughPostprocessor:
        @staticmethod
        def process(chords):
            return chords

    _stub_analysis_dependencies(monkeypatch)
    beat_times = [0.2 + index * 0.5 for index in range(12)]
    beat_numbers = _beat_numbers(len(beat_times))
    analyzer = AudioAnalyzer(
        auto_correct_beat_grid=True,
        postprocessor=PassThroughPostprocessor(),
    )
    monkeypatch.setattr(
        analyzer,
        "_detect_beat_grid",
        lambda samples, sample_rate: (120, beat_times, beat_numbers),
    )
    monkeypatch.setattr(
        analyzer,
        "_extract_chords_vamp",
        lambda samples, sample_rate: [{"timestamp": 0.0, "chord": "C"}],
    )

    with caplog.at_level(logging.INFO):
        result = analyzer.analyze("song.mp3")

    assert result.available_rhythm_track_ids == ["qm_barbeattracker"]
    assert result.rhythm_track_data("qm_barbeattracker") == {
        "bpm": 120,
        "meter_signature": 4,
        "beat_times": beat_times,
        "beat_numbers": beat_numbers,
        "metadata": {},
    }
    assert "Automatic beat-grid correction rejected" in caplog.text
    assert "reason=too few beats" in caplog.text


def test_forced_quantization_keeps_its_existing_single_track_behavior(monkeypatch):
    class PassThroughPostprocessor:
        @staticmethod
        def process(chords):
            return chords

    _stub_analysis_dependencies(monkeypatch)
    analyzer = AudioAnalyzer(
        quantize_beats=True,
        postprocessor=PassThroughPostprocessor(),
    )
    monkeypatch.setattr(
        analyzer,
        "_detect_beat_grid",
        lambda samples, sample_rate: (120, [0.1, 0.62, 1.09], [1, 2, 3]),
    )
    monkeypatch.setattr(
        analyzer,
        "_extract_chords_vamp",
        lambda samples, sample_rate: [{"timestamp": 0.0, "chord": "C"}],
    )

    result = analyzer.analyze("song.mp3")

    assert result.available_rhythm_track_ids == ["qm_barbeattracker"]
    assert result.beat_times == [0.1, 0.6, 1.1]


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
