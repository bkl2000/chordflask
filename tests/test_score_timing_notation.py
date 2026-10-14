import copy
from collections import Counter, defaultdict
from fractions import Fraction
import json
import math
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import pytest

from chordflask_score.notation import NoteTimeError, build_score, validate_notes, write_notation
from chordflask_score.timing import BeatGrid


def grid(numbers=(1, 2, 3, 4, 1, 2, 3, 4, 1), meter=4, times=None):
    return BeatGrid.from_track({"beat_times": times or [i * .5 for i in range(len(numbers))],
                                "beat_numbers": list(numbers), "meter_signature": meter})


def event(pitch=60, start=0, end=1):
    return {"pitch": pitch, "velocity": 80, "start": start, "end": end}


def test_valid_note_times_include_small_positive_tick_boundary():
    smallest_positive = math.nextafter(0.0, 1.0)
    validate_notes({"notes": [event(start=0.0, end=smallest_positive)], "controllers": []})


@pytest.mark.parametrize(("start", "end", "reason"), [
    (-.001, 1, "require 0 <= start < end"),
    (1, 1, "require 0 <= start < end"),
    (1, .999, "require 0 <= start < end"),
    (float("nan"), 1, "non-finite or non-numeric"),
    (0, float("inf"), "non-finite or non-numeric"),
])
def test_invalid_note_times_report_note_and_values(start, end, reason):
    with pytest.raises(NoteTimeError) as caught:
        validate_notes({"notes": [event(61, start, end)], "controllers": []})
    message = str(caught.value)
    assert "note[0] pitch=61" in message
    assert f"start={start!r}, end={end!r}" in message
    assert reason in message


def test_piecewise_tempo_and_boundary_inverse():
    g = grid(times=[0, .5, 1, 1.5, 2, 3, 4, 5, 6])
    assert g.to_quarter(2.5) == 4.5
    assert g.to_quarter(.25) == .5
    assert g.to_seconds(4) == 2
    assert [(m["start_seconds"], m["end_seconds"]) for m in g.measures()] == [(0, 2), (2, 6)]
    for time in g.times:
        assert g.to_seconds(g.to_quarter(time)) == time
    with pytest.raises(ValueError, match="outside"):
        g.to_quarter(-.1)


@pytest.mark.parametrize("change", [
    {"beat_times": []}, {"beat_times": [0, 0, 1]}, {"beat_times": [0, float('nan'), 1]},
    {"beat_times": [0, 1, .5]}, {"beat_numbers": [1, 3, 4]},
    {"beat_numbers": [1, 2]}, {"beat_numbers": [1, 2, 5]},
    {"meter_signature": None}, {"meter_signature": True},
])
def test_invalid_rhythm_never_gets_a_replacement_grid(change):
    track = {"beat_times": [0, .5, 1], "beat_numbers": [1, 2, 3], "meter_signature": 4}
    track.update(change)
    with pytest.raises(ValueError):
        BeatGrid.from_track(track)


def parsed_shape(path):
    from music21 import converter, stream
    score = converter.parse(path)
    return [
        [(m.number, float(m.duration.quarterLength), float(m.paddingLeft),
          [(float(n.getOffsetInHierarchy(m)), float(n.duration.quarterLength),
            tuple(p.midi for p in n.pitches), n.tie.type if n.tie else None)
           for n in m.recurse().notes])
         for m in part.getElementsByClass(stream.Measure)]
        for part in score.parts
    ]


@pytest.mark.parametrize(("numbers", "meter", "duration"), [
    ((1, 2, 3, 4, 1, 2, 3, 4, 1), 4, 4),
    ((3, 4, 1, 2, 3, 4, 1), 4, 2),
    ((1, 2, 3, 1, 2, 3, 1), 3, 3),
])
def test_real_notation_measure_counts_pickup_and_clefs(tmp_path, numbers, meter, duration):
    from music21 import clef, converter
    g = grid(numbers, meter)
    path = tmp_path / "score.xml"
    mapping = write_notation({"notes": [event(60, 0, 2.4), event(59, .5, 1)], "controllers": []}, g, path)
    shape = parsed_shape(path)
    assert len(shape) == 2
    assert all(len(part) == len(mapping["measures"]) for part in shape)
    assert shape[0][0][1] == duration
    score = converter.parse(path)
    assert isinstance(score.parts[0].recurse().getElementsByClass(clef.Clef).first(), clef.TrebleClef)
    assert isinstance(score.parts[1].recurse().getElementsByClass(clef.Clef).first(), clef.BassClef)
    assert all(p.midi == 60 for n in score.parts[0].recurse().notes for p in n.pitches)
    assert all(p.midi == 59 for n in score.parts[1].recurse().notes for p in n.pitches)


def test_overlap_triplets_and_parsed_determinism_preserve_original(tmp_path):
    payload = {"notes": [event(60, 0, 1), event(60, .5, 1.5), event(59, 1/6, .5)], "controllers": []}
    original = copy.deepcopy(payload)
    first, second = tmp_path / "a.xml", tmp_path / "b.xml"
    write_notation(payload, grid(), first)
    write_notation(payload, grid(), second)
    assert payload == original
    assert parsed_shape(first) == parsed_shape(second)
    from music21 import converter
    notes = list(converter.parse(first).parts[0].recurse().notes)
    assert len(notes) == 2
    assert [float(n.duration.quarterLength) for n in notes] == [2, 2]


def test_partial_final_bar_empty_hand_and_coverage(tmp_path):
    g = grid((3, 4, 1, 2, 3, 4, 1, 2, 3), times=[i*.5+1 for i in range(9)])
    payload = {"notes": [event(60, 0, .5), event(60, .5, 2)], "controllers": []}
    path = tmp_path / "score.xml"
    mapping = write_notation(payload, g, path)
    assert mapping["notation_coverage"] == {"omitted_notes": 1, "clipped_notes": 1}
    assert [m[1] for m in parsed_shape(path)[0]] == [2, 4, 2]
    assert mapping["measures"][0]["start_seconds"] == 1
    assert mapping["measures"][-1]["end_seconds"] == 5


def test_tempo_marks_come_from_qm_intervals(tmp_path):
    from music21 import converter, tempo
    g = grid(times=[0, .5, 1, 1.5, 2, 3, 4, 5, 6])
    path = tmp_path / "score.xml"
    write_notation({"notes": [], "controllers": []}, g, path)
    marks = converter.parse(path).parts[0].flatten().getElementsByClass(tempo.MetronomeMark)
    assert [(float(mark.offset), mark.getQuarterBPM()) for mark in marks] == [(0, 120), (4, 60)]


def test_tempo_changes_preserve_all_beat_times_without_redundant_labels(tmp_path):
    import xml.etree.ElementTree as ET
    from music21 import converter
    g = grid(times=[0, .5, 1, 1.75, 2.25, 3.25, 4.25, 4.75, 5.25])
    path = tmp_path / "score.xml"
    mapping = write_notation({"notes": [], "controllers": []}, g, path)
    root = ET.parse(path).getroot()
    assert len(root.findall(".//metronome")) == 1
    assert len(root.findall(".//sound[@tempo]")) == 5
    score = converter.parse(path)
    boundaries = score.metronomeMarkBoundaries()
    for i, seconds in enumerate(g.times):
        elapsed = sum(mark.durationToSeconds(min(end, i) - start)
                      for start, end, mark in boundaries if start < i)
        assert elapsed == pytest.approx(seconds, abs=1e-12)
    assert mapping["measures"] == g.measures()


def test_four_note_chords_and_rest_only_voices_are_reduced(tmp_path):
    from music21 import converter, stream
    g = grid(tuple(i % 4 + 1 for i in range(13)))
    payload = {"notes": [event(pitch, 0, .5) for pitch in (60, 64, 67, 72)] + [event(60, 2, 2.5)],
               "controllers": []}
    original = copy.deepcopy(payload)
    path = tmp_path / "score.xml"
    mapping = write_notation(payload, g, path)
    measures = list(converter.parse(path).parts[0].getElementsByClass(stream.Measure))
    assert len(measures) == len(mapping["measures"]) == 3
    assert tuple(p.midi for p in measures[0].recurse().notes.first().pitches) == (60, 64, 67, 72)
    assert all(not m.voices for m in measures)
    assert [len(m.recurse().getElementsByClass("Rest")) for m in measures] == [1, 1, 1]
    assert payload == original


def test_different_durations_and_identical_pitch_events_remain_distinct(tmp_path):
    from music21 import converter
    payload = {"notes": [event(60, 0, 1), event(64, 0, .5), event(60, 0, 1)], "controllers": []}
    path = tmp_path / "score.xml"
    write_notation(payload, grid(), path)
    notes = converter.parse(path).parts[0].recurse().notes
    assert sorted((tuple(p.midi for p in n.pitches), float(n.duration.quarterLength)) for n in notes) == [
        ((60,), 2), ((60,), 2), ((64,), 1)]


def test_midi_naturals_only_render_when_musically_required(tmp_path):
    payload = {
        "notes": [
            event(69, 0, .4), event(69, .5, .9),
            event(66, 1, 1.4), event(65, 1.5, 1.9),
            event(70, 2, 2.4), event(71, 2.5, 2.9),
        ],
        "controllers": [],
    }
    original = copy.deepcopy(payload)
    output = tmp_path / "score.xml"
    write_notation(payload, grid(), output)
    root = ET.parse(output).getroot()

    assert [node.text for node in root.findall(".//accidental")] == [
        "sharp", "natural", "flat", "natural",
    ]
    assert sorted(int(p.midi) for p in payload_notes(output)) == sorted(
        row["pitch"] for row in payload["notes"]
    )
    assert payload == original


def payload_notes(path):
    from music21 import converter
    return [pitch for item in converter.parse(path).recurse().notes for pitch in item.pitches]


def xml_note_events(path, mapping):
    """Read exact XML durations and join ties, independently of voice renumbering."""
    pitch_classes = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    segments = []
    divisions = 1
    root = ET.parse(path).getroot()
    for measure, row in zip(root.findall("part/measure"), mapping["measures"], strict=True):
        cursor = previous = Fraction(0)
        for child in measure:
            if child.tag == "attributes" and child.findtext("divisions"):
                divisions = int(child.findtext("divisions"))
            elif child.tag in {"backup", "forward"}:
                direction = -1 if child.tag == "backup" else 1
                cursor += direction * Fraction(int(child.findtext("duration")), divisions)
            elif child.tag == "note":
                duration = Fraction(int(child.findtext("duration", "0")), divisions)
                onset = previous if child.find("chord") is not None else cursor
                if child.find("chord") is None:
                    previous = onset
                    cursor += duration
                pitch = child.find("pitch")
                if pitch is None:
                    continue
                midi = (12 * (int(pitch.findtext("octave")) + 1)
                        + pitch_classes[pitch.findtext("step")] + int(pitch.findtext("alter", "0")))
                ties = {tie.get("type") for tie in child.findall("tie")}
                segments.append((row["start_quarter"] + onset, child.findtext("staff", "1"),
                                 midi, duration, "stop" in ties, "start" in ties, child.findtext("voice")))
    pending = defaultdict(list)
    events = []
    for onset, staff, pitch, duration, stop, start, voice in sorted(segments):
        begin, end = onset, onset + duration
        if stop:
            matching = [(i, b, v) for i, (b, e, v) in enumerate(pending[staff, pitch]) if e == onset]
            assert matching, (staff, pitch, onset, "unmatched tie stop")
            # Voice identity disambiguates overlapping repeated pitches. A lone
            # match can change number when an inactive voice is removed.
            matching_voice = [(i, b, v) for i, b, v in matching if v == voice]
            index, begin, _ = (matching_voice or matching)[0]
            pending[staff, pitch].pop(index)
        if start:
            pending[staff, pitch].append((begin, end, voice))
        else:
            events.append((pitch, float(begin), float(end - begin)))
    assert not any(pending.values()), "unfinished ties"
    return sorted(events)


@pytest.mark.parametrize("notes", [
    [event(72, 0, 1), event(74, 1, 2)],  # contiguous monophony
    [event(72, .5, 1), event(74, 1.5, 2)],  # necessary rests
    [event(p, 0, 1) for p in (60, 64, 67)],  # equal-duration chord
    [event(60, 0, 2), event(64, 0, .5), event(65, .5, 1)],  # unequal overlaps
    [event(60, 0, 4)] + [event(72, s, s + .5) for s in (0, .5, 1, 1.5, 2, 2.5, 3, 3.5)],
    [event(60, 0, 1), event(60, 0, 1)],  # duplicate attacks cannot become one chord pitch
    [event(60, 0, 3), event(60, .5, 2.5)],  # overlapping same-pitch ties
    [event(p, s, s + .5) for p, s in ((36, 0), (48, .5), (84, 1), (90, 1.5))],
    [event(p, 0, 1) for p in (57, 60, 64)],  # existing overlapping staff ranges
    [event(66, 0, 1), event(65, 1, 2), event(70, 2, 3), event(71, 3, 4)],
])
def test_notation_preserves_exact_grid_events_including_tied_segments(tmp_path, notes):
    payload = {"notes": notes, "controllers": []}
    original = copy.deepcopy(payload)
    g = grid()
    output = tmp_path / "score.xml"
    mapping = write_notation(payload, g, output)
    # These fixtures already lie on the notation grid. Raw seconds and quarter
    # positions are different units; no raw/quantized time equality is implied.
    expected = sorted((row["pitch"], g.to_quarter(row["start"]),
                       g.to_quarter(row["end"]) - g.to_quarter(row["start"])) for row in notes)
    assert xml_note_events(output, mapping) == expected
    assert mapping["notation_coverage"] == {"omitted_notes": 0, "clipped_notes": 0}
    assert all(int(node.text) > 0 for node in ET.parse(output).findall(".//voice"))
    assert payload == original


def test_running_figure_reuses_recent_voice_after_older_voice_becomes_free(tmp_path):
    from music21 import converter, stream

    notes = [event(60, 0, 1)] + [event(p, s, s + .5) for p, s in
                               ((72, 0), (74, .5), (76, 1), (77, 1.5), (79, 2), (81, 2.5))]
    output = tmp_path / "score.xml"
    mapping = write_notation({"notes": notes, "controllers": []}, grid(), output)
    score = converter.parse(output)
    measures = list(score.parts[0].getElementsByClass(stream.Measure))
    voices = list(measures[0].voices)
    assert [tuple(int(p.midi) for n in v.notes for p in n.pitches) for v in voices] == [
        (60,), (72, 74, 76, 77),
    ]
    assert not measures[1].voices  # only the continuing figure; no idle bass voice
    assert [int(n.pitch.midi) for n in measures[1].notes] == [79, 81]
    assert xml_note_events(output, mapping) == sorted((n["pitch"], n["start"] * 2,
                                                      (n["end"] - n["start"]) * 2) for n in notes)


def test_secondary_voice_retains_necessary_rests_and_empty_bars_have_one_rest():
    from music21 import stream

    notes = [event(60, 0, 1), event(72, .5, 1.5)]
    score, _ = build_score({"notes": notes, "controllers": []}, grid())
    measures = list(score.parts[0].getElementsByClass(stream.Measure))
    assert len(measures[0].voices) == 2
    for voice in measures[0].voices:
        assert sum(n.quarterLength for n in voice.notesAndRests) == 4
        assert all(not r.style.hideObjectOnPrint for r in voice.getElementsByClass("Rest"))
    assert len(list(measures[1].recurse().getElementsByClass("Rest"))) == 1
    assert not measures[1].voices


def test_tuplet_measures_keep_their_existing_voice_assignment():
    from music21 import stream

    notes = [event(60, 0, 1), event(64, 0, 1/6), event(65, 1/6, 1/3),
             event(67, 1/3, .5), event(69, 1, 1.5)]
    score, _ = build_score({"notes": notes, "controllers": []}, grid())
    measure = score.parts[0].getElementsByClass(stream.Measure).first()
    assert [tuple(int(p.midi) for n in v.notes for p in n.pitches) for v in measure.voices] == [
        (60, 69), (64, 65, 67),
    ]


def test_quantized_triplets_and_repeated_pitch_ties_keep_all_events(tmp_path):
    notes = [event(60, 0, 1/6), event(60, 1/6, 1/3), event(60, 1/3, .5),
             event(72, 1.5, 2.5)]
    output = tmp_path / "score.xml"
    mapping = write_notation({"notes": notes, "controllers": []}, grid(), output)
    actual = xml_note_events(output, mapping)
    expected = [(60, 0, 1/3), (60, 1/3, 1/3), (60, 2/3, 1/3), (72, 3, 2)]
    assert Counter(p for p, _, _ in actual) == Counter(n["pitch"] for n in notes)
    for result, reference in zip(actual, expected, strict=True):
        assert result == pytest.approx(reference, abs=1e-6)


@pytest.mark.parametrize(("sharps", "pitch"), [(1, 65), (-1, 71)])
def test_midi_naturals_allow_key_signatures_to_add_required_accidentals(sharps, pitch):
    from music21 import key, stream

    score, _ = build_score({"notes": [event(pitch, 0, .4)], "controllers": []}, grid())
    measure = score.parts[0].getElementsByClass(stream.Measure).first()
    item = measure.recurse().notes.first()
    assert item.pitch.accidental is None
    measure.insert(0, key.KeySignature(sharps))
    measure.makeAccidentals(inPlace=True, overrideStatus=True)
    assert item.pitch.midi == pitch
    assert item.pitch.accidental.name == "natural"
    assert item.pitch.accidental.displayStatus is True


def test_real_verovio_preserves_polyphonic_voice_positions(tmp_path):
    from chordflask_score.runtime import runtime_python

    python = runtime_python()
    if not python.is_file():
        pytest.skip("optional Score runtime is not installed")
    payload = {
        "notes": [event(60, 0, 2), event(62, 2, 4)]
        + [event(64, start, start + .5) for start in (0, .5, 1, 1.5)]
        + [event(65, start, start + .5) for start in (2, 2.5, 3, 3.5)],
        "controllers": [],
    }
    original = copy.deepcopy(payload)
    output = tmp_path / "score.xml"
    write_notation(payload, grid(), output)
    root = ET.parse(output).getroot()
    pitched_voices = [
        {note.findtext("voice") for note in measure.findall("note") if note.find("pitch") is not None}
        for measure in root.findall("part/measure")
    ]
    assert pitched_voices == [{"1", "2"}, {"1", "2"}]

    project_root = Path(__file__).resolve().parents[1]
    code = """
import json
import sys
import verovio

toolkit = verovio.toolkit()
assert toolkit.loadFile(sys.argv[1])
positions = []
for row in toolkit.renderToTimemap():
    for identifier in row.get("on", []):
        values = toolkit.getMIDIValuesForElement(identifier)
        if "pitch" in values:
            positions.append((values["pitch"], row["qstamp"]))
print(json.dumps(sorted(positions)))
"""
    result = subprocess.run(
        [str(python), "-I", "-c", code, str(output)],
        capture_output=True, text=True, timeout=30, cwd=project_root,
    )
    assert result.returncode == 0, result.stderr
    assert "[Warning]" not in result.stderr
    assert json.loads(result.stdout) == [
        [60, 0], [62, 4], [64, 0], [64, 1], [64, 2], [64, 3],
        [65, 4], [65, 5], [65, 6], [65, 7],
    ]
    assert sorted(pitch for pitch, _ in json.loads(result.stdout)) == sorted(
        row["pitch"] for row in payload["notes"]
    )
    assert payload == original


def test_real_verovio_keeps_one_visible_tempo_label(tmp_path):
    from chordflask_score.runtime import runtime_python

    python = runtime_python()
    if not python.is_file():
        pytest.skip("optional Score runtime is not installed")
    root = Path(__file__).resolve().parents[1]
    g = grid(times=[0, .5, 1, 1.75, 2.25, 3.25, 4.25, 4.75, 5.25])
    output = tmp_path / "score.xml"
    mapping = write_notation({"notes": [], "controllers": []}, g, output)
    import json
    map_path = tmp_path / "mapping.json"
    map_path.write_text(json.dumps(mapping))
    code = (f"import sys; sys.path.insert(0, {str(root)!r}); "
            "import json; from pathlib import Path; from chordflask_score.worker import render; "
            "render(Path(sys.argv[1]), Path(sys.argv[2]), json.loads(Path(sys.argv[3]).read_text()))")
    result = subprocess.run([str(python), "-I", "-c", code, str(output), str(tmp_path), str(map_path)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    groups = [node for node in ET.parse(tmp_path / "page-0001.svg").getroot().iter()
              if "tempo" in node.get("class", "").split()]
    # Verovio retains empty tempo groups for sound-only directions; no labels.
    assert len(groups) == 5
    assert sum(bool("".join(group.itertext()).strip()) for group in groups) == 1
