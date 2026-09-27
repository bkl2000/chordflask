from chordflask.chordpro_song import parse_chordpro
from chordflask_lyrics.align import (
    align_lyrics,
    beat_at_or_after_index,
    render_chordpro,
    time_plain_lyrics,
)
from chordflask_lyrics.lrclib import LyricsRecord, TimedLyricLine


def marker_offsets(row):
    offset = 0
    markers = []
    for run in row.runs:
        if run.chord:
            markers.append((run.chord, offset, run.beat_index))
        offset += len(run.lyric)
    return markers


def test_plain_lyrics_are_distributed_over_existing_beat_times():
    assert time_plain_lyrics("first\n\nsecond", [0.0, 1.0, 2.0, 3.0]) == (
        TimedLyricLine(0.0, "first"),
        TimedLyricLine(2.0, "second"),
    )


def test_lyric_start_maps_to_first_beat_at_or_after_without_moving_earlier():
    beats = [0.0, 1.0, 2.0]
    assert beat_at_or_after_index(0.0, beats) == 0
    assert beat_at_or_after_index(0.01, beats) == 1
    assert beat_at_or_after_index(1.0, beats) == 1
    assert beat_at_or_after_index(-1, beats) == 0
    assert beat_at_or_after_index(9, beats) == 2


def test_uneven_chord_times_remain_uneven_inside_lyric_interval():
    rows = align_lyrics(
        (TimedLyricLine(0, "abcdefghijklmnopqrst"), TimedLyricLine(10, "next")),
        beat_times=[0.0, 0.8, 1.0, 8.7, 9.0, 10.0],
        beat_numbers=[1, 2, 3, 4, 1, 2],
        meter=4,
        beat_chords=["C", "C", "G", "Am", "Am", "F"],
    )

    first_row = rows[0].runs
    chord_runs = [run for run in first_row if run.chord]
    assert [(run.chord, run.chord_time) for run in chord_runs[:3]] == [
        ("C", 0.0),
        ("G", 1.0),
        ("Am", 8.7),
    ]
    # With no usable word boundaries, physical timing supplies distinct,
    # proportional text-unit positions instead of collapsing at both ends.
    assert [offset for _chord, offset, _beat in marker_offsets(rows[0])[:3]] == [
        0, 2, 17,
    ]


def test_no_space_text_distributes_markers_proportionally():
    text = "abcdefghijklmnopqrst"
    rows = align_lyrics(
        (TimedLyricLine(0, text), TimedLyricLine(10, "next")),
        beat_times=[0.0, 2.0, 5.0, 8.0, 10.0],
        beat_numbers=[1, 2, 3, 4, 1],
        meter=4,
        beat_chords=["C", "G", "Am", "F", "C"],
    )

    offsets = [offset for _chord, offset, _beat in marker_offsets(rows[0])]
    assert offsets == [0, 4, 10, 16]
    assert len(set(offsets)) == 4


def test_thai_markers_use_general_no_space_fallback_and_keep_romanization():
    text = "ขนาดแค่คิดหัวใจยังสั่น จริงๆ นะเธอ"
    beat_times = [float(index) for index in range(301)]
    beat_chords = ["N"] * len(beat_times)
    for start, end, chord in (
        (207, 208, "Em"),
        (208, 212, "Am7"),
        (212, 216, "B"),
        (216, 218, "E"),
        (218, 220, "E6"),
        (220, 301, "Em"),
    ):
        beat_chords[start:end] = [chord] * (end - start)
    lines = (TimedLyricLine(207, text), TimedLyricLine(300, "next"))
    rows = align_lyrics(
        lines,
        beat_times=beat_times,
        beat_numbers=[index % 4 + 1 for index in range(len(beat_times))],
        meter=4,
        beat_chords=beat_chords,
    )

    markers = marker_offsets(rows[0])
    assert [(chord, beat) for chord, _offset, beat in markers] == [
        ("Em", 207), ("Am7", 208), ("B", 212),
        ("E", 216), ("E6", 218), ("Em", 220),
    ]
    assert [offset for _chord, offset, _beat in markers] == [0, 2, 10, 21, 26, 29]

    content = render_chordpro(
        LyricsRecord(1, "แม้ว่า", "Sek Loso", None, 301, lines),
        rows,
        romanize=lambda value: (
            "khanat khae khit huachai yang san chingo na thoe"
            if value == text else None
        ),
    )
    block = next(
        block for block in parse_chordpro(content)["blocks"]
        if block["type"] == "line"
    )
    assert block["romanized"] == (
        "khanat khae khit huachai yang san chingo na thoe"
    )
    assert "".join(run["lyric"] for run in block["runs"]) == text


def test_proportional_fallback_does_not_split_combining_sequences():
    text = "a\u0301b\u0327c\u0301d"
    rows = align_lyrics(
        (TimedLyricLine(0, text), TimedLyricLine(8, "next")),
        beat_times=[float(index) for index in range(9)],
        beat_numbers=[index % 4 + 1 for index in range(9)],
        meter=4,
        beat_chords=["C", "G", "Am", "F", "C", "G", "Am", "F", "C"],
    )

    offsets = [offset for _chord, offset, _beat in marker_offsets(rows[0])]
    assert set(offsets) <= {0, 2, 4, 6, 7}
    assert not set(offsets) & {1, 3, 5}
    assert "".join(run.lyric for run in rows[0].runs) == text


def test_chord_is_not_moved_before_its_analyzed_beat():
    rows = align_lyrics(
        (TimedLyricLine(0, "pickup"), TimedLyricLine(0.5, "downbeat")),
        beat_times=[1.0, 2.0],
        beat_numbers=[1, 2],
        meter=4,
        beat_chords=["C", "G"],
    )

    lyric_offset = 0
    first_chord_offset = None
    for run in rows[0].runs:
        if run.chord and first_chord_offset is None:
            first_chord_offset = lyric_offset
        lyric_offset += len(run.lyric)
    assert first_chord_offset is not None
    assert first_chord_offset == len("pickup")


def test_active_repeated_chord_is_reanchored_for_each_timed_line():
    rows = align_lyrics(
        (TimedLyricLine(0, "one"), TimedLyricLine(1, "two"), TimedLyricLine(2, "three")),
        beat_times=[0.0, 1.0, 2.0, 3.0],
        beat_numbers=[1, 2, 3, 4],
        meter=4,
        beat_chords=["C", "C", "C", "C"],
    )

    assert len(rows) == 3
    assert [
        [run.chord for run in row.runs if run.chord]
        for row in rows
    ] == [["C"], ["C"], ["C"]]


def test_active_repeated_chord_transfers_at_a_timed_line_boundary():
    beat_times = [float(index) for index in range(32)]
    beat_chords = ["N"] * 15 + ["C"] * 5 + ["D"] * 12
    lines = (TimedLyricLine(15, "one"), TimedLyricLine(17, "two"))

    rows = align_lyrics(
        lines,
        beat_times=beat_times,
        beat_numbers=[index % 4 + 1 for index in range(32)],
        meter=4,
        beat_chords=beat_chords,
    )
    content = render_chordpro(LyricsRecord(1, "T", "A", None, 32, lines), rows)
    parsed = parse_chordpro(content)
    markers = [
        run
        for block in parsed["blocks"] if block["type"] == "line"
        for run in block["runs"] if run["chord"]
    ]

    assert [
        (run["chord"], run["start_beat"], run["end_beat"])
        for run in markers
    ] == [("C", 15, 17), ("C", 17, 20), ("D", 20, 32)]
    assert content.count("[C]") == 2


def test_held_chord_ownership_transfers_without_overlapping_later_row():
    beat_times = [float(index) for index in range(48)]
    beat_chords = ["C"] * 48
    lines = (
        TimedLyricLine(0, "first"),
        TimedLyricLine(16, "middle"),
        TimedLyricLine(32, "later"),
    )

    rows = align_lyrics(
        lines,
        beat_times=beat_times,
        beat_numbers=[index % 4 + 1 for index in range(48)],
        meter=4,
        beat_chords=beat_chords,
    )
    content = render_chordpro(LyricsRecord(1, "T", "A", None, 48, lines), rows)
    parsed = parse_chordpro(content)
    markers = [
        run
        for block in parsed["blocks"] if block["type"] == "line"
        for run in block["runs"] if "start_beat" in run
    ]
    ranges = [(run["start_beat"], run["end_beat"]) for run in markers]

    assert ranges == [(0, 16), (16, 32), (32, 48)]
    assert all(0 <= start < end <= len(beat_times) for start, end in ranges)
    assert ranges == sorted(ranges)
    assert all(
        end <= next_start
        for (_, end), (next_start, _) in zip(ranges, ranges[1:], strict=False)
    )
    assert all(
        sum(start <= beat < end for start, end in ranges) <= 1
        for beat in range(len(beat_times))
    )
    assert next(
        run for run in markers
        if run["start_beat"] <= 32 < run["end_beat"]
    )["lyric"] == "later"


def test_all_changes_survive_a_contiguous_lyrics_row_boundary():
    beat_times = [float(index) for index in range(32)]
    beat_chords = (
        ["N"] * 15
        + ["C"]
        + ["Am"] * 2
        + ["F"] * 2
        + ["G"] * 12
    )
    lines = (TimedLyricLine(15, "first line"), TimedLyricLine(17, "second line"))

    rows = align_lyrics(
        lines,
        beat_times=beat_times,
        beat_numbers=[index % 4 + 1 for index in range(32)],
        meter=4,
        beat_chords=beat_chords,
    )
    content = render_chordpro(LyricsRecord(1, "T", "A", None, 32, lines), rows)
    parsed = parse_chordpro(content)
    markers = [
        run
        for block in parsed["blocks"] if block["type"] == "line"
        for run in block["runs"] if run["chord"]
    ]

    assert [
        (run["chord"], run["start_beat"])
        for run in markers
    ] == [("C", 15), ("Am", 16), ("Am", 17), ("F", 18), ("G", 20)]
    assert [
        next(
            run["chord"]
            for run in markers
            if run["start_beat"] <= beat < run["end_beat"]
        )
        for beat in (15, 16, 18, 20)
    ] == ["C", "Am", "F", "G"]


def test_final_marker_ends_at_chord_run_when_mapped_coverage_continues():
    beat_times = [float(index) for index in range(32)]
    lines = (TimedLyricLine(20, "last line"),)

    rows = align_lyrics(
        lines,
        beat_times=beat_times,
        beat_numbers=[index % 4 + 1 for index in range(32)],
        meter=4,
        beat_chords=["N"] * 20 + ["C"] * 4 + ["N"] * 8,
    )
    content = render_chordpro(LyricsRecord(1, "T", "A", None, 32, lines), rows)
    parsed = parse_chordpro(content)
    markers = [
        run
        for block in parsed["blocks"] if block["type"] == "line"
        for run in block["runs"] if run["chord"]
    ]

    assert [
        (run["chord"], run["start_beat"], run["end_beat"])
        for run in markers
    ] == [("C", 20, 24)]


def test_each_timed_lyric_retains_its_own_rendered_row():
    beats = [float(index) for index in range(16)]
    numbers = [index % 4 + 1 for index in range(16)]
    sparse = align_lyrics(
        (TimedLyricLine(0, "one"), TimedLyricLine(12, "two")),
        beat_times=beats,
        beat_numbers=numbers,
        meter=4,
        beat_chords=["C"] * 16,
    )
    assert [(row.measure_start, row.measure_count) for row in sparse] == [
        (0, 1),
        (3, 1),
    ]

    dense = align_lyrics(
        (TimedLyricLine(0, "x" * 121), TimedLyricLine(12, "two")),
        beat_times=beats,
        beat_numbers=numbers,
        meter=4,
        beat_chords=["C"] * 16,
    )
    assert [(row.measure_start, row.measure_count) for row in dense] == [
        (0, 1),
        (3, 1),
    ]


def test_repeated_chords_are_suppressed_and_output_is_deterministic_and_escaped():
    lines = (TimedLyricLine(0, r"a[b] {c} \\ d"), TimedLyricLine(2, "next"))
    kwargs = {
        "beat_times": [0.0, 1.0, 2.0, 3.0],
        "beat_numbers": [1, 2, 3, 4],
        "meter": 4,
        "beat_chords": ["C", "C", "G", "G"],
    }
    first = align_lyrics(lines, **kwargs)
    second = align_lyrics(lines, **kwargs)
    assert first == second
    record = LyricsRecord(1, "T{itle}", "A[rtist]", None, 4, lines)
    content = render_chordpro(record, first, search_hint=" exact {tag} \\")
    # Chord markers stay ordinary ChordPro names; beat mapping is a hidden
    # custom directive, never a suffix inside the marker.
    assert "[C]" in content
    assert "[G]" in content
    assert "[C@" not in content
    assert "[G@" not in content
    assert "{x_chordflask_line: 0,2}" in content
    assert "{x_chordflask_beats: 0}" in content
    assert "{x_chordflask_line: 2,4}" in content
    assert "{x_chordflask_beats: 2}" in content
    parsed = parse_chordpro(content)
    assert parsed["metadata"] == {"title": "T{itle}", "artist": "A[rtist]"}
    visible = "".join(
        run["lyric"] for block in parsed["blocks"] if block["type"] == "line" for run in block["runs"]
    )
    assert visible == r"a[b] {c} \\ dnext"
    assert "exact" not in visible
    assert "T\\{itle\\}" not in visible
    assert "x_chordflask" not in visible
    assert [
        (run["chord"], run["start_beat"], run["end_beat"])
        for block in parsed["blocks"] if block["type"] == "line"
        for run in block["runs"] if run["chord"]
    ] == [("C", 0, 2), ("G", 2, 4)]


def test_marker_metadata_uses_musical_position_for_repeated_chord_names():
    lines = (TimedLyricLine(0, "abcdef"), TimedLyricLine(3, "ghijkl"))
    kwargs = {
        "beat_times": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
        "beat_numbers": [1, 2, 3, 4, 1, 2],
        "meter": 4,
        "beat_chords": ["Am", "G", "Am", "G", "Am", "G"],
    }
    rows = align_lyrics(lines, **kwargs)

    content = render_chordpro(LyricsRecord(1, "T", "A", None, 6, lines), rows)
    parsed = parse_chordpro(content)
    chord_runs = [
        (run["chord"], run["start_beat"])
        for block in parsed["blocks"] if block["type"] == "line"
        for run in block["runs"] if run["chord"]
    ]
    # The two "Am" markers and the two "G" markers are distinct events.
    assert chord_runs == [
        ("Am", 0), ("G", 1), ("Am", 2), ("G", 3), ("Am", 4), ("G", 5),
    ]
    visible = "".join(
        run["lyric"] for block in parsed["blocks"] if block["type"] == "line"
        for run in block["runs"]
    )
    assert visible == "abcdefghijkl"
    assert "@" not in visible


def test_close_to_me_pattern_preserves_lines_and_skips_timed_whitespace():
    beat_times = [0.139319728 + index * 0.65015873 for index in range(314)]
    lines = (
        TimedLyricLine(42.53, "I've waited hours for this"),
        TimedLyricLine(44.83, "I've made myself so sick"),
        TimedLyricLine(47.38, "I wish I'd stayed asleep today"),
        TimedLyricLine(63.54, " "),
        TimedLyricLine(73.56, "Just try to see in the dark"),
    )
    rows = align_lyrics(
        lines,
        beat_times=beat_times,
        beat_numbers=[index % 4 + 1 for index in range(len(beat_times))],
        meter=4,
        beat_chords=["C"] * len(beat_times),
    )
    content = render_chordpro(LyricsRecord(1, "T", "A", None, 203, lines), rows)
    blocks = [
        block for block in parse_chordpro(content)["blocks"]
        if block["type"] == "line"
    ]

    assert [
        "".join(run["lyric"] for run in block["runs"])
        for block in blocks
    ] == [line.text for line in lines if line.text.strip()]
    starts = [block["line_start_beat"] for block in blocks]
    assert starts == [
        beat_at_or_after_index(line.timestamp, beat_times)
        for line in lines if line.text.strip()
    ]
    assert len(set(starts)) == len(starts)
    assert [
        next(run["start_beat"] for run in block["runs"] if run["chord"])
        for block in blocks
    ] == starts
    assert all(
        next(run["chord"] for run in block["runs"] if run["chord"]) == "C"
        for block in blocks
    )


def test_generated_short_lines_own_their_continuing_and_changed_chords():
    lines = (
        TimedLyricLine(0, "I've waited hours for this"),
        TimedLyricLine(3, "So sick"),
        TimedLyricLine(6, "I wish I'd stayed asleep today"),
    )
    beat_chords = ["Abm", "Abm", "Gb6", "Gb6", "E7", "B", "B", "B", "Abm"]
    rows = align_lyrics(
        lines,
        beat_times=[float(index) for index in range(len(beat_chords))],
        beat_numbers=[index % 4 + 1 for index in range(len(beat_chords))],
        meter=4,
        beat_chords=beat_chords,
    )
    content = render_chordpro(LyricsRecord(1, "T", "A", None, 9, lines), rows)
    blocks = [
        block for block in parse_chordpro(content)["blocks"]
        if block["type"] == "line"
    ]

    assert [
        "".join(run["lyric"] for run in block["runs"])
        for block in blocks
    ] == [line.text for line in lines]
    assert [
        [run["chord"] for run in block["runs"] if run["chord"]]
        for block in blocks
    ] == [["Abm", "Gb6"], ["Gb6", "E7", "B"], ["B", "Abm"]]
    assert [
        (block["line_start_beat"], block["line_end_beat"])
        for block in blocks
    ] == [(0, 3), (3, 6), (6, 9)]
    assert [
        next(run["start_beat"] for run in block["runs"] if run["chord"])
        for block in blocks
    ] == [0, 3, 6]


def test_interpolated_markers_snap_to_word_boundaries():
    lines = (
        TimedLyricLine(0, "alpha bravo charlie"),
        TimedLyricLine(10, "next line"),
    )
    rows = align_lyrics(
        lines,
        beat_times=[0.0, 2.0, 5.0, 8.0, 10.0, 11.0],
        beat_numbers=[1, 2, 3, 4, 1, 2],
        meter=4,
        beat_chords=["C", "G", "Am", "F", "C", "C"],
    )

    offset = 0
    marker_offsets = []
    for run in rows[0].runs:
        if run.chord:
            marker_offsets.append(offset)
        offset += len(run.lyric)
    text = lines[0].text
    assert marker_offsets == [0, 5, 11, 12]
    assert all(
        position in {0, len(text)}
        or text[position - 1].isspace()
        or text[position].isspace()
        for position in marker_offsets
    )


def test_instrumental_gap_is_unmapped_and_sync_resumes_at_next_line():
    # One lyric line, then a long constant-chord instrumental span, then a
    # second lyric line. Generated line coverage is capped at four measures, so
    # the gap is not mapped to the previous line's chord marker.
    beat_times = [index * 0.5 for index in range(100)]
    beat_numbers = [index % 4 + 1 for index in range(100)]
    beat_chords = ["C"] * 90 + ["G"] * 10
    lines = (TimedLyricLine(0.0, "line one"), TimedLyricLine(42.0, "line two"))

    rows = align_lyrics(
        lines,
        beat_times=beat_times,
        beat_numbers=beat_numbers,
        meter=4,
        beat_chords=beat_chords,
    )
    assert rows[0].end_beat == 16
    content = render_chordpro(LyricsRecord(1, "T", "A", None, 50, lines), rows)

    assert "[C@0]" not in content
    assert "[C]" in content and "[G]" in content
    assert "{x_chordflask_beats: 0}" in content
    assert "{x_chordflask_end: 16}" in content

    parsed = parse_chordpro(content)
    line_ranges = [
        (block["line_start_beat"], block["line_end_beat"])
        for block in parsed["blocks"] if block["type"] == "line"
    ]
    assert line_ranges == [(0, 16), (84, 100)]

    def active(beat):
        # Mirrors the browser rule: the mapped range must contain the beat.
        return next((start for start, end in line_ranges if start <= beat < end), None)

    assert active(0) == 0
    assert active(70) is None  # unmapped instrumental gap: highlight clears
    assert active(84) == 84    # seek/resume at the next mapped line
    assert active(90) == 84
