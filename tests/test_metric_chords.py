import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"

from chordflask_base import ChordData
from chordflask.app import FlaskMP4App, _parse_cli_args
from chordflask.metric_chords import (
    classify_beat_grid,
    filter_metric_chords,
    format_classification_diagnostic,
    is_strong_beat,
)
from chordflask.playbackview import PlaybackView


def _make_clean_grid(n_beats, meter=4, beat_interval=0.5):
    times = [i * beat_interval for i in range(n_beats)]
    numbers = [(i % meter) + 1 for i in range(n_beats)]
    return times, numbers


def test_stable_clean_grid():
    times, numbers = _make_clean_grid(64, meter=4)
    result = classify_beat_grid(times, numbers, 4)
    assert result["classification"] == "stable"
    assert result["cv"] < 0.02
    assert result["mad_ratio"] < 0.02


def test_flexible_too_few_beats():
    times, numbers = _make_clean_grid(16, meter=4)
    result = classify_beat_grid(times, numbers, 4)
    assert result["classification"] == "uncertain"
    assert "32" in result.get("reason", "")


def test_flexible_missing_beat_numbers():
    times, _ = _make_clean_grid(64, meter=4)
    result = classify_beat_grid(times, None, 4)
    assert result["classification"] == "flexible"


def test_flexible_bad_meter():
    times, numbers = _make_clean_grid(64, meter=4)
    result = classify_beat_grid(times, numbers, 0)
    assert result["classification"] == "flexible"


def test_flexible_bool_meter():
    times, numbers = _make_clean_grid(64, meter=4)
    result = classify_beat_grid(times, numbers, True)
    assert result["classification"] == "flexible"


def test_flexible_non_increasing_times():
    times, numbers = _make_clean_grid(64, meter=4)
    times[10] = times[9] - 0.1
    result = classify_beat_grid(times, numbers, 4)
    assert result["classification"] == "flexible"


def test_flexible_nan_beat_time():
    times, numbers = _make_clean_grid(64, meter=4)
    times[30] = float("nan")
    result = classify_beat_grid(times, numbers, 4)
    assert result["classification"] == "flexible"


def test_flexible_inf_beat_time():
    times, numbers = _make_clean_grid(64, meter=4)
    times[15] = float("inf")
    result = classify_beat_grid(times, numbers, 4)
    assert result["classification"] == "flexible"


def test_flexible_bool_beat_time():
    times, numbers = _make_clean_grid(64, meter=4)
    times[0] = True
    result = classify_beat_grid(times, numbers, 4)
    assert result["classification"] == "flexible"


def test_flexible_beat_number_out_of_range():
    times, numbers = _make_clean_grid(64, meter=4)
    numbers[20] = 5
    result = classify_beat_grid(times, numbers, 4)
    assert result["classification"] == "flexible"


def test_flexible_high_cv():
    n_beats = 64
    beat_interval = 0.5
    times = [i * beat_interval for i in range(n_beats)]
    for i in range(1, n_beats):
        times[i] += 0.10 * ((i % 3) - 1)
    numbers = [(i % 4) + 1 for i in range(n_beats)]
    result = classify_beat_grid(times, numbers, 4)
    assert result["classification"] == "flexible"


def test_flexible_bad_cycle():
    times, numbers = _make_clean_grid(64, meter=4)
    for i in range(1, len(numbers), 3):
        numbers[i] = 1
    result = classify_beat_grid(times, numbers, 4)
    assert result["classification"] != "stable"


def test_is_strong_beat():
    assert is_strong_beat(1, 4) is True
    assert is_strong_beat(3, 4) is True
    assert is_strong_beat(2, 4) is False
    assert is_strong_beat(4, 4) is False
    assert is_strong_beat(1, 3) is True
    assert is_strong_beat(2, 3) is False
    assert is_strong_beat(3, 3) is False
    assert is_strong_beat(1, 6) is True
    assert is_strong_beat(4, 6) is True
    assert is_strong_beat(2, 6) is False
    assert is_strong_beat(0, 4) is False
    assert is_strong_beat(1, 0) is False
    assert is_strong_beat(1, None) is False
    assert is_strong_beat(True, 4) is False
    assert is_strong_beat(1, True) is False


def test_aba_weak_beat_glitch_suppressed():
    data = ChordData()
    entries = [{"timestamp": float(i), "chord": "C"} for i in range(32)]
    entries[10] = {"timestamp": 9.45, "chord": "G"}
    entries[11] = {"timestamp": 9.80, "chord": "C"}
    data.set_base_chords(entries, beat_times=[i * 0.5 for i in range(64)])
    data.bpm = 120
    data.meter_signature = 4
    data.set_beat_numbers([(i % 4) + 1 for i in range(64)])

    beat_chords = data.get_chords_per_beat()
    filtered, classification = filter_metric_chords(
        beat_chords,
        data.beat_times,
        data.beat_numbers,
        data.beat_chord_indexes,
        data.meter_signature,
        data.chord_times,
    )
    assert classification["classification"] == "stable"
    assert beat_chords[18][1] == "C"
    assert beat_chords[19][1] == "G"
    assert beat_chords[20][1] == "C"
    assert filtered[19][1] == "C"
    assert beat_chords[0][1] == filtered[0][1]


def test_strong_beat_aba_not_suppressed():
    data = ChordData()
    entries = [{"timestamp": float(i), "chord": "C"} for i in range(32)]
    entries[4] = {"timestamp": 3.45, "chord": "G"}
    entries[5] = {"timestamp": 3.90, "chord": "C"}
    data.set_base_chords(entries, beat_times=[i * 0.5 for i in range(64)])
    data.bpm = 120
    data.meter_signature = 4
    data.set_beat_numbers([(i % 4) + 1 for i in range(64)])

    beat_chords = data.get_chords_per_beat()
    filtered, classification = filter_metric_chords(
        beat_chords,
        data.beat_times,
        data.beat_numbers,
        data.beat_chord_indexes,
        data.meter_signature,
        data.chord_times,
    )
    assert classification["classification"] == "stable"
    assert filtered == beat_chords


def test_sustained_weak_change_not_suppressed():
    data = ChordData()
    entries = [
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 4.0, "chord": "F"},
        {"timestamp": 8.0, "chord": "F"},
        {"timestamp": 12.0, "chord": "C"},
    ]
    data.set_base_chords(entries, beat_times=[i * 0.5 for i in range(64)])
    data.bpm = 120
    data.meter_signature = 4
    data.set_beat_numbers([(i % 4) + 1 for i in range(64)])

    beat_chords = data.get_chords_per_beat()
    filtered, _ = filter_metric_chords(
        beat_chords,
        data.beat_times,
        data.beat_numbers,
        data.beat_chord_indexes,
        data.meter_signature,
        data.chord_times,
    )
    for i in range(len(beat_chords)):
        assert filtered[i][1] == beat_chords[i][1], f"beat {i} changed: {beat_chords[i][1]} -> {filtered[i][1]}"


def test_odd_meter_weak_glitch_suppressed_strong_preserved():
    data = ChordData()
    entries = [{"timestamp": float(i), "chord": "C"} for i in range(32)]
    entries[10] = {"timestamp": 9.45, "chord": "G"}
    entries[11] = {"timestamp": 9.80, "chord": "C"}
    data.set_base_chords(entries, beat_times=[i * 0.5 for i in range(48)])
    data.bpm = 120
    data.meter_signature = 3
    data.set_beat_numbers([(i % 3) + 1 for i in range(48)])

    beat_chords = data.get_chords_per_beat()
    filtered, classification = filter_metric_chords(
        beat_chords,
        data.beat_times,
        data.beat_numbers,
        data.beat_chord_indexes,
        data.meter_signature,
        data.chord_times,
    )
    assert classification["classification"] == "stable"
    assert is_strong_beat(1, 3) is True
    assert is_strong_beat(2, 3) is False
    assert is_strong_beat(3, 3) is False
    assert beat_chords[19][1] == "G"
    assert filtered[19][1] == "C"


def test_legacy_no_beat_numbers_unchanged():
    data = ChordData()
    data.set_base_chords([
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 2.0, "chord": "G"},
    ], beat_times=[0.0, 1.0, 2.0, 3.0])
    data.bpm = 120
    data.meter_signature = 4

    beat_chords = data.get_chords_per_beat()
    filtered, classification = filter_metric_chords(
        beat_chords,
        data.beat_times,
        data.beat_numbers,
        data.beat_chord_indexes,
        data.meter_signature,
        data.chord_times,
    )
    assert classification["classification"] != "stable"
    assert filtered == beat_chords


def test_flag_off_preserves_default_behavior():
    data = ChordData()
    data.set_base_chords([
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 2.0, "chord": "G"},
    ], beat_times=[0.0, 1.0, 2.0, 3.0])
    data.bpm = 120

    default_output = PlaybackView(data).render(0.1)
    explicit_off_output = PlaybackView(data, metric_chords=False).render(0.1)
    assert explicit_off_output == default_output


def test_flag_on_creates_view_with_classification():
    data = ChordData()
    data.set_base_chords(
        [{"timestamp": float(i), "chord": "C"} for i in range(64)],
        beat_times=[float(i) for i in range(64)],
    )
    data.bpm = 120
    data.meter_signature = 4
    data.set_beat_numbers([(i % 4) + 1 for i in range(64)])

    view = PlaybackView(data, metric_chords=True)
    assert view._PlaybackView__metric_chords is True
    rendered = view.render(0.1)
    assert rendered is not None


def test_clean_grid_still_renders_grid():
    data = ChordData()
    data.set_base_chords(
        [{"timestamp": float(i), "chord": f"C{i}"} for i in range(64)],
        beat_times=[float(i) for i in range(64)],
    )
    data.bpm = 120
    data.meter_signature = 4
    data.set_beat_numbers([(i % 4) + 1 for i in range(64)])

    view = PlaybackView(data, metric_chords=True)
    rendered = view.render(0.1)
    assert rendered["output"]
    assert "C0" in rendered["output"]


def test_format_classification_stable():
    classification = {"classification": "stable", "beat_count": 64, "cv": 0.01,
                       "mad_ratio": 0.005, "deviant_fraction": 0.02,
                       "cycle_pass_fraction": 1.0, "suppressed_count": 3}
    diag = format_classification_diagnostic(classification)
    assert "stable" in diag
    assert "suppressed=3" in diag


def test_format_classification_flexible():
    classification = {"classification": "flexible", "reason": "CV 0.1000 > 0.06"}
    diag = format_classification_diagnostic(classification)
    assert "flexible" in diag
    assert "CV" in diag


def test_format_classification_no_dict():
    diag = format_classification_diagnostic(None)
    assert "no classification available" in diag


def test_cli_help_mentions_metric_chords():
    result = subprocess.run(
        [sys.executable, "-m", "chordflask", "--help"],
        capture_output=True, text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0
    assert "--metric-chords" in result.stdout
    assert "--no-metric-chords" in result.stdout
    assert "default for the web UI" in " ".join(result.stdout.split())


def test_cli_enables_metric_chords_by_default_with_explicit_opt_out():
    assert _parse_cli_args([]).metric_chords is True
    assert _parse_cli_args(["--metric-chords"]).metric_chords is True
    assert _parse_cli_args(["--no-metric-chords"]).metric_chords is False


def test_worker_keeps_metric_chords_disabled_by_default():
    assert _parse_cli_args(["--worker"]).metric_chords is False


def test_cli_rejects_worker_with_metric_chords():
    result = subprocess.run(
        [sys.executable, "-m", "chordflask", "--worker", "--metric-chords"],
        capture_output=True, text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode != 0
    assert "metric-chords" in result.stderr.lower()


def test_diagnostic_command_readonly(tmp_path):
    chord_data = ChordData()
    chord_data.set_base_chords(
        [{"timestamp": float(i), "chord": "C"} for i in range(64)],
        beat_times=[float(i) for i in range(64)],
    )
    chord_data.bpm = 120
    chord_data.meter_signature = 4
    chord_data.set_beat_numbers([(i % 4) + 1 for i in range(64)])

    json_path = tmp_path / "test.json"
    chord_data.save_to_file(str(json_path))
    original_bytes = json_path.read_bytes()

    script = SCRIPTS_DIR / "metric_chords_diff.py"
    result = subprocess.run(
        [sys.executable, str(script), str(json_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0

    final_bytes = json_path.read_bytes()
    assert final_bytes == original_bytes


def test_diagnostic_command_with_glitch(tmp_path):
    data = ChordData()
    n = 64
    entries = [{"timestamp": float(i), "chord": "C"} for i in range(n)]
    entries[10] = {"timestamp": 9.45, "chord": "Ab"}
    entries[11] = {"timestamp": 9.80, "chord": "C"}
    data.set_base_chords(entries, beat_times=[float(i) for i in range(64)])
    data.bpm = 120
    data.meter_signature = 4
    data.set_beat_numbers([(i % 4) + 1 for i in range(64)])

    json_path = tmp_path / "test.json"
    data.save_to_file(str(json_path))

    script = SCRIPTS_DIR / "metric_chords_diff.py"
    result = subprocess.run(
        [sys.executable, str(script), str(json_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "status:        stable" in result.stdout
    assert "Beats with suppressed chord (1 total):" in result.stdout
    assert "beat    9" in result.stdout
    assert "Ab -> C" in result.stdout


def test_diagnostic_handles_missing_file(capfd):
    script = SCRIPTS_DIR / "metric_chords_diff.py"
    result = subprocess.run(
        [sys.executable, str(script), "/nonexistent/file.json"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "not a file" in result.stdout or "SKIP" in result.stdout


def test_flask_app_constructor_accepts_metric_chords():
    app = FlaskMP4App(metric_chords=False)
    assert app._FlaskMP4App__metric_chords is False

    app2 = FlaskMP4App(metric_chords=True)
    assert app2._FlaskMP4App__metric_chords is True


def test_player_passes_metric_chords_to_view():
    from chordflask.mp4playerflask import MP4PlayerFlask

    data = ChordData()
    data.set_base_chords(
        [{"timestamp": float(i), "chord": "C"} for i in range(64)],
        beat_times=[float(i) for i in range(64)],
    )
    data.bpm = 120
    data.meter_signature = 4
    data.set_beat_numbers([(i % 4) + 1 for i in range(64)])

    class FakeFileRepr:
        def get(self, key=None):
            return "dummy"

    player = MP4PlayerFlask(FakeFileRepr(), metric_chords=True)
    assert player.playback_view._PlaybackView__metric_chords is True


def test_filter_fail_closed_malformed_chord_times():
    data = ChordData()
    entries = [{"timestamp": float(i), "chord": "C"} for i in range(32)]
    data.set_base_chords(entries, beat_times=[i * 0.5 for i in range(64)])
    data.bpm = 120
    data.meter_signature = 4
    data.set_beat_numbers([(i % 4) + 1 for i in range(64)])

    beat_chords = data.get_chords_per_beat()
    chord_times = list(data.chord_times)
    chord_times[3] = float("nan")

    filtered, classification = filter_metric_chords(
        beat_chords,
        data.beat_times,
        data.beat_numbers,
        data.beat_chord_indexes,
        data.meter_signature,
        chord_times,
    )
    assert classification["classification"] == "flexible"
    assert "raw_chord_times[3]" in classification["reason"]
    assert filtered == beat_chords


def test_filter_fail_closed_bool_in_beat_chord_indexes():
    data = ChordData()
    entries = [{"timestamp": float(i), "chord": "C"} for i in range(32)]
    data.set_base_chords(entries, beat_times=[i * 0.5 for i in range(64)])
    data.bpm = 120
    data.meter_signature = 4
    data.set_beat_numbers([(i % 4) + 1 for i in range(64)])

    beat_chords = data.get_chords_per_beat()
    indexes = list(data.beat_chord_indexes)
    indexes[20] = True

    filtered, classification = filter_metric_chords(
        beat_chords,
        data.beat_times,
        data.beat_numbers,
        indexes,
        data.meter_signature,
        data.chord_times,
    )
    assert classification["classification"] == "flexible"
    assert "beat_chord_indexes[20]" in classification["reason"]
    assert filtered == beat_chords


def test_filter_fail_closed_out_of_range_beat_chord_index():
    data = ChordData()
    entries = [{"timestamp": float(i), "chord": "C"} for i in range(32)]
    data.set_base_chords(entries, beat_times=[i * 0.5 for i in range(64)])
    data.bpm = 120
    data.meter_signature = 4
    data.set_beat_numbers([(i % 4) + 1 for i in range(64)])

    beat_chords = data.get_chords_per_beat()
    indexes = list(data.beat_chord_indexes)
    indexes[20] = len(data.chord_times)

    filtered, classification = filter_metric_chords(
        beat_chords,
        data.beat_times,
        data.beat_numbers,
        indexes,
        data.meter_signature,
        data.chord_times,
    )
    assert classification["classification"] == "flexible"
    assert "beat_chord_indexes[20]" in classification["reason"]
    assert filtered == beat_chords


def test_filter_fail_closed_not_list_inputs():
    filtered, classification = filter_metric_chords(
        None, [], [], [], 4, [],
    )
    assert classification["classification"] == "flexible"
    assert filtered == []

    filtered2, classification2 = filter_metric_chords(
        [], None, [], [], 4, [],
    )
    assert classification2["classification"] == "flexible"
    assert filtered2 == []


def test_classifier_fail_closed_not_list_beat_times():
    classification = classify_beat_grid(None, [], 4)
    assert classification["classification"] == "flexible"
    assert classification["reason"] == "beat_times is not a list"


def test_filter_fail_closed_length_mismatch():
    times, numbers = _make_clean_grid(64)
    beat_chords = [(timestamp, "C") for timestamp in times]

    filtered, classification = filter_metric_chords(
        beat_chords,
        times,
        numbers,
        [0] * 63,
        4,
        [0.0],
    )

    assert filtered == beat_chords
    assert classification["classification"] == "flexible"
    assert classification["reason"] == "beat_chord_indexes and beat_times length mismatch"
