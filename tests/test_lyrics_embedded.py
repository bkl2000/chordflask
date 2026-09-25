import json
from types import SimpleNamespace

from chordflask_lyrics import embedded
from chordflask_lyrics.lrclib import TimedLyricLine


def probe_result(tags):
    return SimpleNamespace(returncode=0, stdout=json.dumps({"format": {"tags": tags}}))


def test_mp3_uslt_exposed_by_ffprobe_is_read_as_plain_lyrics(monkeypatch, tmp_path):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"media")
    monkeypatch.setattr(
        embedded.subprocess,
        "run",
        lambda *args, **kwargs: probe_result({"lyrics": "First line\nSecond line"}),
    )

    result = embedded.get_embedded_lyrics(media)

    assert result == embedded.EmbeddedLyrics(
        "ffprobe:lyrics", "First line\nSecond line"
    )
    assert result.synchronized is False


def test_embedded_lrc_timestamps_are_preserved(monkeypatch, tmp_path):
    monkeypatch.setattr(
        embedded.subprocess,
        "run",
        lambda *args, **kwargs: probe_result(
            {"lyrics": "[00:01.25]First line\n[00:05.00]Second line"}
        ),
    )

    result = embedded.get_embedded_lyrics(tmp_path / "song.mp3")

    assert result.synchronized is True
    assert result.lines == (
        TimedLyricLine(1.25, "First line"),
        TimedLyricLine(5.0, "Second line"),
    )


def test_empty_or_corrupt_embedded_lyrics_are_ignored(monkeypatch, tmp_path):
    results = iter(
        [
            probe_result({"lyrics": " \n\t "}),
            probe_result({"lyrics": "broken\x00text"}),
        ]
    )
    monkeypatch.setattr(embedded.subprocess, "run", lambda *args, **kwargs: next(results))

    assert embedded.get_embedded_lyrics(tmp_path / "empty.mp3") is None
    assert embedded.get_embedded_lyrics(tmp_path / "broken.mp3") is None
