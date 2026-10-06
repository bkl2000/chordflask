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
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\n", " ")
        .replace("\r", " ")
    )


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


def _escape_song_text(value):
    return str(value).replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def format_export_chordpro(sheet):
    """Render a shared export sheet as a grid or lyric-bearing song sheet."""
    if not sheet.lyrics:
        return format_chordpro(
            title=sheet.title,
            bpm=sheet.bpm,
            meter=sheet.meter,
            beats=[chord for _, chord in sheet.beats],
            beat_numbers=[number for number, _ in sheet.beats],
            repeat_mode=sheet.repeat_mode,
        )

    lines = [f"{{title: {_directive_value(sheet.title)}}}"]
    for name, value in sheet.lyrics_provenance:
        lines.append(f"{{{name}: {_directive_value(value)}}}")
    if _usable_bpm(sheet.bpm):
        lines.append(f"{{tempo: {sheet.bpm}}}")
    if _usable_meter(sheet.meter):
        lines.append(f"{{time: {sheet.meter}/4}}")
    lines.append("")
    section_directives = {
        "verse": ("start_of_verse", "end_of_verse"),
        "chorus": ("start_of_chorus", "end_of_chorus"),
        "bridge": ("start_of_bridge", "end_of_bridge"),
    }
    for block in sheet.lyrics:
        if block.type == "blank":
            lines.append("")
            continue
        if block.type == "section_start":
            start = section_directives.get(block.section or "", ("start_of_verse", ""))[0]
            lines.append(f"{{{start}: {_directive_value(block.heading or '')}}}")
            continue
        if block.type == "section_end":
            end = section_directives.get(block.section or "", ("", "end_of_verse"))[1]
            lines.append(f"{{{end}}}")
            continue
        if block.type == "comment" and block.text:
            lines.append(f"{{comment: {_directive_value(block.text)}}}")
            continue
        if block.type != "line":
            continue
        if block.romanized:
            lines.append(f"{{x_chordflask_romanized: {_directive_value(block.romanized)}}}")
        synchronized = [
            run for run in block.runs
            if run.chord is not None and run.start_beat is not None
        ]
        chord_runs = [run for run in block.runs if run.chord is not None]
        if synchronized and len(synchronized) == len(chord_runs):
            lines.append("{x_chordflask_beats: " + ",".join(
                str(run.start_beat) for run in synchronized
            ) + "}")
            if synchronized[-1].end_beat is not None:
                lines.append(f"{{x_chordflask_end: {synchronized[-1].end_beat}}}")
        if block.line_start_beat is not None and block.line_end_beat is not None:
            lines.append(
                f"{{x_chordflask_line: {block.line_start_beat},{block.line_end_beat}}}"
            )
        # Chord markers are model-generated. Escape only lyric fragments.
        line = "".join(
            (f"[{run.chord}]" if run.chord is not None else "")
            + _escape_song_text(run.lyric)
            for run in block.runs
        )
        lines.append(line)
    return "\n".join(lines).rstrip() + "\n"
