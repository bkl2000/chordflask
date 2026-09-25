from pathlib import Path

import pytest

from chordflask.chordpro_song import (
    ChordProSongError,
    MAX_SONG_BYTES,
    MAX_SONG_LINE_BYTES,
    parse_chordpro,
    read_chordpro,
)


def test_parses_metadata_sections_chords_lyrics_and_unicode():
    parsed = parse_chordpro(
        "{title: Test Song}\n"
        "{artist: Test Artist}\n"
        "{subtitle: Synthetic example}\n"
        "{key: B♭}\n"
        "{capo: 2}\n"
        "{sov}\n"
        "Before [C]Hello [G♯]wörld\n"
        "{eov}\n"
        "{soc: Refrain}\n"
        "[Am]Again\n"
        "{eoc}\n"
    )

    assert parsed["metadata"] == {
        "title": "Test Song",
        "artist": "Test Artist",
        "subtitle": "Synthetic example",
        "key": "B♭",
        "capo": "2",
    }
    assert parsed["blocks"] == [
        {"type": "section_start", "section": "verse", "heading": "Verse"},
        {"type": "line", "runs": [
            {"chord": None, "lyric": "Before "},
            {"chord": "C", "lyric": "Hello "},
            {"chord": "G♯", "lyric": "wörld"},
        ]},
        {"type": "section_end", "section": "verse"},
        {"type": "section_start", "section": "chorus", "heading": "Refrain"},
        {"type": "line", "runs": [{"chord": "Am", "lyric": "Again"}]},
        {"type": "section_end", "section": "chorus"},
    ]


def test_comments_blank_lines_escapes_and_unsupported_directives_are_safe():
    parsed = parse_chordpro(
        "{comment: <script>alert(1)</script>}\n"
        "{ci: italic note}\n"
        "{cb: boxed note}\n"
        "{tempo: 120}\n"
        "{start_of_tab}\n"
        "literal <img src=x onerror=alert(1)>\n"
        "{end_of_tab}\n"
        "\n"
        r"\[C\] literal \{text\} and \\" + "\n"
    )

    assert parsed["blocks"] == [
        {"type": "comment", "style": "normal", "text": "<script>alert(1)</script>"},
        {"type": "comment", "style": "italic", "text": "italic note"},
        {"type": "comment", "style": "box", "text": "boxed note"},
        {"type": "line", "runs": [{
            "chord": None,
            "lyric": "literal <img src=x onerror=alert(1)>",
        }]},
        {"type": "blank"},
        {"type": "line", "runs": [{
            "chord": None,
            "lyric": "[C] literal {text} and \\",
        }]},
    ]


@pytest.mark.parametrize("line", [
    "[C missing",
    "empty [] marker",
    "stray ] bracket",
    "{title}",
    "{title: missing close",
    "{title: extra close}}",
    "{not valid!: value}",
    "{eob}",
    "{sov}\n{eoc}",
])
def test_malformed_input_falls_back_to_literal_lines(line):
    parsed = parse_chordpro(line)

    assert parsed["blocks"][-1] == {
        "type": "line",
        "runs": [{"chord": None, "lyric": line.splitlines()[-1]}],
    }


def test_chordflask_beat_directives_are_hidden_sync_metadata():
    parsed = parse_chordpro(
        "{x_chordflask_beats: 12,15}\n"
        "{x_chordflask_end: 20}\n"
        "[C]Hello [G]wörld"
    )

    assert parsed["blocks"] == [
        {"type": "line", "runs": [
            {"chord": "C", "lyric": "Hello ", "start_beat": 12, "end_beat": 15},
            {"chord": "G", "lyric": "wörld", "start_beat": 15, "end_beat": 20},
        ]},
    ]


def test_romanization_attaches_to_same_synced_logical_line():
    parsed = parse_chordpro(
        "{x_chordflask_romanized: chan rak thoe}\n"
        "{x_chordflask_beats: 12,15}\n"
        "{x_chordflask_end: 20}\n"
        "[C]ฉันรัก [G]เธอ"
    )

    assert parsed["blocks"] == [{
        "type": "line",
        "romanized": "chan rak thoe",
        "runs": [
            {"chord": "C", "lyric": "ฉันรัก ", "start_beat": 12, "end_beat": 15},
            {"chord": "G", "lyric": "เธอ", "start_beat": 15, "end_beat": 20},
        ],
    }]


def test_romanization_does_not_leak_and_empty_metadata_is_ignored():
    parsed = parse_chordpro(
        "{x_chordflask_romanized: nueng}\nหนึ่ง\n"
        "สอง\n{x_chordflask_romanized: }\nสาม"
    )

    assert parsed["blocks"][0]["romanized"] == "nueng"
    assert "romanized" not in parsed["blocks"][1]
    assert "romanized" not in parsed["blocks"][2]


def test_unknown_directive_clears_pending_romanization_consistently():
    parsed = parse_chordpro(
        "{x_chordflask_romanized: nueng}\n{unknown: value}\nหนึ่ง"
    )

    assert "romanized" not in parsed["blocks"][0]


def test_chord_track_provenance_is_metadata_not_visible_text():
    parsed = parse_chordpro("{x_chordflask_track: btc}\n\n[C]Hello")

    assert parsed["metadata"]["x_chordflask_track"] == "btc"
    assert parsed["blocks"][-1] == {
        "type": "line",
        "runs": [{"chord": "C", "lyric": "Hello"}],
    }


def test_suppressed_repeated_beats_stay_in_one_marker_range():
    parsed = parse_chordpro(
        "{x_chordflask_beats: 20,24,27}\n"
        "{x_chordflask_end: 29}\n"
        "[C]first [D]second [C]third"
    )
    markers = [run for run in parsed["blocks"][0]["runs"] if run["chord"]]

    assert [
        (run["chord"], run["start_beat"], run["end_beat"])
        for run in markers
    ] == [("C", 20, 24), ("D", 24, 27), ("C", 27, 29)]
    first_c, d, later_c = markers
    assert all(
        first_c["start_beat"] <= beat < first_c["end_beat"]
        for beat in range(20, 24)
    )
    assert not first_c["start_beat"] <= 24 < first_c["end_beat"]
    assert d["start_beat"] <= 24 < d["end_beat"]
    assert later_c["start_beat"] <= 27 < later_c["end_beat"]


def test_sync_metadata_is_invisible_and_legacy_markers_are_unchanged():
    legacy = parse_chordpro("[C]Hello [G]wörld\n[C@17]Odd")
    first = legacy["blocks"][0]

    assert all("start_beat" not in run and "end_beat" not in run for run in first["runs"])
    assert first["runs"][0] == {"chord": "C", "lyric": "Hello "}
    assert first["runs"][1] == {"chord": "G", "lyric": "wörld"}
    # A bracket is no longer split: an odd "@" stays ordinary chord text.
    assert legacy["blocks"][1]["runs"][0]["chord"] == "C@17"
    visible = "".join(
        run["lyric"] for block in legacy["blocks"]
        if block["type"] == "line" for run in block["runs"]
    )
    assert "x_chordflask" not in visible
    assert "Hello " in visible


@pytest.mark.parametrize("metadata", [
    # more beat entries than chord markers
    "{x_chordflask_beats: 12,15,18}\n{x_chordflask_end: 20}\n[C]Hello [G]wörld",
    # fewer beat entries than chord markers
    "{x_chordflask_beats: 12}\n{x_chordflask_end: 20}\n[C]Hello [G]wörld",
    # missing end directive
    "{x_chordflask_beats: 12,15}\n[C]Hello [G]wörld",
    # non-increasing beat positions
    "{x_chordflask_beats: 15,12}\n{x_chordflask_end: 20}\n[C]Hello [G]wörld",
    # end not beyond the last marker
    "{x_chordflask_beats: 12,15}\n{x_chordflask_end: 15}\n[C]Hello [G]wörld",
])
def test_invalid_sync_metadata_fails_safe_to_static_rendering(metadata):
    parsed = parse_chordpro(metadata)
    block = parsed["blocks"][-1]

    assert block["type"] == "line"
    assert all("start_beat" not in run and "end_beat" not in run for run in block["runs"])
    # The line still renders normally as ordinary ChordPro.
    assert block["runs"][-1]["chord"] == "G"
    assert block["runs"][-1]["lyric"] == "wörld"


def test_sync_metadata_does_not_leak_across_a_blank_line():
    parsed = parse_chordpro(
        "{x_chordflask_beats: 12,15}\n"
        "{x_chordflask_end: 20}\n"
        "\n"
        "[C]Hello [G]wörld"
    )
    block = parsed["blocks"][-1]

    assert all("start_beat" not in run and "end_beat" not in run for run in block["runs"])


def test_read_chordpro_rejects_empty_invalid_utf8_and_bounds(tmp_path):
    sidecar = tmp_path / "song.cho"

    sidecar.write_bytes(b"")
    with pytest.raises(ChordProSongError, match="empty"):
        read_chordpro(sidecar)

    sidecar.write_bytes(b"\xff")
    with pytest.raises(ChordProSongError, match="UTF-8"):
        read_chordpro(sidecar)

    sidecar.write_bytes(b"x" * (MAX_SONG_BYTES + 1))
    with pytest.raises(ChordProSongError, match="too large"):
        read_chordpro(sidecar)

    sidecar.write_bytes(b"x" * (MAX_SONG_LINE_BYTES + 1) + b"\n")
    with pytest.raises(ChordProSongError, match="oversized line"):
        read_chordpro(sidecar)


def test_read_chordpro_wraps_read_errors(tmp_path, monkeypatch):
    sidecar = tmp_path / "song.cho"
    sidecar.write_text("Synthetic", encoding="utf-8")

    def fail_open(self, *args, **kwargs):
        raise PermissionError("private filesystem detail")

    monkeypatch.setattr(Path, "open", fail_open)

    with pytest.raises(ChordProSongError, match="could not be read") as error:
        read_chordpro(sidecar)
    assert "private filesystem detail" not in str(error.value)
