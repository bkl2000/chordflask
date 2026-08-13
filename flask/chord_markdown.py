#!/usr/bin/env python3

"""Pure Markdown formatting for a playable chord leadsheet.

This module has no Flask or filesystem dependencies. It converts a plain
snapshot of the active display state into a UTF-8 Markdown document with one
compact metadata line, a source line, and measure tables of eight whole
measures per block.
"""

import re

_SLUG_RE = re.compile(r"[^a-z0-9]+")

_MEASURES_PER_BLOCK = 8


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
    for previous, current in zip(beat_numbers, beat_numbers[1:]):
        if current != previous % meter + 1:
            return False
    return True


def group_beats_into_measures(beats, meter=None, beat_numbers=None):
    """Group one display chord per beat into measures.

    ``beats`` is a list of chords in beat order. Measure boundaries come from
    ``beat_numbers`` when they cycle predictably around 1..meter; otherwise
    beats are chunked by the meter (or four beats). An initial pickup measure
    may be short and a trailing measure may be incomplete. The result is a
    list of measure chord lists.
    """
    if not beats:
        return []
    if len(beat_numbers or []) == len(beats) and _usable_beat_numbers(beat_numbers, meter):
        measures = []
        current = []
        for chord, number in zip(beats, beat_numbers):
            if number == 1 and current:
                measures.append(current)
                current = []
            current.append(chord)
        if current:
            measures.append(current)
        return measures

    width = meter if _usable_meter(meter) else 4
    measures = []
    for start in range(0, len(beats), width):
        measures.append(list(beats[start : start + width]))
    return measures


def _repeat_beat_fields(measures):
    """Apply the changes repeat mode to measure beat fields.

    The valid chord is repeated at the start of every measure and later held
    beats become ``_``.
    """
    fields = []
    previous = None
    for measure in measures:
        row = []
        for position, chord in enumerate(measure):
            if position == 0:
                cell = chord
            elif chord == previous:
                cell = "_"
            else:
                cell = chord
            row.append(cell)
            previous = chord
        fields.append(row)
    return fields


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
    carries the rhythm track's measure positions when available. Measure
    tables contain eight whole measures per block with centered ``Takt N``
    headers and one cell per measure holding its beat fields.
    """
    if repeat_mode not in {"changes", "chords"}:
        raise ValueError("repeat_mode must be 'changes' or 'chords'")
    beats = list(beats or [])
    measures = group_beats_into_measures(beats, meter=meter, beat_numbers=beat_numbers)
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
    if repeat_mode == "changes":
        lines.append("")
        lines.append("`_` keeps the previous chord.")
    lines.append("")

    for block_start in range(0, len(measures), _MEASURES_PER_BLOCK):
        block = measures[block_start : block_start + _MEASURES_PER_BLOCK]
        headers = [f" Takt {block_start + index + 1} " for index in range(len(block))]
        lines.append("|" + "|".join(headers) + "|")
        lines.append("|" + "|".join(" :---: " for _ in block) + "|")
        cells = [f"`{' '.join(escape_markdown_cell(chord) for chord in measure)}`" for measure in block]
        lines.append("| " + " | ".join(cells) + " |")

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
