"""Pure ChordPro formatting for a chord grid."""

import math

from .chord_markdown import group_beats_into_measures


def _usable_bpm(bpm):
    return (
        isinstance(bpm, (int, float))
        and not isinstance(bpm, bool)
        and math.isfinite(bpm)
        and bpm > 0
    )


def _usable_meter(meter):
    return isinstance(meter, int) and not isinstance(meter, bool) and meter > 0


def _directive_value(value):
    return str(value).replace("\n", " ").replace("\r", " ")


def format_chordpro(
    *,
    title,
    bpm=None,
    meter=None,
    beats,
    beat_numbers=None,
    repeat_mode="changes",
):
    """Render one display chord per beat as a UTF-8 ChordPro grid."""
    if repeat_mode not in {"changes", "chords"}:
        raise ValueError("repeat_mode must be 'changes' or 'chords'")

    measures = group_beats_into_measures(
        list(beats),
        meter=meter,
        beat_numbers=list(beat_numbers or []),
    )
    if repeat_mode == "changes":
        previous = None
        for measure in measures:
            for index, chord in enumerate(measure):
                if chord == previous and chord not in {"", "N", "X"}:
                    measure[index] = "."
                previous = chord

    lines = [f"{{title: {_directive_value(title)}}}"]
    if _usable_bpm(bpm):
        lines.append(f"{{tempo: {bpm}}}")
    if _usable_meter(meter):
        lines.append(f"{{time: {meter}/4}}")
    lines.extend(("", "{start_of_grid}"))
    for start in range(0, len(measures), 2):
        row = measures[start : start + 2]
        lines.append(" ".join(f"| {' '.join(measure)}" for measure in row) + " |")
    lines.append("{end_of_grid}")
    return "\n".join(lines) + "\n"
