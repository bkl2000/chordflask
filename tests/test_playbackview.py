import inspect
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FLASK_DIR = REPO_ROOT / "flask"

if str(FLASK_DIR) not in sys.path:
    sys.path.insert(0, str(FLASK_DIR))

from chordflask_base import ChordData
from chordflask.filerepr import FileRepr
from chordflask.playbackview import PlaybackView
from chordflask.mp4playerflask import MP4PlayerFlask


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


def test_compact_grid_keeps_current_chord_on_third_row_with_eight_columns():
    data = ChordData()
    chords = [
        {"timestamp": float(i), "chord": f"C{i}"}
        for i in range(200)
    ]
    data.set_base_chords(chords, beat_times=[float(i) for i in range(200)])

    view = PlaybackView(data, display_chord_offset=0)
    rendered = view.render(17.1)

    lines = rendered["output"].splitlines()
    assert len(lines[1:]) == 13
    assert "C0" in lines[1]
    assert "C8" in lines[2]
    assert "[ C17" in lines[3]
    assert all(f"C{i}" in lines[3] for i in range(16, 24))
    assert "C24" not in lines[3]


def test_grid_can_show_repeated_chords_as_underscores():
    data = ChordData()
    data.set_base_chords([
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 4.0, "chord": "F"},
        {"timestamp": 6.0, "chord": "G"},
    ], beat_times=[float(i) for i in range(24)])

    view = PlaybackView(data, display_chord_offset=0, repeat_mode="changes")
    rendered = view.render(16.1)

    lines = rendered["output"].splitlines()
    assert "  F" in lines[1]
    assert "  G" in lines[1]
    assert "[  G  ]" in lines[3]
    assert lines[3].count("_") == 7


def _grid_cells(output, row):
    line = output.splitlines()[row]
    return [line[index:index + 7] for index in range(0, len(line), 7)]


def test_changes_mode_repeats_held_chord_at_each_two_measure_row():
    data = ChordData()
    data.set_base_chords(
        [{"timestamp": 0.0, "chord": "C"}],
        beat_times=[float(index) for index in range(24)],
    )
    data.meter_signature = 4

    output = PlaybackView(data, repeat_mode="changes").render(16.1)["output"]

    assert _grid_cells(output, 1) == ["   C   "] + ["   _   "] * 7
    assert _grid_cells(output, 2) == ["   C   "] + ["   _   "] * 7
    assert _grid_cells(output, 3) == ["[  C  ]"] + ["   _   "] * 7


def test_changes_mode_keeps_real_change_and_active_marker():
    data = ChordData()
    data.set_base_chords(
        [
            {"timestamp": 0.0, "chord": "C"},
            {"timestamp": 21.0, "chord": "G"},
        ],
        beat_times=[float(index) for index in range(32)],
    )
    data.meter_signature = 4

    output = PlaybackView(data, repeat_mode="changes").render(21.1)["output"]

    assert _grid_cells(output, 3) == [
        "   C   ", "   _   ", "   _   ", "   _   ",
        "   _   ", "[  G  ]", "   _   ", "   _   ",
    ]


def test_chords_mode_still_shows_held_chord_on_every_beat():
    data = ChordData()
    data.set_base_chords(
        [{"timestamp": 0.0, "chord": "C"}],
        beat_times=[float(index) for index in range(24)],
    )
    data.meter_signature = 4

    output = PlaybackView(data, repeat_mode="chords").render(16.1)["output"]

    assert _grid_cells(output, 3) == ["[  C  ]"] + ["   C   "] * 7


def test_three_four_grid_keeps_two_measures_per_row():
    data = ChordData()
    data.set_base_chords(
        [
            {"timestamp": float(index), "chord": f"C{index}"}
            for index in range(24)
        ],
        beat_times=[float(index) for index in range(24)],
    )
    data.meter_signature = 3
    data.set_beat_numbers([1, 2, 3] * 8)

    output = PlaybackView(data, repeat_mode="chords").render(12.1)["output"]

    assert len(_grid_cells(output, 3)) == 6
    assert "C12" in _grid_cells(output, 3)[0]
    assert "C17" in _grid_cells(output, 3)[5]


def test_desktop_grid_places_current_row_at_position_three():
    data = ChordData()
    data.set_base_chords(
        [{"timestamp": float(index), "chord": f"C{index}"} for index in range(400)],
        beat_times=[float(index) for index in range(400)],
    )
    data.meter_signature = 4
    data.set_beat_numbers([1, 2, 3, 4] * 100)

    output = PlaybackView(data, grid_mode="desktop").render(120.1)["output"]
    rows = output.splitlines()[1:]
    active_row = next(index for index, line in enumerate(rows, start=1) if "[" in line)

    assert active_row == 3
    assert len(rows) == 21
    assert "C104" in rows[0]
    assert "C120" in rows[2]
    assert "C128" in rows[3]


def test_compact_grid_clamps_song_start_without_blank_rows():
    data = ChordData()
    data.set_base_chords(
        [{"timestamp": 0.0, "chord": "C"}],
        beat_times=[float(index) for index in range(4)],
    )
    data.meter_signature = 4

    output = PlaybackView(data, repeat_mode="changes").render(0.1)["output"]
    grid_lines = output.splitlines()[1:]

    assert len(grid_lines) == 1
    assert "[  C  ]" in grid_lines[0]
    assert all(line.strip() for line in grid_lines)


def test_compact_grid_clamps_song_end_without_blank_rows():
    data = ChordData()
    data.set_base_chords(
        [{"timestamp": float(index), "chord": f"C{index}"} for index in range(20)],
        beat_times=[float(index) for index in range(20)],
    )
    data.meter_signature = 4

    output = PlaybackView(data).render(19.1)["output"]
    grid_lines = output.splitlines()[1:]

    assert len(grid_lines) == 3
    assert "C19" in grid_lines[-1]
    assert all(line.strip() for line in grid_lines)


def test_desktop_track_switch_keeps_grid_position_and_mode(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"not used")
    file_repr = FileRepr(str(media), datapath=str(tmp_path / ".chordflask"), create=True)
    data = ChordData()
    data.set_chord_track(
        "chordino",
        [{"timestamp": float(index), "chord": f"C{index}"} for index in range(200)],
    )
    data.set_chord_track(
        "btc",
        [{"timestamp": float(index), "chord": f"G{index}"} for index in range(200)],
    )
    data.set_rhythm_track(
        "qm_barbeattracker",
        bpm=120,
        meter_signature=4,
        beat_times=[float(index) for index in range(200)],
        beat_numbers=[1, 2, 3, 4] * 50,
    )
    data.save_to_file(file_repr.get("json"))

    player = MP4PlayerFlask(file_repr, grid_mode="desktop")
    before = player.playback_view.render(120.1)
    player.select_chord_track("btc")
    after = player.playback_view.render(120.1)

    assert player.grid_mode == "desktop"
    assert next(index for index, line in enumerate(before["output"].splitlines()[1:], 1) if "[" in line) == 3
    assert next(index for index, line in enumerate(after["output"].splitlines()[1:], 1) if "[" in line) == 3
    assert "G120" in after["output"]
