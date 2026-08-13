from pathlib import Path
import re
import subprocess
import sys

import pytest
from PIL import ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[1]
FLASK_DIR = REPO_ROOT / "flask"
HELPER = FLASK_DIR / "helpers" / "create_sheet_pdf.py"
REFERENCE = REPO_ROOT / "tests" / "fixtures" / "chord_sheet_reference.md"

if str(FLASK_DIR) not in sys.path:
    sys.path.insert(0, str(FLASK_DIR))

from chord_markdown import format_leadsheet_markdown  # noqa: E402
from chord_sheet_pdf import ChordSheetPdfRenderer  # noqa: E402


def _page_count(pdf):
    return len(re.findall(rb"/Type /Page(?:\s|/)", pdf))


def test_render_reference_markdown_is_a4_pdf_with_preserved_design_size():
    pdf = ChordSheetPdfRenderer().render_markdown(REFERENCE.read_text(encoding="utf-8"))

    assert pdf.startswith(b"%PDF")
    assert _page_count(pdf) == 1
    assert b"/MediaBox [ 0 0 595.2 841.92 ]" in pdf


def test_render_three_four_pickup_and_incomplete_ending(monkeypatch):
    drawn = []
    original_text = ImageDraw.ImageDraw.text

    def record_text(draw, xy, text, *args, **kwargs):
        font = kwargs.get("font")
        drawn.append((text, getattr(font, "size", None)))
        return original_text(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", record_text)
    markdown = format_leadsheet_markdown(
        title="Waltz",
        chord_track="Chordino",
        rhythm_track="QM Bar/Beat Tracker",
        version="Original",
        transpose=0,
        spelling="Flats",
        unicode_symbols=True,
        bpm=96,
        meter=3,
        beats=["G♭maj7", "B♭m7♭5", "Cmaj13(#11)", "N", "X", "D♭/F"],
        beat_numbers=[2, 3, 1, 2, 3, 1],
        repeat_mode="chords",
    )

    pdf = ChordSheetPdfRenderer().render_markdown(markdown)

    assert pdf.startswith(b"%PDF")
    assert _page_count(pdf) == 1
    drawn_text = [text for text, _ in drawn]
    for literal in ("Auftakt", "G♭maj7", "B♭m7♭5", "Cmaj13(#11)", "N", "X", "D♭/F"):
        assert literal in drawn_text
    sizes = {text: size for text, size in drawn}
    assert sizes["Cmaj13(#11)"] < sizes["N"]


def test_render_uses_sixty_boxes_per_page_and_continues():
    beat_count = 61 * 4
    markdown = format_leadsheet_markdown(
        title="Long Song",
        chord_track="Chordino",
        rhythm_track="QM Bar/Beat Tracker",
        version="Original",
        transpose=0,
        spelling="Flats",
        meter=4,
        beats=["C"] * beat_count,
        beat_numbers=[index % 4 + 1 for index in range(beat_count)],
        repeat_mode="chords",
    )

    pdf = ChordSheetPdfRenderer().render_markdown(markdown)

    assert _page_count(pdf) == 2


def test_render_file_uses_default_and_explicit_output_paths(tmp_path):
    source = tmp_path / "song.md"
    source.write_text(REFERENCE.read_text(encoding="utf-8"), encoding="utf-8")
    renderer = ChordSheetPdfRenderer()

    default_output = renderer.render_file(source)
    explicit_output = renderer.render_file(source, tmp_path / "named.output")

    assert default_output == tmp_path / "song.pdf"
    assert explicit_output == tmp_path / "named.pdf"
    assert default_output.read_bytes().startswith(b"%PDF")
    assert explicit_output.read_bytes().startswith(b"%PDF")


def test_render_failure_preserves_existing_output(tmp_path):
    source = tmp_path / "broken.md"
    source.write_text("# Broken\n", encoding="utf-8")
    output = tmp_path / "broken.pdf"
    output.write_bytes(b"existing")

    with pytest.raises(ValueError, match="chord block"):
        ChordSheetPdfRenderer().render_file(source, output)

    assert output.read_bytes() == b"existing"
    assert list(tmp_path.glob(".*.pdf-*.tmp")) == []


def test_render_rejects_missing_or_empty_chord_blocks():
    renderer = ChordSheetPdfRenderer()

    with pytest.raises(ValueError, match="chord block"):
        renderer.render_markdown("# No block\n")
    with pytest.raises(ValueError, match="empty"):
        renderer.render_markdown("# Empty\n\n```text\n\n```\n")


def test_render_requires_bundled_fonts(tmp_path):
    with pytest.raises(FileNotFoundError, match="Bundled PDF font"):
        ChordSheetPdfRenderer(font_dir=tmp_path)


def test_pdf_cli_supports_default_and_output_option(tmp_path):
    source = tmp_path / "song.md"
    source.write_text(REFERENCE.read_text(encoding="utf-8"), encoding="utf-8")
    explicit = tmp_path / "explicit.pdf"

    default_run = subprocess.run(
        [sys.executable, str(HELPER), str(source)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    explicit_run = subprocess.run(
        [sys.executable, str(HELPER), str(source), "-o", str(explicit)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    assert default_run.returncode == 0, default_run.stderr
    assert explicit_run.returncode == 0, explicit_run.stderr
    assert source.with_suffix(".pdf").read_bytes().startswith(b"%PDF")
    assert explicit.read_bytes().startswith(b"%PDF")


def test_bundled_fonts_are_open_licensed_and_loadable():
    font_dir = FLASK_DIR / "assets" / "fonts"
    license_text = (font_dir / "LICENSE.txt").read_text(encoding="utf-8")

    assert "SIL OPEN FONT LICENSE Version 1.1" in license_text
    for name in (
        "LiberationSans-Regular.ttf",
        "LiberationSans-Bold.ttf",
        "LiberationMono-Regular.ttf",
    ):
        font = ImageFont.truetype(str(font_dir / name), 16)
        assert font.getbbox("Cmaj13(#11)")
