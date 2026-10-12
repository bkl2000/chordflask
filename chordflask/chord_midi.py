"""Beat-synchronous MIDI export of an already transposed display snapshot."""

import math
from functools import lru_cache

from music21 import exceptions21, harmony, midi

from .chord_markdown import _usable_beat_numbers
from .chordutils import fix_chord_label

TICKS_PER_BEAT = 9600


@lru_cache(maxsize=512)
def _voicing(label):
    """A fixed piano register: bass C3–B3, close-position harmony from C4."""
    if not isinstance(label, str):
        return ()
    label = label.strip().replace("♭", "b").replace("♯", "#")
    label = label.replace("°", "dim").replace("ø7", "m7b5").replace("ø", "m7b5").replace("Δ", "maj")
    if label in {"", "N", "X"}:
        return ()
    try:
        symbol = harmony.ChordSymbol(fix_chord_label(label))
        root = symbol.root().pitchClass
        bass = symbol.bass().pitchClass
        # Retain extensions above the root instead of folding ninths into seconds.
        root_pitch = symbol.root().midi
        upper = {60 + root + pitch.midi - root_pitch for pitch in symbol.pitches}
        # ChordSymbol may place inversion tones below the root. Lift those into
        # the root's octave; the explicit bass below preserves slash inversions.
        upper = {value + 12 if value < 60 + root else value for value in upper}
        return tuple(sorted({48 + bass, *upper}))
    except (ValueError, TypeError, AttributeError, exceptions21.Music21Exception):
        return ()


def generate_chord_midi(snapshot):
    """Return MIDI bytes from display ``beats`` and audio ``beat_times``.

    Each analyzed beat advances one MIDI quarter. Tempo changes reproduce its
    actual interval, with microsecond rounding corrected at every boundary.
    Invalid/non-increasing times fail instead of inventing a replacement grid.
    The final chord lasts one more interval (120 BPM for a single beat).
    No display offset or additional chord smoothing is applied.
    """
    beats = list(snapshot["beats"])
    times = [float(value) for value in snapshot["beat_times"]]
    if not beats or len(beats) != len(times):
        raise ValueError("MIDI export requires one timestamp per displayed beat")
    if any(not math.isfinite(value) or value < 0 for value in times):
        raise ValueError("MIDI beat timestamps must be finite and non-negative")
    intervals = [right - left for left, right in zip(times, times[1:], strict=False)]
    if any(value <= 0 for value in intervals):
        raise ValueError("MIDI beat timestamps must be strictly increasing")
    final_interval = intervals[-1] if intervals else 0.5
    times.append(times[-1] + final_interval)
    width = snapshot.get("meter")
    if width is None:
        width = 4
    if isinstance(width, bool) or not isinstance(width, int) or not 1 <= width <= 255:
        raise ValueError("Invalid MIDI meter")
    numbers = [number for number, _ in beats]
    phase = numbers[0] - 1 if _usable_beat_numbers(numbers, width) else 0

    # Choose silent whole bars nearest the first interval's extrapolated grid,
    # retaining the analyzed beat phase. Pre-roll tempo maps the start exactly.
    first = 0
    if times[0] > 0:
        initial_interval = intervals[0] if intervals else final_interval
        first = phase + width * max(0, round((times[0] / initial_interval - phase) / width))
        if first == 0:
            first = width

    midi_file = midi.MidiFile()
    midi_file.ticksPerQuarterNote = TICKS_PER_BEAT
    conductor = midi.MidiTrack(0)
    piano = midi.MidiTrack(1)
    midi_file.tracks = [conductor, piano]
    events = {0: [], 1: []}

    def meta(tick, kind, data):
        event = midi.MidiEvent(conductor, type=kind)
        event.data = data
        events[0].append((tick, event))

    # With a pickup at audio time zero, a short initial measure avoids adding
    # audible silence. Restore the real meter at the first analyzed downbeat.
    pickup = width - phase if first == 0 and phase else width
    meta(0, midi.MetaEvents.TIME_SIGNATURE, bytes([pickup, 2, 24, 8]))
    if pickup != width and pickup <= len(beats):
        meta(pickup * TICKS_PER_BEAT, midi.MetaEvents.TIME_SIGNATURE, bytes([width, 2, 24, 8]))
    program = midi.MidiEvent(piano, type=midi.ChannelVoiceMessages.PROGRAM_CHANGE)
    program.data = 0  # GM Acoustic Grand Piano
    events[1].append((0, program))

    elapsed = 0.0

    def tempo_to(tick, target, quarters):
        nonlocal elapsed
        microseconds = round((target - elapsed) * 1_000_000 / quarters)
        if not 1 <= microseconds <= 0xFFFFFF:
            raise ValueError("Beat interval is outside the MIDI tempo range")
        meta(tick, midi.MetaEvents.SET_TEMPO, microseconds.to_bytes(3, "big"))
        elapsed += microseconds * quarters / 1_000_000

    if first:
        tempo_to(0, times[0], first)
    for index in range(len(beats)):
        tempo_to((first + index) * TICKS_PER_BEAT, times[index + 1], 1)

    previous = ()
    for index in range(len(beats) + 1):
        current = _voicing(beats[index][1]) if index < len(beats) else ()
        if current == previous:
            continue
        tick = (first + index) * TICKS_PER_BEAT
        for pitches, kind, velocity in (
            (previous, midi.ChannelVoiceMessages.NOTE_OFF, 0),
            (current, midi.ChannelVoiceMessages.NOTE_ON, 76),
        ):
            for pitch in pitches:
                event = midi.MidiEvent(piano, type=kind)
                event.pitch = pitch
                event.velocity = velocity
                events[1].append((tick, event))
        previous = current

    end = (first + len(beats)) * TICKS_PER_BEAT
    for track in midi_file.tracks:
        ordered = sorted(events[track.index], key=lambda item: item[0])
        ending = midi.MidiEvent(track, type=midi.MetaEvents.END_OF_TRACK)
        ending.data = b""
        ordered.append((end, ending))
        previous_tick = 0
        for tick, event in ordered:
            track.events.extend([midi.DeltaTime(track, time=tick - previous_tick), event])
            previous_tick = tick
    return midi_file.writestr()
