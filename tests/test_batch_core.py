from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]

from chordflask.helpers.batch_core import find_media_files


def test_find_media_files_returns_preferred_media_sorted_by_size(tmp_path):
    small = tmp_path / "b.webm"
    large = tmp_path / "a.mp4"
    audio = tmp_path / "c.mp3"
    duplicate_audio = tmp_path / "a.mp3"
    ignored = tmp_path / "notes.txt"
    small.write_bytes(b"1")
    large.write_bytes(b"12345")
    audio.write_bytes(b"123")
    duplicate_audio.write_bytes(b"2")
    ignored.write_text("ignored")

    files = find_media_files(tmp_path)

    assert files == [small, audio, large]


def test_find_media_files_prefers_mp4_over_same_stem(tmp_path):
    (tmp_path / "song.mp4").write_bytes(b"10")
    (tmp_path / "song.webm").write_bytes(b"9")
    (tmp_path / "song.mp3").write_bytes(b"8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "nested.mp4").write_bytes(b"7")

    names = [p.name for p in find_media_files(tmp_path)]

    assert names == ["song.mp4"]


def test_find_media_files_raises_for_missing_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        find_media_files(tmp_path / "missing")
