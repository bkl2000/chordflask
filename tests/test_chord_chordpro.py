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
