"""Derived notation via music21; raw performance events are never modified."""

import math
from pathlib import Path
import xml.etree.ElementTree as ET

from .timing import BeatGrid

QUANTIZATION = {"mixed": (4, 3), "binary": (4,)}


class NoteTimeError(ValueError):
    """A note has unusable original timing data."""


def validate_notes(payload):
    if not isinstance(payload, dict) or set(payload) != {"notes", "controllers"}:
        raise ValueError("Invalid original note record")
    for index, row in enumerate(payload["notes"]):
        if set(row) != {"pitch", "velocity", "start", "end"}:
            raise ValueError("Invalid original note fields")
        if type(row["pitch"]) is not int or not 0 <= row["pitch"] <= 127:
            raise ValueError("Invalid MIDI pitch")
        if type(row["velocity"]) is not int or not 1 <= row["velocity"] <= 127:
            raise ValueError("Invalid MIDI velocity")
        if any(type(row[k]) not in (int, float) or not math.isfinite(row[k]) for k in ("start", "end")):
            raise NoteTimeError(
                f"note[{index}] pitch={row['pitch']} has non-finite or non-numeric times "
                f"start={row['start']!r}, end={row['end']!r}"
            )
        if not 0 <= row["start"] < row["end"]:
            raise NoteTimeError(
                f"note[{index}] pitch={row['pitch']} has invalid interval "
                f"start={row['start']!r}, end={row['end']!r}; require 0 <= start < end"
            )
    for row in payload["controllers"]:
        if set(row) != {"number", "value", "time"}:
            raise ValueError("Invalid original controller fields")
        if any(type(row[k]) is not int or not 0 <= row[k] <= 127 for k in ("number", "value")):
            raise ValueError("Invalid MIDI controller")
        if type(row["time"]) not in (int, float) or not math.isfinite(row["time"]) or row["time"] < 0:
            raise ValueError("Invalid MIDI controller time")


def _reuse_recent_voice(measure, capacity):
    voices = list(measure.voices)
    if not voices:
        return
    # Verovio misplaces existing unbracketed tuplets. Reassigning their voices
    # changes which notes are affected; keep these measures intact for now.
    if any(item.duration.tuplets for item in measure.recurse().notesAndRests):
        return
    events = []
    for voice in voices:
        for item in list(voice.notesAndRests):
            if not item.isRest:
                events.append((item.offset, item))
            voice.remove(item)
    events.sort(key=lambda event: event[0])
    for offset, item in events:
        available = [voice for voice in voices if voice.highestTime <= offset]
        # Continue in the most recently active free voice, including when a
        # sustained note and the running figure finish at the same instant.
        voice = max(available, key=lambda voice: (voice.highestTime, voice.highestOffset))
        voice.insert(offset, item)
    for voice in voices:
        voice.makeRests(inPlace=True, fillGaps=True, refStreamOrTimeRange=(0, capacity))


def build_score(payload, grid: BeatGrid, *, quantization="mixed"):
    from music21 import chord, clef, layout, metadata, meter, note, stream, tempo

    validate_notes(payload)
    divisors = QUANTIZATION[quantization]
    score = stream.Score(id="score")
    # No work title is supplied by the transcription inputs. An explicit empty
    # movement name suppresses music21's default "Music21 Fragment" title.
    score.metadata = metadata.Metadata(movementName="")
    hands = [stream.PartStaff(id="right"), stream.PartStaff(id="left")]
    for part, key in zip(hands, (clef.TrebleClef(), clef.BassClef()), strict=True):
        part.insert(0, key)
        part.insert(0, meter.TimeSignature(f"{grid.meter}/4"))
        part.partName = "Right hand" if part.id == "right" else "Left hand"

    omitted = clipped = 0
    for row in sorted(payload["notes"], key=lambda n: (n["start"], n["pitch"], n["end"], n["velocity"])):
        start = max(row["start"], grid.times[0])
        end = min(row["end"], grid.times[-1])
        if start >= end:
            omitted += 1
            continue
        clipped += int(start != row["start"] or end != row["end"])
        begin, finish = grid.to_quarter(start), grid.to_quarter(end)
        item = note.Note(row["pitch"], quarterLength=finish - begin)
        if item.pitch.accidental is not None and item.pitch.accidental.alter == 0:
            item.pitch.accidental = None
        item.volume.velocity = row["velocity"]
        hands[0 if row["pitch"] >= 60 else 1].insert(begin, item)

    # Keep exact interval tempi; repeated equal values need no new direction.
    previous_bpm = None
    for index, (start, end) in enumerate(zip(grid.times, grid.times[1:], strict=False)):
        bpm = 60 / (end - start)
        if bpm == previous_bpm:
            continue
        # numberSounding exports <sound tempo> without a printed <metronome>.
        mark = (tempo.MetronomeMark(number=round(bpm), numberSounding=bpm) if index == 0
                else tempo.MetronomeMark(numberSounding=bpm))
        hands[0].insert(grid.first_quarter + index, mark)
        previous_bpm = bpm

    expected = grid.measures()
    for part in hands:
        part.quantize(divisors, inPlace=True, processOffsets=True, processDurations=True)
        # Quantization is bounded by the observed end, avoiding an extra bar.
        for item in part.recurse().notes:
            if item.offset >= grid.last_quarter:
                part.remove(item)
            elif item.offset + item.duration.quarterLength > grid.last_quarter:
                item.duration.quarterLength = grid.last_quarter - item.offset
        simultaneous = {}
        for item in part.notes:
            simultaneous.setdefault((item.offset, item.duration.quarterLength), []).append(item)
        for (offset, _), notes in simultaneous.items():
            # Preserve repeated identical pitches as separate events/voices.
            if len(notes) > 1 and len({n.pitch.midi for n in notes}) == len(notes):
                for item in notes:
                    part.remove(item)
                part.insert(offset, chord.Chord(notes))
        part.makeVoices(inPlace=True, fillGaps=False)
        part.makeRests(inPlace=True, fillGaps=True, refStreamOrTimeRange=(0, grid.last_quarter))
        part.makeMeasures(inPlace=True)
        part.makeTies(inPlace=True)
        part.makeRests(inPlace=True, fillGaps=True)
        measures = list(part.getElementsByClass(stream.Measure))
        if len(measures) != len(expected):
            raise ValueError("music21 measure count differs from QM measure map")
        if grid.first_quarter:
            first = measures[0]
            # Remove the artificial leading silence used for full-bar construction.
            for container in [first, *first.getElementsByClass(stream.Voice)]:
                for item in list(container.notesAndRests):
                    if item.offset < grid.first_quarter:
                        if not item.isRest:
                            raise ValueError("Quantization crossed the pickup boundary")
                        finish = item.offset + item.duration.quarterLength
                        if finish <= grid.first_quarter:
                            container.remove(item)
                        else:
                            item.duration.quarterLength = finish - grid.first_quarter
                            item.offset = 0
                    else:
                        item.offset -= grid.first_quarter
            # Tempo positions also follow the shortened pickup.
            for item in list(first.getElementsByClass(tempo.MetronomeMark)):
                item.offset = max(0, item.offset - grid.first_quarter)
            first.paddingLeft = grid.first_quarter
        for measure, mapping in zip(measures, expected, strict=True):
            measure.number = mapping["number"]
            measure.id = f"{part.id}-measure-{measure.number}"
        remainder = grid.last_quarter % grid.meter
        if remainder:
            measures[-1].paddingRight = grid.meter - remainder
            last = measures[-1]
            capacity = expected[-1]["end_quarter"] - expected[-1]["start_quarter"]
            for container in [last, *last.getElementsByClass(stream.Voice)]:
                for item in list(container.notesAndRests):
                    if item.offset >= capacity:
                        container.remove(item)
                    elif item.offset + item.duration.quarterLength > capacity:
                        item.duration.quarterLength = capacity - item.offset
        for measure, mapping in zip(measures, expected, strict=True):
            _reuse_recent_voice(measure, mapping["end_quarter"] - mapping["start_quarter"])
            voices = list(measure.voices)
            retained = [voice for voice in voices if voice.notes] or voices[:1]
            for voice in voices:
                if voice not in retained:
                    measure.remove(voice)
            measure.flattenUnnecessaryVoices(inPlace=True)
            for number, voice in enumerate(measure.voices, start=1):
                voice.id = number
        part = part.splitAtDurations(recurse=True)[0]
        part.makeAccidentals(inPlace=True)
        part.makeBeams(inPlace=True)
        score.insert(0, part)
    score.insert(0, layout.StaffGroup(list(score.parts), symbol="brace", barTogether=True))
    return score, {"rhythm": grid.as_dict(), "measures": expected,
                   "notation_coverage": {"omitted_notes": omitted, "clipped_notes": clipped}}


def write_notation(payload, grid, destination: Path, *, quantization="mixed"):
    score, mapping = build_score(payload, grid, quantization=quantization)
    score.write("musicxml", fp=destination, makeNotation=False)
    validate_musicxml(destination.read_bytes(), len(mapping["measures"]))
    return mapping


def validate_musicxml(content, measure_count):
    if len(content) > 16 * 1024 * 1024:
        raise ValueError("MusicXML exceeds size limit")
    # music21 writes its standard external MusicXML DTD. ElementTree never
    # fetches it; reject entities and every other DTD declaration.
    declaration = (b'<!DOCTYPE score-partwise  PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
                   b'"http://www.musicxml.org/dtds/partwise.dtd">')
    cleaned = content.replace(declaration, b"")
    if b"<!DOCTYPE" in cleaned.upper() or b"<!ENTITY" in cleaned.upper():
        raise ValueError("Unsafe MusicXML DTD/entities")
    root = ET.fromstring(cleaned)
    if root.tag != "score-partwise":
        raise ValueError("Expected partwise MusicXML")
    parts = root.findall("part")
    if len(parts) != 1 or root.findtext("part/measure/attributes/staves") != "2":
        raise ValueError("Expected a two-staff piano MusicXML part")
    if any(len(part.findall("measure")) != measure_count for part in parts):
        raise ValueError("MusicXML and measure map counts differ")
    return root
