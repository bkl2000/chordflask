import pytest

from chordflask.chord_chordpro import format_chordpro


def test_format_chordpro_basic_four_four_changes_grid_and_metadata():
    chordpro = format_chordpro(
        title="Song Name",
        bpm=106,
        meter=4,
        beats=["Bb"] * 4 + ["Gm"] * 4,
        beat_numbers=[1, 2, 3, 4] * 2,
        repeat_mode="changes",
    )

    assert chordpro == (
        "{title: Song Name}\n"
        "{tempo: 106}\n"
        "{time: 4/4}\n"
        "\n"
        "{start_of_grid}\n"
        "| Bb . . . | Gm . . . |\n"
        "{end_of_grid}\n"
    )


def test_format_chordpro_chords_mode_writes_every_beat():
    chordpro = format_chordpro(
        title="Song",
        meter=4,
        beats=["Bb"] * 4 + ["Gm"] * 4,
        beat_numbers=[1, 2, 3, 4] * 2,
        repeat_mode="chords",
    )

    assert "| Bb Bb Bb Bb | Gm Gm Gm Gm |" in chordpro
    assert "." not in chordpro


def test_format_chordpro_omits_unusable_bpm_and_meter():
    chordpro = format_chordpro(
        title="Song",
        bpm=None,
        meter=None,
        beats=["C", "C"],
    )

    assert "{tempo:" not in chordpro
    assert "{time:" not in chordpro
    assert "| C . |" in chordpro


def test_format_chordpro_rejects_unknown_repeat_mode():
    with pytest.raises(ValueError, match="repeat_mode"):
        format_chordpro(title="Song", beats=["C"], repeat_mode="invalid")


def test_lyrics_export_retains_provenance_but_grid_export_does_not():
    from chordflask.chord_chordpro import format_export_chordpro
    from chordflask.chord_export_sheet import build_export_sheet
    from chordflask.chordpro_song import parse_chordpro

    snapshot = {
        "beats": [(1, "C"), (2, "G")], "chord_track_label": "Chordino",
        "rhythm_track_label": "QM", "version": "original", "transpose": 0,
        "prefer_flats": False, "use_unicode": False, "bpm": 60, "meter": 4,
        "repeat_mode": "chords",
    }
    content = (
        "{x_chordflask_generator: ChordFlask Lyrics}\n"
        "{x_chordflask_version: 0.9.18}\n"
        "{x_chordflask_fingerprint: " + "a" * 64 + "}\n"
        "{x_chordflask_rhythm_fingerprint: " + "b" * 64 + "}\n"
        "{x_chordflask_beats: 0,1}\n{x_chordflask_end: 2}\n[C]Hi [G]there\n"
    )
    song = parse_chordpro(content)
    exported = parse_chordpro(format_export_chordpro(build_export_sheet("Song", snapshot, song)))
    assert all(exported["metadata"][name] == value for name, value in song["metadata"].items())
    grid = format_export_chordpro(build_export_sheet("Song", snapshot))
    assert grid == format_chordpro(
        title="Song", bpm=60, meter=4, beats=["C", "G"],
        beat_numbers=[1, 2], repeat_mode="chords",
    )
    assert "x_chordflask_" not in grid
