import argparse
from io import BytesIO
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
FLASK_DIR = REPO_ROOT / "flask"
HELPERS_DIR = FLASK_DIR / "helpers"

for path in (FLASK_DIR, HELPERS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from chordflask_base import ChordData  # noqa: E402
import chordleadsheet_batch  # noqa: E402
from chordleadsheet_batch import (  # noqa: E402
    LeadsheetExportError,
    build_argument_parser,
    export_file,
    run,
)
from chordflask import FlaskMP4App  # noqa: E402
from filerepr import FileRepr  # noqa: E402
from mp4playerflask import MP4PlayerFlask  # noqa: E402


@pytest.fixture(autouse=True)
def isolate_default_analysis_queue(monkeypatch, tmp_path):
    monkeypatch.setenv("CHORDFLASK_QUEUE_DIR", str(tmp_path / "default-queue"))


def _write_analysis(media, *, edited=False, extra_chord=None, extra_rhythm=None):
    file_repr_dir = media.parent / ".chordflask"
    file_repr_dir.mkdir(exist_ok=True)
    cd = ChordData()
    cd.set_chord_track(
        "chordino",
        [
            {"timestamp": 0.0, "chord": "C"},
            {"timestamp": 1.0, "chord": "G"},
        ],
    )
    if extra_chord:
        cd.set_chord_track(
            extra_chord,
            [
                {"timestamp": 0.0, "chord": "F"},
                {"timestamp": 1.0, "chord": "Am"},
            ],
        )
    cd.set_rhythm_track(
        "qm_barbeattracker",
        bpm=120,
        meter_signature=4,
        beat_times=[0.0, 0.5, 1.0, 1.5],
        beat_numbers=[1, 2, 3, 4],
    )
    if extra_rhythm:
        cd.set_rhythm_track(
            extra_rhythm,
            bpm=100,
            meter_signature=4,
            beat_times=[0.0, 0.6, 1.2, 1.8],
            beat_numbers=[1, 2, 3, 4],
        )
    if edited:
        cd.create_beat_aligned_track("user_edited", metadata={"display_name": "Edited"})
    cd.save_to_file(file_repr_dir / f"{media.stem}.json")
    return file_repr_dir


def _args(**overrides):
    defaults = vars(build_argument_parser().parse_args(["videos"]))
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_export_file_reuses_analysis_and_writes_leadsheet(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    analysis_dir = _write_analysis(media)

    result = export_file(media, _args())

    assert result == {
        "media": str(media),
        "ok": True,
        "analysis_action": "reused",
        "exported": True,
        "error": None,
    }
    leadsheet = analysis_dir / "song-chords-chordino.md"
    pdf = analysis_dir / "song-chords-chordino.pdf"
    assert leadsheet.is_file()
    assert pdf.read_bytes().startswith(b"%PDF")
    content = leadsheet.read_text()
    assert content.startswith("# song\n")
    assert "**120 BPM · 4/4 · Original · Flats · Transpose 0**" in content
    assert "Chordino · QM Bar/Beat Tracker" in content
    assert "```text\n" in content
    assert "C          -          G          -" in content


def test_browser_and_batch_exports_are_byte_identical(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    analysis_dir = _write_analysis(media)
    export_file(media, _args())

    file_repr = FileRepr(str(media), create=True)
    app_wrapper = FlaskMP4App()
    app_wrapper.file_repr = file_repr
    app_wrapper.player = MP4PlayerFlask(file_repr, metric_chords=True)
    app_wrapper.player.set_prefer_flats(True)
    app_wrapper.player.set_repeat_mode("changes")

    response = app_wrapper.app.test_client().post(
        "/download_chords",
        json={"dirname": str(tmp_path), "filename": media.name},
    )

    assert response.status_code == 200
    with ZipFile(BytesIO(response.data)) as archive:
        assert archive.read("song-chords-chordino.md") == (
            analysis_dir / "song-chords-chordino.md"
        ).read_bytes()
        assert archive.read("song-chords-chordino.pdf").startswith(b"%PDF")


def test_export_file_prefers_edited_for_auto(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    analysis_dir = _write_analysis(media, edited=True)

    result = export_file(media, _args(chord_track="auto"))

    assert result["exported"] is True
    leadsheet = analysis_dir / "song-chords-edited.md"
    content = leadsheet.read_text()
    assert "· Edited ·" in content
    assert "Edited · QM Bar/Beat Tracker" in content


def test_export_file_uses_named_chord_and_rhythm_tracks(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    analysis_dir = _write_analysis(media, extra_chord="pytorch", extra_rhythm="other")

    export_file(
        media,
        _args(chord_track="pytorch", rhythm_track="other", repeat_mode="chords"),
    )

    leadsheet = analysis_dir / "song-chords-pytorch.md"
    content = leadsheet.read_text()
    assert "**100 BPM · 4/4 · Original · Flats · Transpose 0**" in content
    assert "F          F          Am         Am" in content


def test_export_file_applies_transpose_sharps_unicode(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    analysis_dir = _write_analysis(media)

    export_file(media, _args(transpose=2, sharps=True, unicode=True))

    leadsheet = analysis_dir / "song-chords-chordino.md"
    content = leadsheet.read_text()
    assert "Transpose 2" in content
    assert "Sharps" in content
    assert "Unicode" in content
    assert "D          -          A          -" in content


def test_export_file_missing_analysis_is_created_serially(tmp_path, monkeypatch):
    media = tmp_path / "new.mp4"
    media.write_bytes(b"media")
    analyzed = []

    def fake_analyze(media_path):
        analyzed.append(media_path)
        _write_analysis(media)

    monkeypatch.setattr(chordleadsheet_batch, "_analyze_media", fake_analyze)

    result = export_file(media, _args())

    assert result["analysis_action"] == "created"
    assert result["exported"] is True
    assert analyzed == [media]


def test_export_file_unavailable_chord_track_fails(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    _write_analysis(media)

    with pytest.raises(LeadsheetExportError, match="not available"):
        export_file(media, _args(chord_track="missing"))


def test_export_file_unavailable_rhythm_track_fails(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    _write_analysis(media)

    with pytest.raises(LeadsheetExportError, match="not available"):
        export_file(media, _args(rhythm_track="missing"))


def test_export_file_replaces_existing_leadsheet_atomically(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    analysis_dir = _write_analysis(media)
    leadsheet = analysis_dir / "song-chords-chordino.md"
    leadsheet.write_text("old content\n")

    export_file(media, _args(transpose=0))

    content = leadsheet.read_text()
    assert content.startswith("# song\n")
    assert list(analysis_dir.glob("*.tmp")) == []
    assert list(analysis_dir.glob(".*.tmp")) == []


def test_export_file_atomic_failure_preserves_existing_leadsheet(tmp_path, monkeypatch):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    analysis_dir = _write_analysis(media)
    leadsheet = analysis_dir / "song-chords-chordino.md"
    leadsheet.write_text("old content\n")

    def fail_replace(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr(chordleadsheet_batch.os, "replace", fail_replace)

    with pytest.raises(LeadsheetExportError, match="replace failed"):
        export_file(media, _args())

    assert leadsheet.read_text() == "old content\n"
    assert list(analysis_dir.glob(".*.tmp")) == []


def test_export_file_pdf_failure_publishes_neither_output(tmp_path, monkeypatch):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    analysis_dir = _write_analysis(media)

    def fail_render(self, markdown):
        raise OSError("PDF failed")

    monkeypatch.setattr(chordleadsheet_batch.ChordSheetPdfRenderer, "render_markdown", fail_render)

    with pytest.raises(LeadsheetExportError, match="PDF failed"):
        export_file(media, _args())

    assert not (analysis_dir / "song-chords-chordino.md").exists()
    assert not (analysis_dir / "song-chords-chordino.pdf").exists()


def test_run_continues_after_failures_and_returns_one(tmp_path, monkeypatch):
    good = tmp_path / "good.mp4"
    bad = tmp_path / "bad.mp4"
    good.write_bytes(b"1")
    bad.write_bytes(b"22")
    _write_analysis(good)

    original_export = export_file

    def failing_export(media_path, args):
        if Path(media_path).name == "bad.mp4":
            raise RuntimeError("boom")
        return original_export(media_path, args)

    monkeypatch.setattr(chordleadsheet_batch, "export_file", failing_export)
    messages = []

    exit_code = run(tmp_path, _args(), output=messages.append)

    assert exit_code == 1
    assert any("1 reused analyses" in message for message in messages)
    assert any("1 leadsheets, 1 failed" in message for message in messages)
    assert any("Error:" in message and "boom" in message for message in messages)


def test_run_reports_new_and_reused_analyses(tmp_path, monkeypatch):
    good = tmp_path / "good.mp4"
    missing = tmp_path / "missing.mp4"
    good.write_bytes(b"1")
    missing.write_bytes(b"1")
    _write_analysis(good)

    def fake_analyze(media_path):
        _write_analysis(Path(media_path))

    monkeypatch.setattr(chordleadsheet_batch, "_analyze_media", fake_analyze)
    messages = []

    exit_code = run(tmp_path, _args(), output=messages.append)

    assert exit_code == 0
    assert any(
        "2 files, 1 reused analyses, 1 new analyses, 2 leadsheets, 0 failed" in message
        for message in messages
    )


def test_run_counts_new_analysis_when_later_track_export_fails(tmp_path, monkeypatch):
    media = tmp_path / "new.mp4"
    media.write_bytes(b"media")

    def fake_analyze(media_path):
        _write_analysis(Path(media_path))

    monkeypatch.setattr(chordleadsheet_batch, "_analyze_media", fake_analyze)
    messages = []

    exit_code = run(
        tmp_path,
        _args(chord_track="missing"),
        output=messages.append,
    )

    assert exit_code == 1
    assert any(
        "1 files, 0 reused analyses, 1 new analyses, 0 leadsheets, 1 failed" in message
        for message in messages
    )


def test_run_is_non_recursive(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"1")
    _write_analysis(media)
    nested = tmp_path / "nested"
    nested.mkdir()
    nested_media = nested / "nested.mp3"
    nested_media.write_bytes(b"1")

    messages = []

    exit_code = run(tmp_path, _args(), output=messages.append)

    assert exit_code == 0
    assert any("Found 1 media files" in message for message in messages)
    assert not any("nested.mp3" in message for message in messages)


def test_main_reports_missing_directory_as_exit_two(tmp_path, capsys):
    missing = tmp_path / "missing"

    assert chordleadsheet_batch.main([str(missing)]) == 2
    assert "Media directory does not exist" in capsys.readouterr().err


def test_argument_parser_options():
    parser = build_argument_parser()

    args = parser.parse_args(
        [
            "dir",
            "--chord-track",
            "edited",
            "--rhythm-track",
            "x",
            "--transpose",
            "-2",
            "--sharps",
            "--unicode",
            "--repeat-mode",
            "chords",
            "--no-metric-chords",
        ]
    )

    assert args.chord_track == "edited"
    assert args.rhythm_track == "x"
    assert args.transpose == -2
    assert args.sharps is True
    assert args.unicode is True
    assert args.repeat_mode == "chords"
    assert args.no_metric_chords is True


def test_argument_parser_defaults():
    args = build_argument_parser().parse_args(["dir"])

    assert args.chord_track == "auto"
    assert args.rhythm_track == "qm_barbeattracker"
    assert args.transpose == 0
    assert args.sharps is False
    assert args.unicode is False
    assert args.repeat_mode == "changes"
    assert args.no_metric_chords is False


def test_argument_parser_rejects_unknown_repeat_mode():
    with pytest.raises(SystemExit) as error:
        build_argument_parser().parse_args(["dir", "--repeat-mode", "all"])
    assert error.value.code == 2


def test_helper_imports_do_not_load_flask():
    probe = (
        "import sys\n"
        f"sys.path.insert(0, {str(FLASK_DIR)!r})\n"
        f"sys.path.insert(0, {str(HELPERS_DIR)!r})\n"
        "import chordleadsheet_batch\n"
        "for name in ('flask', 'moviepy', 'vamp', 'librosa'):\n"
        "    assert name not in sys.modules, name\n"
        "print('PASS')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr
    assert "PASS" in result.stdout
