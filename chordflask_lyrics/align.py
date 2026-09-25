"""Pure musical-timeline alignment and ChordPro rendering."""

from __future__ import annotations

from dataclasses import dataclass, replace
import bisect

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
    end_beat: int | None = None


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


def _row_runs(lines, end_times, beat_times, beat_chords, row_end_beat):
    runs = []
    previous_chord = None
    for line_index, line in enumerate(lines):
        if line_index:
            runs.append(AlignedRun(None, " "))
        end_time = end_times[line_index]
        events = []

        # Preserve the chord already active at the lyric timestamp. Subsequent
        # events retain their analyzed beat times; event count never controls
        # their placement.
        active_beat = bisect.bisect_right(beat_times, line.timestamp) - 1
        if active_beat >= 0:
            chord = beat_chords[active_beat]
            if chord not in {"", "N", "X"} and chord != previous_chord:
                events.append(
                    (line.timestamp, chord, beat_times[active_beat], active_beat)
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
        cursor = 0
        for event_time, chord, chord_time, beat_index in events:
            fraction = 0.0
            if end_time > line.timestamp:
                fraction = (event_time - line.timestamp) / (end_time - line.timestamp)
            position = max(0, min(len(line.text), round(fraction * len(line.text))))
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
    """Give each row's final marker its effective analyzed range end.

    The effective end is the analyzed chord-run end capped by mapped Lyrics
    coverage. Adjacent rows are continuous coverage, so a display-row boundary
    does not truncate a held chord. A gap between rows retains the earlier
    coverage boundary. If adjacent rows split one run, the earlier marker owns
    it and the redundant marker at the start of the next row is removed. A
    later surviving marker takes ownership at its own start beat.
    """
    bounded = list(rows)
    for index, row in enumerate(bounded):
        row_chords = [run for run in row.runs if run.chord is not None]
        if not row_chords:
            continue
        last_run = row_chords[-1]
        if last_run.beat_index is None:
            continue

        analyzed_chord = beat_chords[last_run.beat_index]
        run_end = last_run.beat_index + 1
        while run_end < len(beat_chords) and beat_chords[run_end] == analyzed_chord:
            run_end += 1
        next_row = bounded[index + 1] if index + 1 < len(bounded) else None
        contiguous = (
            next_row is not None
            and row.measure_start + row.measure_count == next_row.measure_start
        )
        effective_end = run_end if contiguous else min(row.end_beat, run_end)
        next_chords = (
            [run for run in next_row.runs if run.chord is not None]
            if next_row is not None
            else []
        )
        if contiguous and next_chords:
            first_next_run = next_chords[0]
            if (
                first_next_run.beat_index is not None
                and first_next_run.beat_index < run_end
            ):
                next_runs = tuple(
                    replace(run, chord=None, chord_time=None, beat_index=None)
                    if run is first_next_run else run
                    for run in next_row.runs
                )
                bounded[index + 1] = replace(next_row, runs=next_runs)

        next_mapped_run = next(
            (
                run
                for later_row in bounded[index + 1 :]
                for run in later_row.runs
                if run.chord is not None and run.beat_index is not None
            ),
            None,
        )
        if (
            next_mapped_run is not None
            and last_run.beat_index < next_mapped_run.beat_index < effective_end
        ):
            effective_end = next_mapped_run.beat_index
        bounded[index] = replace(row, end_beat=effective_end)
    return tuple(bounded)


def align_lyrics(
    lines: tuple[TimedLyricLine, ...],
    *,
    beat_times: list[float],
    beat_numbers: list[int],
    meter: int | None,
    beat_chords: list[str],
) -> tuple[AlignedRow, ...]:
    """Align lines to beat/measure groups, normally four measures per row."""
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
    four_measure_groups = {}
    for line, beat_index, end_time in located:
        measure_index = measure_by_beat[beat_index]
        four_measure_groups.setdefault(measure_index // 4, []).append((line, beat_index, end_time))

    row_specs = []
    for group_index in sorted(four_measure_groups):
        entries = four_measure_groups[group_index]
        text_size = sum(len(line.text) for line, _, _ in entries)
        group_start = group_index * 4
        group_beats = [beat for measure in measures[group_start : group_start + 4] for beat in measure]
        chord_density = len({beat_chords[index] for index in group_beats})
        use_two = text_size > 120 or chord_density > 8
        subgroups = {}
        for line, beat_index, end_time in entries:
            measure_index = measure_by_beat[beat_index]
            subgroup = measure_index // 2 if use_two else group_index
            subgroups.setdefault(subgroup, []).append((line, beat_index, end_time))
        for subgroup in sorted(subgroups):
            selected = subgroups[subgroup]
            row_lines = [item[0] for item in selected]
            row_ends = [item[2] for item in selected]
            measure_start = subgroup * 2 if use_two else group_index * 4
            measure_count = min(2 if use_two else 4, len(measures) - measure_start)
            row_beats = [
                beat
                for measure in measures[measure_start : measure_start + measure_count]
                for beat in measure
            ]
            # Exclusive analyzed beat end of this rendered row's measures. It is
            # the boundary used to clear Lyrics sync in an instrumental gap.
            row_end_beat = row_beats[-1] + 1 if row_beats else measure_start
            row_specs.append(
                (measure_start, measure_count, row_lines, row_ends, row_end_beat)
            )

    rows = []
    for index, spec in enumerate(row_specs):
        measure_start, measure_count, row_lines, row_ends, row_end_beat = spec
        next_spec = row_specs[index + 1] if index + 1 < len(row_specs) else None
        if (
            next_spec is not None
            and measure_start + measure_count == next_spec[0]
        ):
            # Consecutive display rows are one mapped Lyrics span. Keep every
            # analyzed change up to the next timed lyric instead of truncating
            # the marker set merely because the visual row changed.
            row_end_beat = max(
                row_end_beat,
                bisect.bisect_left(beat_times, row_ends[-1]),
            )
        rows.append(
            AlignedRow(
                measure_start,
                measure_count,
                _row_runs(
                    row_lines, row_ends, beat_times, beat_chords, row_end_beat
                ),
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
) -> str:
    """Render aligned rows into the subset accepted by ChordFlask's parser."""
    output = [f"{{title: {_escape(record.title)}}}", f"{{artist: {_escape(record.artist)}}}"]
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
        chord_runs = [run for run in row.runs if run.chord is not None]
        beat_indices = [run.beat_index for run in chord_runs]
        if (
            chord_runs
            and all(beat is not None for beat in beat_indices)
            and row.end_beat is not None
            and row.end_beat > beat_indices[-1]
        ):
            beats = ",".join(str(beat) for beat in beat_indices)
            output.append(f"{{x_chordflask_beats: {beats}}}")
            output.append(f"{{x_chordflask_end: {row.end_beat}}}")
        line = []
        for run in row.runs:
            if run.chord is not None:
                line.append(f"[{_escape(run.chord)}]")
            line.append(_escape(run.lyric))
        output.append("".join(line))
    return "\n".join(output) + "\n"
