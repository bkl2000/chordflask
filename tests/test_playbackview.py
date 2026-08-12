import inspect
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FLASK_DIR = REPO_ROOT / "flask"

if str(FLASK_DIR) not in sys.path:
    sys.path.insert(0, str(FLASK_DIR))

from chorddata import ChordData
from playbackview import PlaybackView
from mp4playerflask import MP4PlayerFlask


def test_player_has_no_fixed_playback_anticipation():
    default = inspect.signature(MP4PlayerFlask).parameters["display_chord_offset"].default
    assert default == 0.0


def test_render_returns_grid_payload_for_current_position():
    data = ChordData()
    data.set_base_chords([
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 1.0, "chord": "G"},
        {"timestamp": 2.0, "chord": "F"},
    ], beat_times=[0.0, 1.0, 2.0, 3.0])
    data.bpm = 120

    view = PlaybackView(data, display_chord_offset=0)
    rendered = view.render(1.1)

    assert rendered["index"] == 1
    assert rendered["bpm"] == 120
    assert "[  G  ]" in rendered["output"]


def test_default_view_changes_on_the_detected_beat_without_fixed_anticipation():
    data = ChordData()
    data.set_base_chords(
        [
            {"timestamp": 0.0, "chord": "C"},
            {"timestamp": 1.0, "chord": "G"},
        ],
        beat_times=[0.0, 1.0, 2.0],
    )

    view = PlaybackView(data)

    assert view.render(0.99)["index"] == 0
    assert view.render(1.0)["index"] == 1


def test_chord_transition_is_assigned_to_nearest_beat_without_moving_marker():
    data = ChordData()
    data.set_base_chords(
        [
            {"timestamp": 0.0, "chord": "C"},
            {"timestamp": 1.08, "chord": "G"},
        ],
        beat_times=[0.0, 1.0, 2.0],
    )

    assert data.get_chords_per_beat() == [
        (0.0, "C"),
        (1.0, "G"),
        (2.0, "G"),
    ]
    assert PlaybackView(data).render(0.99)["index"] == 0
    assert PlaybackView(data).render(1.0)["index"] == 1


def test_grid_rows_start_on_qm_downbeats_instead_of_file_index_zero():
    data = ChordData()
    chords = [
        {"timestamp": float(i), "chord": f"C{i}"}
        for i in range(13)
    ]
    data.set_base_chords(chords, beat_times=[float(i) for i in range(13)])
    data.set_beat_numbers([4, 1, 2, 3, 4, 1, 2, 3, 4, 1, 2, 3, 4])
    data.meter_signature = 4

    rendered = PlaybackView(data).render(9.1)
    active_line = rendered["output"].splitlines()[2]

    assert "C9" in active_line
    assert "C1" in active_line
    assert "C0" not in active_line


def test_grid_keeps_current_chord_on_second_row_with_eight_columns():
    data = ChordData()
    chords = [
        {"timestamp": float(i), "chord": f"C{i}"}
        for i in range(24)
    ]
    data.set_base_chords(chords, beat_times=[float(i) for i in range(24)])

    view = PlaybackView(data, display_chord_offset=0)
    rendered = view.render(0.1)

    lines = rendered["output"].splitlines()
    assert "[ C0  ]" not in lines[1]
    assert "[ C0  ]" in lines[2]
    assert all(f"C{i}" in lines[2] for i in range(8))
    assert "C8" not in lines[2]


def test_grid_can_show_repeated_chords_as_underscores():
    data = ChordData()
    data.set_base_chords([
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 4.0, "chord": "F"},
        {"timestamp": 6.0, "chord": "G"},
    ], beat_times=[float(i) for i in range(8)])

    view = PlaybackView(data, display_chord_offset=0, repeat_mode="changes")
    rendered = view.render(0.1)

    lines = rendered["output"].splitlines()
    assert "[  C  ]" in lines[2]
    assert "  F" in lines[2]
    assert "  G" in lines[2]
    assert lines[2].count("_") == 5


def _grid_cells(output, row):
    line = output.splitlines()[row + 1]
    return [line[index:index + 7] for index in range(0, len(line), 7)]


def test_changes_mode_repeats_held_chord_at_each_two_measure_row():
    data = ChordData()
    data.set_base_chords(
        [{"timestamp": 0.0, "chord": "C"}],
        beat_times=[float(index) for index in range(24)],
    )
    data.meter_signature = 4

    output = PlaybackView(data, repeat_mode="changes").render(0.1)["output"]

    assert _grid_cells(output, 1) == ["[  C  ]"] + ["   _   "] * 7
    assert _grid_cells(output, 2) == ["   C   "] + ["   _   "] * 7
    assert _grid_cells(output, 3) == ["   C   "] + ["   _   "] * 7


def test_changes_mode_keeps_real_change_and_active_marker():
    data = ChordData()
    data.set_base_chords(
        [
            {"timestamp": 0.0, "chord": "C"},
            {"timestamp": 5.0, "chord": "G"},
        ],
        beat_times=[float(index) for index in range(16)],
    )
    data.meter_signature = 4

    output = PlaybackView(data, repeat_mode="changes").render(5.1)["output"]

    assert _grid_cells(output, 1) == [
        "   C   ", "   _   ", "   _   ", "   _   ",
        "   _   ", "[  G  ]", "   _   ", "   _   ",
    ]


def test_chords_mode_still_shows_held_chord_on_every_beat():
    data = ChordData()
    data.set_base_chords(
        [{"timestamp": 0.0, "chord": "C"}],
        beat_times=[float(index) for index in range(16)],
    )
    data.meter_signature = 4

    output = PlaybackView(data, repeat_mode="chords").render(0.1)["output"]

    assert _grid_cells(output, 1) == ["[  C  ]"] + ["   C   "] * 7


def test_three_four_grid_keeps_two_measures_per_row():
    data = ChordData()
    data.set_base_chords(
        [
            {"timestamp": float(index), "chord": f"C{index}"}
            for index in range(12)
        ],
        beat_times=[float(index) for index in range(12)],
    )
    data.meter_signature = 3
    data.set_beat_numbers([1, 2, 3] * 4)

    output = PlaybackView(data, repeat_mode="chords").render(0.1)["output"]

    assert len(_grid_cells(output, 1)) == 6
    assert "C0" in _grid_cells(output, 1)[0]
    assert "C5" in _grid_cells(output, 1)[5]


def test_browser_grid_has_16_rows_and_blank_song_boundaries():
    data = ChordData()
    data.set_base_chords(
        [{"timestamp": 0.0, "chord": "C"}],
        beat_times=[float(index) for index in range(4)],
    )
    data.meter_signature = 4

    output = PlaybackView(data, repeat_mode="changes").render(0.1)["output"]
    grid_lines = output.splitlines()[1:]

    assert len(grid_lines) == 16
    assert grid_lines[0].strip() == ""
    assert grid_lines[2].strip() == ""
