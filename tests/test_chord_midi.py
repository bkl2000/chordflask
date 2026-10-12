"""Check the serialized MIDI, including real-time playback and musical ticks."""

from io import BytesIO

import mido
import pytest

from chordflask.chord_midi import generate_chord_midi


def snapshot(chords, times=None, numbers=None, meter=4):
    return {
        "beats": list(zip(numbers or [i % meter + 1 for i in range(len(chords))], chords, strict=True)),
        "beat_times": times if times is not None else [i / 2 for i in range(len(chords))],
        "meter": meter,
    }


def events(content):
    file = mido.MidiFile(file=BytesIO(content))
    ticks = 0
    seconds = 0
    tempo = 500000
    result = []
    for message in mido.merge_tracks(file.tracks):
        ticks += message.time
        seconds += mido.tick2second(message.time, file.ticks_per_beat, tempo)
        result.append((ticks / file.ticks_per_beat, seconds, message))
        if message.type == "set_tempo":
            tempo = message.tempo
    return file, result


def starts(result):
    return [(tick, seconds, msg.note) for tick, seconds, msg in result
            if msg.type == "note_on" and msg.velocity]


def test_irregular_beats_preserve_audio_times_grid_and_tempo_map():
    times = [1.1234567, 1.6000002, 2.3100011, 2.8000009, 3.4400002]
    file, result = events(generate_chord_midi(snapshot(
        ['C', 'Dm', 'E7', 'F', 'G'], times, [3, 4, 1, 2, 3],
    )))
    onsets = sorted(set((tick, time) for tick, time, _ in starts(result)))
    first = onsets[0][0]
    assert first >= 2 and first % 4 == 2
    assert [tick for tick, _ in onsets] == [first + i for i in range(5)]
    assert [time for _, time in onsets] == pytest.approx(times, abs=0.000002)
    tempos = [(tick, msg.tempo) for tick, _, msg in result if msg.type == 'set_tempo']
    assert [tick for tick, _ in tempos] == [0] + [first + i for i in range(5)]
    assert tempos[2][1] == pytest.approx(710001, abs=2)
    assert file.length == pytest.approx(times[-1] + times[-1] - times[-2], abs=0.000002)
    assert any(msg.type == 'program_change' and msg.program == 0 for _, _, msg in result)
    assert [(tick, msg.numerator, msg.denominator) for tick, _, msg in result
            if msg.type == 'time_signature'] == [(0, 4, 4)]


def test_pickup_at_zero_uses_short_measure_then_real_meter():
    _, result = events(generate_chord_midi(snapshot(['C', 'F', 'G'], numbers=[3, 4, 1])))
    assert [(tick, msg.numerator) for tick, _, msg in result
            if msg.type == 'time_signature'] == [(0, 2), (2, 4)]
    assert sorted(set((tick, time) for tick, time, _ in starts(result))) == [(0, 0), (1, .5), (2, 1)]


def test_held_chords_and_rests_end_without_stuck_notes():
    file, result = events(generate_chord_midi(snapshot(['C', 'C', 'N', 'X', 'bad', 'G', 'G'])))
    assert sorted(set(tick for tick, _, _ in starts(result))) == [0, 5]
    assert sorted(set(tick for tick, _, msg in result if msg.type == 'note_off')) == [2, 7]
    assert file.length == 3.5
    active = set()
    for _, _, msg in result:
        if msg.type == 'note_on':
            active.add(msg.note)
        if msg.type == 'note_off':
            active.remove(msg.note)
    assert not active


@pytest.mark.parametrize(('label', 'notes'), [
    ('D♭maj7/A♭', {56, 61, 65, 68, 72}),
    ('C/E', {52, 60, 64, 67}),
    ('C9', {48, 60, 64, 67, 70, 74}),
    ('C7♭9', {48, 60, 64, 67, 70, 73}),
    ('C°7', {48, 60, 63, 66, 69}),
    ('Cø7', {48, 60, 63, 66, 70}),
    ('CΔ7', {48, 60, 64, 67, 71}),
    ('C+', {48, 60, 64, 68}),
])
def test_chord_names_extensions_and_slash_bass(label, notes):
    _, result = events(generate_chord_midi(snapshot([label])))
    assert {note for _, _, note in starts(result)} == notes


@pytest.mark.parametrize('times', [[0, 0], [1, .5], [-1, 0], [0, float('nan')],
                                  [0, float('inf')], [0, 20], [0, 1e-8], [0]])
def test_invalid_grid_is_rejected(times):
    with pytest.raises(ValueError):
        generate_chord_midi(snapshot(['C', 'G'], times))


def test_single_beat_has_bounded_duration_and_silent_preroll():
    file, result = events(generate_chord_midi(snapshot(['C'], [2.5])))
    assert {time for _, time, _ in starts(result)} == {2.5}
    assert file.length == 3


def test_grid_ending_before_pickup_downbeat_has_no_events_after_end():
    file, result = events(generate_chord_midi(snapshot(['C'], [0], [2])))
    assert file.length == .5
    assert all(message.time >= 0 for track in file.tracks for message in track)
    assert all(track[-1].type == 'end_of_track' for track in file.tracks)
    assert max(tick for tick, _, _ in result) == 1


def test_tempo_rounding_does_not_accumulate_drift():
    times = [i * .50000049 for i in range(200)]
    _, result = events(generate_chord_midi(snapshot(['C', 'G'] * 100, times)))
    onsets = sorted(set(time for _, time, _ in starts(result)))
    assert onsets == pytest.approx(times, abs=.00000051)


@pytest.mark.parametrize('meter', [0, -1, True, 256, 3.5])
def test_invalid_meter_is_rejected(meter):
    with pytest.raises(ValueError, match='meter'):
        generate_chord_midi(snapshot(['C'], meter=meter, numbers=[1]))


def test_short_pickup_ends_before_unreached_downbeat():
    file, result = events(generate_chord_midi(snapshot(['C'], [0], [3])))
    assert file.length == .5
    assert max(tick for tick, _, _ in result) == 1


def test_all_rests_still_preserve_duration_and_tempo_map():
    file, result = events(generate_chord_midi(snapshot(['N', 'X', 'unrecognized'], [0, .6, 1.3])))
    assert not starts(result)
    assert file.length == 2
