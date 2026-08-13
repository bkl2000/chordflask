#!/usr/bin/env python3

"""Render ChordFlask Markdown leadsheets as print-ready raster PDFs."""

from dataclasses import dataclass
from io import BytesIO
import os
from pathlib import Path
import re
import tempfile

from PIL import Image, ImageDraw, ImageFont


PAGE_W = 1240
PAGE_H = 1754

MARGIN_X = 45
MARGIN_TOP = 55
MARGIN_BOTTOM = 45

BARS_PER_ROW = 4
ROWS_PER_PAGE = 15
BARS_PER_PAGE = BARS_PER_ROW * ROWS_PER_PAGE

_MEASURE_GAP = 6
_TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_METADATA_RE = re.compile(r"^\*\*(.+?)\*\*$", re.MULTILINE)
_METER_RE = re.compile(r"(?:^|·)\s*([1-9][0-9]*)/4(?:\s*·|$)")
_CODE_BLOCK_RE = re.compile(
    r"```(?:text)?[ \t]*\r?\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)
_PICKUP_RE = re.compile(r"^Auftakt(?:\s+\(Zählzeiten\s+([1-9][0-9]*)(?:–[1-9][0-9]*)?\))?$")


@dataclass(frozen=True)
class ChordSheetMeasure:
    """One full-width measure box, optionally representing a pickup."""

    beats: tuple[str, ...]
    number: int | None
    pickup: bool = False


@dataclass(frozen=True)
class ParsedChordSheet:
    """Markdown content needed by the PDF renderer."""

    title: str
    metadata: str
    source: str
    meter: int
    measures: tuple[ChordSheetMeasure, ...]


class ChordSheetPdfRenderer:
    """Render playable ChordFlask Markdown with the established sheet design.

    Fonts are loaded only from the bundled ``assets/fonts`` directory. Rendering
    therefore has no system-font dependency in source or standalone operation.
    Invalid or empty chord blocks raise ``ValueError``; missing bundled assets
    raise ``FileNotFoundError``. No output is published before a complete PDF has
    been generated.
    """

    def __init__(self, font_dir: str | os.PathLike | None = None):
        self.__font_dir = (
            Path(font_dir)
            if font_dir is not None
            else Path(__file__).resolve().parent / "assets" / "fonts"
        )
        self.__title_font = self.__font("LiberationSans-Bold.ttf", 32)
        self.__metadata_font = self.__font("LiberationSans-Regular.ttf", 16)
        self.__bar_number_font = self.__font("LiberationSans-Regular.ttf", 12)
        self.__chord_fonts = tuple(
            self.__font("LiberationMono-Regular.ttf", size)
            for size in (21, 18, 15, 12)
        )

    def render_markdown(self, markdown: str) -> bytes:
        """Return a complete PDF for one UTF-8 Markdown leadsheet."""
        if not isinstance(markdown, str):
            raise TypeError("markdown must be a string")
        sheet = self.__parse_markdown(markdown, fallback_title="Chord Sheet")
        return self.__render_sheet(sheet)

    def render_file(
        self,
        input_path: str | os.PathLike,
        output_path: str | os.PathLike | None = None,
    ) -> Path:
        """Render a Markdown file atomically and return the PDF output path."""
        source = Path(input_path)
        destination = Path(output_path) if output_path is not None else source.with_suffix(".pdf")
        if destination.suffix.lower() != ".pdf":
            destination = destination.with_suffix(".pdf")

        markdown = source.read_text(encoding="utf-8")
        sheet = self.__parse_markdown(markdown, fallback_title=source.stem)
        pdf = self.__render_sheet(sheet)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.stem}.pdf-",
            suffix=".tmp",
            dir=destination.parent,
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = None
                handle.write(pdf)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, destination)
            temporary_name = None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass
        return destination

    def __font(self, filename: str, size: int):
        path = self.__font_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"Bundled PDF font is missing: {path}")
        return ImageFont.truetype(str(path), size)

    @staticmethod
    def __unescape_markdown(value: str) -> str:
        return value.replace("\\|", "|").replace("\\\\", "\\")

    def __parse_markdown(self, markdown: str, *, fallback_title: str) -> ParsedChordSheet:
        title_match = _TITLE_RE.search(markdown)
        title = title_match.group(1).strip() if title_match else fallback_title
        title = self.__unescape_markdown(title)

        metadata_match = _METADATA_RE.search(markdown)
        metadata = metadata_match.group(1).strip() if metadata_match else ""
        meter_match = _METER_RE.search(metadata)
        meter = int(meter_match.group(1)) if meter_match else 4

        source = ""
        if metadata_match:
            for line in markdown[metadata_match.end() :].splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("```"):
                    break
                source = self.__unescape_markdown(line)
                break

        block_match = _CODE_BLOCK_RE.search(markdown)
        if not block_match:
            raise ValueError("No ```text ... ``` chord block found")
        measures = self.__parse_measure_block(block_match.group(1), meter)
        if not measures:
            raise ValueError("The chord block is empty")

        return ParsedChordSheet(
            title=title,
            metadata=metadata,
            source=source,
            meter=meter,
            measures=tuple(measures),
        )

    def __parse_measure_block(self, block: str, meter: int) -> list[ChordSheetMeasure]:
        lines = block.splitlines()
        meaningful = [(index, line) for index, line in enumerate(lines) if line.strip()]
        pickup_index = None
        pickup_start = 1
        for index, line in meaningful:
            match = _PICKUP_RE.fullmatch(line.strip())
            if match:
                pickup_index = index
                pickup_start = int(match.group(1) or 1)
                break

        pickup_row_index = None
        if pickup_index is not None:
            pickup_row_index = next(
                (index for index, line in meaningful if index > pickup_index and line.strip()),
                None,
            )
            if pickup_row_index is None:
                raise ValueError("The pickup label has no chord row")

        regular_lines = [
            line
            for index, line in meaningful
            if index != pickup_index and index != pickup_row_index
        ]
        measure_width = self.__formatted_measure_width(regular_lines, meter)
        if measure_width is None and pickup_row_index is not None:
            pickup_line = lines[pickup_row_index]
            if (len(pickup_line) - (meter - 1)) % meter == 0:
                measure_width = len(pickup_line)

        if measure_width is None:
            if pickup_index is not None:
                raise ValueError("The pickup chord row has an invalid fixed-width layout")
            return self.__parse_token_stream(block, meter)

        beat_width = (measure_width - (meter - 1)) // meter
        measures = []
        if pickup_row_index is not None:
            pickup_beats = self.__split_fixed_measure(
                lines[pickup_row_index], meter, beat_width
            )
            if pickup_start > meter:
                raise ValueError("The pickup starts outside the time signature")
            measures.append(ChordSheetMeasure(tuple(pickup_beats), None, pickup=True))

        measure_number = 1
        for line in regular_lines:
            expected_length = measure_width * 2 + _MEASURE_GAP
            if len(line) != expected_length:
                raise ValueError("A chord row has an invalid fixed-width layout")
            for start in (0, measure_width + _MEASURE_GAP):
                beats = self.__split_fixed_measure(
                    line[start : start + measure_width], meter, beat_width
                )
                if not any(beats):
                    continue
                measures.append(ChordSheetMeasure(tuple(beats), measure_number))
                measure_number += 1
        return measures

    @staticmethod
    def __formatted_measure_width(lines: list[str], meter: int) -> int | None:
        if not lines or len({len(line) for line in lines}) != 1:
            return None
        line_length = len(lines[0])
        if line_length <= _MEASURE_GAP:
            return None
        content_width = line_length - _MEASURE_GAP
        if content_width % 2:
            return None
        measure_width = content_width // 2
        if measure_width <= meter - 1:
            return None
        if (measure_width - (meter - 1)) % meter:
            return None
        if any(
            line[measure_width : measure_width + _MEASURE_GAP] != " " * _MEASURE_GAP
            for line in lines
        ):
            return None
        return measure_width

    @staticmethod
    def __split_fixed_measure(row: str, meter: int, beat_width: int) -> list[str]:
        expected_length = meter * beat_width + meter - 1
        if len(row) != expected_length:
            raise ValueError("A measure has an invalid fixed-width layout")
        beats = []
        position = 0
        for beat in range(meter):
            beats.append(row[position : position + beat_width].strip())
            position += beat_width
            if beat < meter - 1:
                if row[position] != " ":
                    raise ValueError("Beat fields must be separated by spaces")
                position += 1
        return beats

    @staticmethod
    def __parse_token_stream(block: str, meter: int) -> list[ChordSheetMeasure]:
        tokens = block.split()
        if not tokens:
            return []
        remainder = len(tokens) % meter
        if remainder:
            tokens.extend([""] * (meter - remainder))
        return [
            ChordSheetMeasure(tuple(tokens[start : start + meter]), start // meter + 1)
            for start in range(0, len(tokens), meter)
        ]

    def __render_sheet(self, sheet: ParsedChordSheet) -> bytes:
        page_count = (len(sheet.measures) + BARS_PER_PAGE - 1) // BARS_PER_PAGE
        pages = []
        try:
            for page_number in range(1, page_count + 1):
                start = (page_number - 1) * BARS_PER_PAGE
                page_measures = sheet.measures[start : start + BARS_PER_PAGE]
                pages.append(
                    self.__render_page(sheet, page_measures, page_number, page_count)
                )
            output = BytesIO()
            pages[0].save(
                output,
                "PDF",
                resolution=150.0,
                save_all=True,
                append_images=pages[1:],
            )
            return output.getvalue()
        finally:
            for page in pages:
                page.close()

    def __render_page(self, sheet, measures, page_number, page_count):
        image = Image.new("RGB", (PAGE_W, PAGE_H), "white")
        draw = ImageDraw.Draw(image)

        page_title = sheet.title + (" (cont.)" if page_number > 1 else "")
        draw.text(
            (MARGIN_X, MARGIN_TOP),
            page_title,
            font=self.__title_font,
            fill="black",
        )
        y = MARGIN_TOP + 45

        if sheet.metadata:
            draw.text(
                (MARGIN_X, y),
                sheet.metadata,
                font=self.__metadata_font,
                fill="black",
            )
            y += 27
        if sheet.source:
            draw.text(
                (MARGIN_X, y),
                sheet.source,
                font=self.__metadata_font,
                fill="black",
            )
            y += 27

        page_text = f"{page_number}/{page_count}"
        page_box = draw.textbbox((0, 0), page_text, font=self.__metadata_font)
        page_width = page_box[2] - page_box[0]
        draw.text(
            (PAGE_W - MARGIN_X - page_width, MARGIN_TOP + 5),
            page_text,
            font=self.__metadata_font,
            fill="black",
        )

        grid_top = y + 15
        available_width = PAGE_W - 2 * MARGIN_X
        available_height = PAGE_H - grid_top - MARGIN_BOTTOM
        bar_width = available_width / BARS_PER_ROW
        row_height = available_height / ROWS_PER_PAGE

        for index, measure in enumerate(measures):
            row = index // BARS_PER_ROW
            column = index % BARS_PER_ROW
            x0 = MARGIN_X + column * bar_width
            y0 = grid_top + row * row_height
            x1 = x0 + bar_width
            y1 = y0 + row_height

            draw.rectangle((x0, y0, x1, y1), outline="black", width=2)
            label = "Auftakt" if measure.pickup else str(measure.number)
            draw.text(
                (x0 + 5, y0 + 4),
                label,
                font=self.__bar_number_font,
                fill="black",
            )

            inner_left = x0 + 8
            inner_right = x1 - 8
            inner_top = y0 + 22
            inner_bottom = y1 - 7
            beat_width = (inner_right - inner_left) / sheet.meter
            for beat in range(1, sheet.meter):
                x = inner_left + beat * beat_width
                draw.line((x, inner_top, x, inner_bottom), fill="black", width=1)

            for beat, chord in enumerate(measure.beats):
                if not chord:
                    continue
                center_x = inner_left + (beat + 0.5) * beat_width
                center_y = y0 + row_height * 0.58
                chord_font = self.__fitting_font(draw, chord, beat_width - 6)
                self.__centered_text(draw, center_x, center_y, chord, chord_font)
        return image

    def __fitting_font(self, draw, text, maximum_width):
        for font in self.__chord_fonts:
            box = draw.textbbox((0, 0), text, font=font)
            if box[2] - box[0] <= maximum_width:
                return font
        return self.__chord_fonts[-1]

    @staticmethod
    def __centered_text(draw, x, y, text, font):
        box = draw.textbbox((0, 0), text, font=font)
        width = box[2] - box[0]
        height = box[3] - box[1]
        draw.text((x - width / 2, y - height / 2), text, font=font, fill="black")
