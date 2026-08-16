import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
FLASK_DIR = REPO_ROOT / "flask"

if str(FLASK_DIR) not in sys.path:
    sys.path.insert(0, str(FLASK_DIR))

from chordflask_maintain.storage import (  # noqa: E402
    PROTECTED,
    RECLAIMABLE,
    REVIEW,
    format_storage_report,
    inspect_storage,
)


def _write(path, size=10):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def test_missing_media_directory_raises(tmp_path):
    with pytest.raises(ValueError):
        inspect_storage(tmp_path / "does-not-exist")


def test_media_file_raises(tmp_path):
    media = _write(tmp_path / "song.mp3")
    with pytest.raises(ValueError):
        inspect_storage(media)


def test_no_chordflask_directory(tmp_path):
    media = tmp_path / "album"
    media.mkdir()
    inspection = inspect_storage(media)
    assert inspection.exists is False
    assert inspection.categories == []


def test_empty_chordflask_directory(tmp_path):
    media = tmp_path / "album"
    (media / ".chordflask").mkdir(parents=True)
    inspection = inspect_storage(media)
    assert inspection.exists is True
    assert inspection.categories == []


def test_classification_and_bytes(tmp_path):
    media = tmp_path / "album"
    store = media / ".chordflask"
    _write(media / "song.mp4", 5)  # video source: verifies the song.mp3 cache
    _write(store / "song.json", 40)
    _write(store / "song.mp3", 100)
    _write(store / "song.xml", 30)
    _write(store / "song.mid", 20)
    _write(store / "song-chords-edited.md", 12)
    _write(store / "song-chords-edited.pdf", 13)
    _write(store / "song.song", 5)
    _write(store / "song.corrupt-20260101T000000Z-abcdef12.json", 60)

    inspection = inspect_storage(media)
    by_name = {c.name: c for c in inspection.categories}

    assert by_name["analysis JSON"].status == PROTECTED
    assert by_name["analysis JSON"].count == 1
    assert by_name["analysis JSON"].bytes == 40

    assert by_name["cached audio"].status == RECLAIMABLE
    assert by_name["cached audio"].bytes == 100

    assert by_name["MusicXML"].status == RECLAIMABLE
    assert by_name["MIDI"].status == RECLAIMABLE
    assert by_name["leadsheet exports"].status == RECLAIMABLE
    assert by_name["leadsheet exports"].count == 2

    assert by_name["song metadata"].status == REVIEW
    assert by_name["corrupt backups"].status == REVIEW
    assert by_name["corrupt backups"].bytes == 60


def test_mp3_without_video_source_is_unverified(tmp_path):
    media = tmp_path / "album"
    store = media / ".chordflask"
    _write(store / "song.mp3", 100)  # no matching video source

    inspection = inspect_storage(media)
    by_name = {c.name: c for c in inspection.categories}

    assert "cached audio" not in by_name
    assert by_name["unverified audio"].status == REVIEW
    assert by_name["unverified audio"].bytes == 100


def test_orphan_temp_dir_size_and_classification(tmp_path):
    media = tmp_path / "album"
    store = media / ".chordflask"
    temp = store / ".song.analyze-abc123"
    _write(temp / "song.json", 50)
    _write(temp / "song.mp3", 200)

    inspection = inspect_storage(media)
    by_name = {c.name: c for c in inspection.categories}
    assert by_name["orphan temp dirs"].status == REVIEW
    assert by_name["orphan temp dirs"].count == 2
    assert by_name["orphan temp dirs"].bytes == 250


def test_convert_temp_file_classified_as_temporary(tmp_path):
    media = tmp_path / "album"
    _write(media / ".chordflask" / ".song.convert-abc123.mp3", 50)

    inspection = inspect_storage(media)
    by_name = {c.name: c for c in inspection.categories}
    assert by_name["temporary files"].status == REVIEW
    assert by_name["temporary files"].count == 1
    assert by_name["temporary files"].bytes == 50


def test_analysis_json_with_convert_stem_classified_as_analysis(tmp_path):
    media = tmp_path / "album"
    _write(media / ".chordflask" / "song.convert-demo.json", 40)

    inspection = inspect_storage(media)
    by_name = {c.name: c for c in inspection.categories}
    assert "temporary files" not in by_name
    assert by_name["analysis JSON"].status == PROTECTED
    assert by_name["analysis JSON"].bytes == 40


def test_chordy_is_not_inspected(tmp_path):
    media = tmp_path / "album"
    media.mkdir()
    legacy = media / ".chordy"
    _write(legacy / "song.json", 500)

    inspection = inspect_storage(media)
    assert inspection.exists is False
    assert inspection.categories == []


def test_symlink_chordflask_is_skipped(tmp_path):
    media = tmp_path / "album"
    media.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (media / ".chordflask").symlink_to(outside)

    inspection = inspect_storage(media)
    assert inspection.exists is False
    assert any("skipped" in note.lower() for note in inspection.notes)


def test_symlinks_inside_chordflask_not_followed(tmp_path):
    media = tmp_path / "album"
    store = media / ".chordflask"
    store.mkdir(parents=True)
    _write(store / "song.json", 40)
    outside_file = _write(tmp_path / "big.bin", 1000)
    (store / "escape.mp3").symlink_to(outside_file)

    inspection = inspect_storage(media)
    by_name = {c.name: c for c in inspection.categories}
    assert "cached audio" not in by_name
    assert any("escape.mp3" in note for note in inspection.notes)


def test_report_changes_nothing(tmp_path):
    media = tmp_path / "album"
    store = media / ".chordflask"
    json_file = _write(store / "song.json", 40)
    _write(store / "song.mp3", 100)

    before = {p: p.read_bytes() for p in store.rglob("*") if p.is_file()}
    before_mtimes = {p: p.stat().st_mtime_ns for p in store.rglob("*") if p.is_file()}

    inspection = inspect_storage(media)
    format_storage_report(inspection)

    after = {p: p.read_bytes() for p in store.rglob("*") if p.is_file()}
    after_mtimes = {p: p.stat().st_mtime_ns for p in store.rglob("*") if p.is_file()}

    assert before == after
    assert before_mtimes == after_mtimes
    assert json_file.read_bytes() == b"x" * 40


def test_independent_directories_not_cross_inspected(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    _write(a / ".chordflask" / "song.json", 40)
    _write(b / ".chordflask" / "song.json", 90)

    inspection_a = inspect_storage(a)
    inspection_b = inspect_storage(b)

    assert str(inspection_a.chordflask_path) == str(a / ".chordflask")
    assert str(inspection_b.chordflask_path) == str(b / ".chordflask")
    assert {c.name: c.bytes for c in inspection_a.categories} == {
        "analysis JSON": 40
    }
    assert {c.name: c.bytes for c in inspection_b.categories} == {
        "analysis JSON": 90
    }


def test_nested_chordflask_not_traversed(tmp_path):
    media = tmp_path / "album"
    store = media / ".chordflask"
    _write(store / "song.json", 40)
    # A nested .chordflask inside the storage dir must not be treated separately.
    nested = store / "nested"
    _write(nested / "other.json", 70)

    inspection = inspect_storage(media)
    by_name = {c.name: c for c in inspection.categories}
    # "other" directory holds the nested file as an unclassified directory.
    assert by_name["analysis JSON"].bytes == 40
    assert "other directories" in by_name


def test_formatted_report_mentions_status(tmp_path):
    media = tmp_path / "album"
    _write(media / ".chordflask" / "song.json", 40)

    text = format_storage_report(inspect_storage(media))
    assert ".chordflask" in text
    assert "analysis JSON" in text
    assert PROTECTED in text


def test_formatted_report_no_storage(tmp_path):
    media = tmp_path / "album"
    media.mkdir()
    text = format_storage_report(inspect_storage(media))
    assert "no analysis storage" in text
