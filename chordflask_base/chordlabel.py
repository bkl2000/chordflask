"""Pure chord-label logic (neutral, framework-free).

Part of :mod:`chordflask_base`. Contains only the label utilities that depend on
nothing but the standard library: label validation, run-length
encoding/expansion, and root/bass-only transposition and respelling.

The audio-, music21-, and Unicode-dependent parts stay in ``flask/chordutils.py``
(the view/analysis helper); that module re-exports the names below so existing
``chordutils.<name>`` call sites keep working.
"""

from __future__ import annotations

import re


def _chord_ascii_label(label):
    return (
        label.replace('\u266d', 'b')
        .replace('\u266f', '#')
        .replace('\u00f87', 'm7b5')
        .replace('\u00b07', 'dim7')
        .replace('\u00b0', 'dim')
        .replace('+', 'aug')
    )


_CHORD_QUALITIES = (
    "mmaj7", "maj7", "maj9", "m7b5", "min7b5", "m7", "m9", "m6",
    "min", "maj", "m", "dim7", "dim", "aug", "sus4", "sus2",
)
_CHORD_LABEL_RE = re.compile(
    r"^[A-Ga-g][b#]?"
    r"(?:" + "|".join(_CHORD_QUALITIES) + r"|7[b#]?[0-9]?|6)?"
    r"(?:/[A-Ga-g][b#]?)?$"
)


def validate_chord_label(label):
    """Return the normalized ASCII chord label, or raise ValueError.

    Accepts N and X (case-insensitive), ASCII and Unicode accidentals,
    supported qualities, and slash chords. Invalid input is rejected
    rather than silently converted to ``N``.
    """
    if not isinstance(label, str):
        raise ValueError("chord label must be a string")
    text = label.strip()
    if not text:
        raise ValueError("chord label must not be empty")
    text = _chord_ascii_label(text)
    if text.upper() in ("N", "X"):
        return text.upper()
    if not _CHORD_LABEL_RE.match(text):
        raise ValueError(f"invalid chord label: {label!r}")
    return text


def rle_chord_labels(events):
    """Run-length encode a (timestamp, label) sequence into chord entries."""
    encoded = []
    for timestamp, label in events:
        if encoded and encoded[-1][1] == label:
            continue
        encoded.append((timestamp, label))
    return [{"timestamp": ts, "chord": ch} for ts, ch in encoded]


def expand_chord_labels(entries, beat_times):
    """Expand run-length-encoded chord entries back to one label per beat."""
    labels = []
    index = 0
    current = "N"
    for beat_time in beat_times:
        while index < len(entries) and entries[index]["timestamp"] <= beat_time:
            current = entries[index]["chord"]
            index += 1
        labels.append(current)
    return labels


_CHORD_ROOT_RE = re.compile(r"^[A-Ga-g][b#]?")

_PITCH_CLASSES = {
    "C": 0, "B#": 0,
    "C#": 1, "Db": 1,
    "D": 2,
    "D#": 3, "Eb": 3,
    "E": 4, "Fb": 4,
    "E#": 5, "F": 5,
    "F#": 6, "Gb": 6,
    "G": 7,
    "G#": 8, "Ab": 8,
    "A": 9,
    "A#": 10, "Bb": 10,
    "B": 11, "Cb": 11,
}

_FLAT_PITCHES = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")
_SHARP_PITCHES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def transpose_pitch(pitch, semitones, prefer_flats):
    """Transpose one pitch while choosing a consistent display spelling."""
    key = pitch[0].upper() + pitch[1:]
    pitch_class = (_PITCH_CLASSES[key] + semitones) % 12
    names = _FLAT_PITCHES if prefer_flats else _SHARP_PITCHES
    return names[pitch_class]


def respell_pitch(pitch, prefer_flats):
    """Respell one pitch name (letter plus optional accidental) to flats or sharps.

    Natural notes and already-preferred spellings pass through unchanged.
    """
    return transpose_pitch(pitch, 0, prefer_flats)


def respell_chord_label(label, prefer_flats):
    """Respell a chord label's root and slash bass, preserving its quality.

    Only the root and an optional slash-bass pitch are respelled, so quality
    alterations such as ``7#9``, ``7b5``, and ``m7b5`` stay exactly as written.
    ``N`` and ``X`` pass through unchanged, as do labels without a leading
    pitch letter. This is display spelling only and never changes stored data.
    """
    return transpose_chord_pitches(label, 0, prefer_flats)


def transpose_chord_pitches(label, semitones, prefer_flats):
    """Transpose only a chord's root and slash bass.

    The quality suffix is copied byte-for-byte. This avoids music21 changing
    accepted analyzer notation such as ``C7#9`` into another textual form.
    Unknown labels pass through unchanged; validation remains the caller's
    responsibility at editing boundaries.
    """
    if not isinstance(label, str):
        return label
    if label.upper() in ("N", "X"):
        return label.upper()
    base, separator, bass = label.partition("/")
    root_match = _CHORD_ROOT_RE.match(base)
    if root_match is None:
        return label
    root = root_match.group(0)
    result = transpose_pitch(root, semitones, prefer_flats) + base[root_match.end():]
    if separator:
        bass_match = _CHORD_ROOT_RE.match(bass)
        if bass_match is None:
            result += "/" + bass
        else:
            bass_root = bass_match.group(0)
            result += "/" + transpose_pitch(
                bass_root, semitones, prefer_flats
            ) + bass[bass_match.end():]
    return result
