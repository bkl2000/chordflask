#!/usr/bin/env python3

"""Pure Markdown formatting for a playable chord leadsheet.

This module has no Flask or filesystem dependencies. It converts a plain
snapshot of the active display state into a UTF-8 Markdown document with one
compact metadata line, a source line, and playable monospace chord rows.
"""

import re

_SLUG_RE = re.compile(r"[^a-z0-9]+")

_MEASURES_PER_BLOCK = 8
_MEASURES_PER_ROW = 2
_MINIMUM_BEAT_WIDTH = 10
_MEASURE_GAP = "      "


def safe_track_slug(track_id):
    """Return a filename-safe slug for a track id."""
    if not isinstance(track_id, str):
        return "chords"
    slug = _SLUG_RE.sub("-", track_id.lower()).strip("-")
    return slug or "chords"


def download_track_slug(track_id):
    """Return the filename track segment for a download.

    ``user_edited`` becomes ``edited``; every other track id is slugified.
    """
    if track_id == "user_edited":
        return "edited"
    return safe_track_slug(track_id)


def escape_markdown_cell(value):
    """Escape a value for a single Markdown table or heading cell."""
    if value is None:
        return ""
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _usable_meter(meter):
    return isinstance(meter, int) and not isinstance(meter, bool) and meter > 0


def _usable_beat_numbers(beat_numbers, meter):
    if not isinstance(beat_numbers, list) or len(beat_numbers) == 0:
        return False
    if not _usable_meter(meter):
        return False
    if any(
        not isinstance(number, int) or isinstance(number, bool) or not 1 <= number <= meter
        for number in beat_numbers
    ):
        return False
    for previous, current in zip(beat_numbers, beat_numbers[1:], strict=False):
        if current != previous % meter + 1:
            return False
    return True


def _group_beats_with_positions(beats, meter=None, beat_numbers=None):
    """Return ``(starting_beat, chords)`` pairs for each measure."""
    if not beats:
        return []
    if len(beat_numbers or []) == len(beats) and _usable_beat_numbers(beat_numbers, meter):
        measures = []
        current = []
        starting_beat = beat_numbers[0]
        for chord, number in zip(beats, beat_numbers, strict=True):
            if number == 1 and current:
                measures.append((starting_beat, current))
                current = []
                starting_beat = number
            current.append(chord)
        if current:
            measures.append((starting_beat, current))
        return measures

    width = meter if _usable_meter(meter) else 4
    return [
        (1, list(beats[start : start + width]))
        for start in range(0, len(beats), width)
    ]


def group_beats_into_measures(beats, meter=None, beat_numbers=None):
    """Group one display chord per beat into measures.

    ``beats`` is a list of chords in beat order. Measure boundaries come from
    ``beat_numbers`` when they cycle predictably around 1..meter; otherwise
    beats are chunked by the meter (or four beats). An initial pickup measure
    may be short and a trailing measure may be incomplete. The result is a
    list of measure chord lists.
    """
    return [
        measure
        for _, measure in _group_beats_with_positions(
            beats,
            meter=meter,
            beat_numbers=beat_numbers,
        )
    ]


def _repeat_beat_fields(measures):
    """Apply the changes repeat mode to measure beat fields.

    A chord change is written once and later held beats become ``-``.
    """
    fields = []
    previous = None
    for measure in measures:
        row = []
        for chord in measure:
            cell = "-" if chord == previous and chord not in {"", "N", "X"} else chord
            row.append(cell)
            previous = chord
        fields.append(row)
    return fields


def _beat_width(measures):
    return max(
        _MINIMUM_BEAT_WIDTH,
        max((len(str(chord)) for measure in measures for chord in measure), default=0),
    )


def _measure_row(measure, *, meter, beat_width, starting_beat=1):
    fields = [""] * meter
    for index, chord in enumerate(measure, starting_beat - 1):
        if index >= meter:
            break
        fields[index] = str(chord)
    return " ".join(field.ljust(beat_width) for field in fields)


def _counting_range(starting_beat, chord_count):
    ending_beat = starting_beat + chord_count - 1
    if starting_beat == ending_beat:
        return str(starting_beat)
    return f"{starting_beat}\u2013{ending_beat}"


def format_leadsheet_markdown(
    *,
    title,
    chord_track,
    rhythm_track,
    version,
    transpose,
    spelling,
    unicode_symbols=False,
    bpm=None,
    meter=None,
    beats=None,
    beat_numbers=None,
    repeat_mode="changes",
):
    """Render the active display view as a playable leadsheet.

    ``beats`` is one display chord per active-rhythm beat. ``beat_numbers``
    carries the rhythm track's measure positions when available. Two complete
    measures are rendered per row, with an initial pickup on its own row.
    """
    if repeat_mode not in {"changes", "chords"}:
        raise ValueError("repeat_mode must be 'changes' or 'chords'")
    beats = list(beats or [])
    positioned_measures = _group_beats_with_positions(
        beats,
        meter=meter,
        beat_numbers=beat_numbers,
    )
    measure_width = meter if _usable_meter(meter) else 4
    positions = [position for position, _ in positioned_measures]
    measures = [measure for _, measure in positioned_measures]
    if repeat_mode == "changes":
        measures = _repeat_beat_fields(measures)
    else:
        measures = [list(measure) for measure in measures]

    lines = [f"# {escape_markdown_cell(title)}", ""]

    metadata = []
    if bpm is not None:
        metadata.append(f"{bpm} BPM")
    if _usable_meter(meter):
        metadata.append(f"{meter}/4")
    metadata.append(escape_markdown_cell(version))
    metadata.append(escape_markdown_cell(spelling))
    metadata.append(f"Transpose {transpose}")
    if unicode_symbols:
        metadata.append("Unicode")
    if metadata:
        lines.append(f"**{' · '.join(metadata)}**")
    lines.append("")

    lines.append(f"{escape_markdown_cell(chord_track)} · {escape_markdown_cell(rhythm_track)}")
    lines.append("")

    lines.append("```text")
    beat_width = _beat_width(measures)

    if measures and positions[0] != 1:
        pickup = measures.pop(0)
        starting_beat = positions.pop(0)
        counting = _counting_range(starting_beat, len(pickup))
        lines.append(f"Auftakt (Zählzeiten {counting})")
        lines.append(
            _measure_row(
                pickup,
                meter=measure_width,
                beat_width=beat_width,
                starting_beat=starting_beat,
            )
        )
        lines.append("")

    for row_start in range(0, len(measures), _MEASURES_PER_ROW):
        row_measures = measures[row_start : row_start + _MEASURES_PER_ROW]
        rendered = [
            _measure_row(measure, meter=measure_width, beat_width=beat_width)
            for measure in row_measures
        ]
        if len(rendered) == 1:
            rendered.append(_measure_row([], meter=measure_width, beat_width=beat_width))
        lines.append(_MEASURE_GAP.join(rendered))
        lines.append("")

        rendered_measure_count = row_start + len(row_measures)
        if rendered_measure_count % _MEASURES_PER_BLOCK == 0:
            lines.append("")

    lines.append("```")

    return "\n".join(lines) + "\n"


def format_chord_markdown(
    *,
    title,
    chord_track,
    rhythm_track,
    version,
    transpose,
    spelling,
    unicode_symbols=False,
    bpm=None,
    meter=None,
    beats,
    repeat_mode="changes",
):
    """Render the active display view as a Markdown leadsheet.

    ``beats`` is a list of ``(beat_number, chord)`` tuples, already respelled
    and formatted for display. ``spelling`` is ``"Flats"`` or ``"Sharps"``.
    """
    return format_leadsheet_markdown(
        title=title,
        chord_track=chord_track,
        rhythm_track=rhythm_track,
        version=version,
        transpose=transpose,
        spelling=spelling,
        unicode_symbols=unicode_symbols,
        bpm=bpm,
        meter=meter,
        beats=[chord for _, chord in beats],
        beat_numbers=[number for number, _ in beats],
        repeat_mode=repeat_mode,
    )
