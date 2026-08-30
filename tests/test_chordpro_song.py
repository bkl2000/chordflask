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
