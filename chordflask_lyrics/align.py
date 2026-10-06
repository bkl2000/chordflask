"""Pure musical-timeline alignment and ChordPro rendering."""

from __future__ import annotations

from dataclasses import dataclass, replace
import bisect
from collections.abc import Callable
import unicodedata

from chordflask.chord_markdown import group_beats_into_measures

from .lrclib import LyricsRecord, TimedLyricLine


@dataclass(frozen=True)
class AlignedRun:
    chord: str | None
    lyric: str
    chord_time: float | None = None
    beat_index: int | None = None


@dataclass(frozen=True)
class AlignedRow:
    measure_start: int
    measure_count: int
    runs: tuple[AlignedRun, ...]
    start_beat: int | None = None
    end_beat: int | None = None
    chord_end_beat: int | None = None


def time_plain_lyrics(value: str, beat_times: list[float]) -> tuple[TimedLyricLine, ...]:
    """Place plain lyric lines in order across the analyzed beat timeline.

    Plain tags contain no synchronization information. Equal beat-span placement
    keeps this fallback deterministic and lets the normal alignment path handle
    all chord and measure mapping.
    """
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines or not beat_times:
        return ()
    beat_count = len(beat_times)
    return tuple(
        TimedLyricLine(beat_times[min(index * beat_count // len(lines), beat_count - 1)], line)
        for index, line in enumerate(lines)
    )


def beat_at_or_after_index(timestamp: float, beat_times: list[float]) -> int:
    """Map a lyric start to the first beat that does not precede it.

    A timestamp beyond the analyzed grid is clamped to the final beat. This
    prevents measure grouping from moving an ordinary lyric start earlier than
    its synchronized timestamp.
    """
    if not beat_times:
        raise ValueError("analysis has no beat times")
    return min(bisect.bisect_left(beat_times, timestamp), len(beat_times) - 1)


def _measure_map(beat_times, beat_numbers, meter):
    measures = group_beats_into_measures(
        list(range(len(beat_times))),
        meter=meter,
        beat_numbers=beat_numbers,
    )
    mapping = {}
    for measure_index, beats in enumerate(measures):
        for beat_index in beats:
            mapping[beat_index] = measure_index
    return measures, mapping


def _word_boundary(text: str, position: int) -> int:
    """Snap an estimated marker offset without splitting an ordinary word."""
    position = max(0, min(len(text), position))
    boundaries = [0, len(text)]
    boundaries.extend(
        index
        for index in range(1, len(text))
        if text[index - 1].isspace() or text[index].isspace()
    )
    return min(boundaries, key=lambda index: (abs(index - position), index > position))


def _text_unit_boundaries(text: str) -> list[int]:
    """Return lightweight grapheme-like boundaries without an NLP dependency.

    Python's standard library does not expose full Unicode grapheme clustering.
    Keeping marks, variation selectors, emoji modifiers, and ZWJ sequences with
    their preceding base nevertheless protects the common combining sequences
    that proportional lyric placement must not split.
    """
    if not text:
        return [0]
    boundaries = [0]
    for index in range(1, len(text)):
        character = text[index]
        previous = text[index - 1]
        category = unicodedata.category(character)
        extends_previous = (
            category.startswith("M")
            or character == "\u200d"
            or previous == "\u200d"
            or "\ufe00" <= character <= "\ufe0f"
            or "\U000e0100" <= character <= "\U000e01ef"
            or "\U0001f3fb" <= character <= "\U0001f3ff"
        )
        if not extends_previous:
            boundaries.append(index)
    boundaries.append(len(text))
    return boundaries


def _proportional_boundaries(text, event_times, start_time, end_time):
    """Map events to safe boundaries, keeping positions distinct when possible."""
    boundaries = _text_unit_boundaries(text)
    unit_count = len(boundaries) - 1
    if not event_times or unit_count == 0 or end_time <= start_time:
        return [0] * len(event_times)

    targets = [
        round(
            max(0.0, min(1.0, (event_time - start_time) / (end_time - start_time)))
            * unit_count
        )
        for event_time in event_times
    ]
    if len(targets) <= len(boundaries):
        previous = -1
        for index, target in enumerate(targets):
            remaining = len(targets) - index - 1
            targets[index] = max(previous + 1, min(target, unit_count - remaining))
            previous = targets[index]
    return [boundaries[target] for target in targets]


def _marker_positions(text, events, line_start, line_end, coverage_end):
    """Prefer word boundaries, falling back when they collapse timed events."""
    word_positions = []
    for event_time, _chord, _chord_time, _beat_index in events:
        fraction = 0.0
        if line_end > line_start:
            fraction = (event_time - line_start) / (line_end - line_start)
        word_positions.append(_word_boundary(text, round(fraction * len(text))))

    proportional = _proportional_boundaries(
        text,
        [event[0] for event in events],
        events[0][0] if events else line_start,
        coverage_end,
    )
    if len(set(word_positions)) < len(set(proportional)):
        return proportional
    return word_positions


def _row_runs(lines, end_times, beat_times, beat_chords, row_end_beat):
    runs = []
    previous_chord = None
    for line_index, line in enumerate(lines):
        if line_index:
            runs.append(AlignedRun(None, " "))
        end_time = end_times[line_index]
        events = []

        # Anchor the chord authoritative at the mapped lyric-start beat. This
        # deliberately repeats a held chord on each new timed lyric line.
        # Subsequent events retain their analyzed beat times; event count never
        # controls their placement.
        line_start_beat = beat_at_or_after_index(line.timestamp, beat_times)
        if line_start_beat < row_end_beat:
            chord = beat_chords[line_start_beat]
            if chord not in {"", "N", "X"}:
                events.append(
                    (
                        beat_times[line_start_beat],
                        chord,
                        beat_times[line_start_beat],
                        line_start_beat,
                    )
                )
                previous_chord = chord

        first_change = bisect.bisect_left(beat_times, line.timestamp)
        # A rendered row owns only its own measures: clamp chord events to the
        # row's mapped beat span so an instrumental gap after the row is left
        # unmapped instead of being smeared onto the previous lyric line.
        end_beat = min(
            bisect.bisect_left(beat_times, end_time),
            row_end_beat,
            len(beat_chords),
        )
        for beat_index in range(first_change, end_beat):
            chord = beat_chords[beat_index]
            if chord in {"", "N", "X"} or chord == previous_chord:
                continue
            events.append(
                (beat_times[beat_index], chord, beat_times[beat_index], beat_index)
            )
            previous_chord = chord
        coverage_end = (
            beat_times[row_end_beat]
            if row_end_beat < len(beat_times)
            else end_time
        )
        positions = _marker_positions(
            line.text,
            events,
            line.timestamp,
            end_time,
            min(end_time, coverage_end),
        )
        cursor = 0
        for (_event_time, chord, chord_time, beat_index), position in zip(
            events, positions, strict=True
        ):
            if position < cursor:
                position = cursor
            lyric = line.text[cursor:position]
            if lyric or not runs:
                runs.append(AlignedRun(None, lyric))
            runs.append(AlignedRun(chord, "", chord_time, beat_index))
            cursor = position
        runs.append(AlignedRun(None, line.text[cursor:]))

    compact = []
    for run in runs:
        if compact and run.chord is None and compact[-1].chord is None:
            prior = compact.pop()
            compact.append(AlignedRun(None, prior.lyric + run.lyric))
        else:
            compact.append(run)
    return tuple(compact)


def _bound_row_runs(rows, beat_chords):
    """Cap each timed lyric line's final marker at its own coverage end."""
    bounded = []
    for row in rows:
        row_chords = [run for run in row.runs if run.chord is not None]
        if not row_chords:
            bounded.append(row)
            continue
        last_run = row_chords[-1]
        if last_run.beat_index is None:
            bounded.append(row)
            continue

        analyzed_chord = beat_chords[last_run.beat_index]
        run_end = last_run.beat_index + 1
        while run_end < len(beat_chords) and beat_chords[run_end] == analyzed_chord:
            run_end += 1
        effective_end = min(row.end_beat, run_end)
        bounded.append(replace(row, chord_end_beat=effective_end))
    return tuple(bounded)


def align_lyrics(
    lines: tuple[TimedLyricLine, ...],
    *,
    beat_times: list[float],
    beat_numbers: list[int],
    meter: int | None,
    beat_chords: list[str],
) -> tuple[AlignedRow, ...]:
    """Align every visible timed lyric line to its own beat coverage."""
    if not lines:
        raise ValueError("synchronized lyrics are empty")
    if len(beat_times) != len(beat_chords):
        raise ValueError("beat times and beat chords must have equal lengths")
    measures, measure_by_beat = _measure_map(beat_times, beat_numbers, meter)
    if not measures:
        raise ValueError("analysis has no measures")

    song_end = beat_times[-1] + (beat_times[-1] - beat_times[-2] if len(beat_times) > 1 else 1.0)
    located = []
    for index, line in enumerate(lines):
        end_time = lines[index + 1].timestamp if index + 1 < len(lines) else song_end
        located.append((line, beat_at_or_after_index(line.timestamp, beat_times), end_time))
    rows = []
    for line, start_beat, end_time in located:
        if not line.text.strip():
            continue
        measure_index = measure_by_beat[start_beat]
        max_line_span = (meter or 4) * 4
        row_end_beat = min(
            bisect.bisect_left(beat_times, end_time),
            start_beat + max_line_span,
            len(beat_chords),
        )
        row_end_beat = max(start_beat + 1, row_end_beat)
        rows.append(
            AlignedRow(
                measure_index,
                1,
                _row_runs(
                    [line], [end_time], beat_times, beat_chords, row_end_beat
                ),
                start_beat,
                row_end_beat,
            )
        )
    return _bound_row_runs(rows, beat_chords)


def _escape(value: object) -> str:
    result = str(value).replace("\\", "\\\\")
    for character in "[]{}":
        result = result.replace(character, f"\\{character}")
    return result.replace("\r", " ").replace("\n", " ")


def render_chordpro(
    record: LyricsRecord,
    rows: tuple[AlignedRow, ...],
    *,
    search_hint: str | None = None,
    key: str | None = None,
    capo: int | None = None,
    chord_track_id: str | None = None,
    romanize: Callable[[str], str | None] | None = None,
    provenance: dict[str, str] | None = None,
) -> str:
    """Render aligned rows into the subset accepted by ChordFlask's parser."""
    output = [f"{{title: {_escape(record.title)}}}", f"{{artist: {_escape(record.artist)}}}"]
    for name, value in (provenance or {}).items():
        output.append(f"{{{name}: {_escape(value)}}}")
    if key:
        output.append(f"{{key: {_escape(key)}}}")
    if capo is not None:
        output.append(f"{{capo: {_escape(capo)}}}")
    if search_hint is not None:
        output.append(f"{{x_lrclib_search: {_escape(search_hint)}}}")
    if chord_track_id is not None:
        output.append(f"{{x_chordflask_track: {_escape(chord_track_id)}}}")
    output.append("")
    for row in rows:
        lyric_text = "".join(run.lyric for run in row.runs)
        romanized = romanize(lyric_text) if romanize is not None else None
        if (
            row.start_beat is not None
            and row.end_beat is not None
            and row.end_beat > row.start_beat
        ):
            output.append(
                f"{{x_chordflask_line: {row.start_beat},{row.end_beat}}}"
            )
        if romanized:
            output.append(f"{{x_chordflask_romanized: {_escape(romanized)}}}")
        chord_runs = [run for run in row.runs if run.chord is not None]
        beat_indices = [run.beat_index for run in chord_runs]
        chord_end_beat = row.chord_end_beat or row.end_beat
        if (
            chord_runs
            and all(beat is not None for beat in beat_indices)
            and chord_end_beat is not None
            and chord_end_beat > beat_indices[-1]
        ):
            beats = ",".join(str(beat) for beat in beat_indices)
            output.append(f"{{x_chordflask_beats: {beats}}}")
            output.append(f"{{x_chordflask_end: {chord_end_beat}}}")
        line = []
        for run in row.runs:
            if run.chord is not None:
                line.append(f"[{_escape(run.chord)}]")
            line.append(_escape(run.lyric))
        output.append("".join(line))
    return "\n".join(output) + "\n"
