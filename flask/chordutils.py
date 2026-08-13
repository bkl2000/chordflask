#!/usr/bin/env python3

"""
chordutils.py

Utility functions for handling chord labels and transpositions.

Functions:
- is_valid_chord_label(chord_label): Validates chord labels. [COMMENTED OUT]
- fix_chord_label(chord_label): Converts chord labels to a format compatible with music21.
- inv_fix_chord_label(fixed_chord_label): Converts chord labels from music21 format back to standard notation.
- transpose_single_chord(chord_label, semitones, prefer_flats): Transposes a single chord.
- _apply_unicode_formatting(chord_label): Applies Unicode formatting to chord labels.
- transpose_chords(chord_list, semitones=0, prefer_flats=True, use_unicode=False, parallel=False): Transposes a list of chords by a specified number of semitones and optionally formats them with UTF-8 characters.
"""

import re
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import lru_cache
import atexit
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Mapping for converting flat and sharp symbols to Unicode
FLAT_UNICODE = {
    'b': '♭',
    '-': '♭'  # Assuming '-' is used for flats in fixed labels
}

SHARP_UNICODE = {
    '#': '♯',
    '+': '♯'  # Assuming '+' might represent augmented chords which could include sharps
}

# Define suffix mappings for accurate replacements
CHORD_SUFFIX_REPLACEMENTS = {
    'm7b5': 'ø7',
    'maj7': 'M7',
    'maj9': 'M9',
    'm7': 'm7',
    'm9': 'm9',
    'm6': 'm6',
    '6': '6',
    'min7b5': 'm7b5',
    'min': 'm',
    'dim7': 'dim7',
    'dim': 'dim',
    'aug': 'aug',  # Keep 'aug' for clarity before Unicode formatting
    'sus4': 'sus4',
    'sus2': 'sus2',
    '7#5': '7#5',
    '7b5': '7b5',
    '7#9': '7#9',
    '7b9': '7b9',
    '+': '+',      # Ensure '+' is preserved for augmented chords
}

INV_CHORD_SUFFIX_REPLACEMENTS = {
    'ø7': 'm7♭5',
    'M7': 'maj7',
    'M9': 'maj9',
    'm7': 'm7',
    'm9': 'm9',
    'm6': 'm6',
    '6': '6',
    'm7b5': 'm7b5',
    'm': 'min',
    'dim7': 'dim7',
    'dim': 'dim',
    'aug': 'aug',
    'sus4': 'sus4',
    'sus2': 'sus2',
    '7#5': '7♯5',
    '7b5': '7♭5',
    '7#9': '7♯9',
    '7b9': '7♭9',
    '+': '+',      # Preserve '+' for augmented chords
}

# Precompile regex patterns for performance
FIX_CHORD_SUFFIX_PATTERN = re.compile(
    r'(?<![\w/])(' + '|'.join(map(re.escape, CHORD_SUFFIX_REPLACEMENTS.keys())) + r')(?![\w/])'
)

INV_FIX_CHORD_SUFFIX_PATTERN = re.compile(
    r'(?<![\w/])(' + '|'.join(map(re.escape, INV_CHORD_SUFFIX_REPLACEMENTS.keys())) + r')(?![\w/])'
)

DIM_PATTERN = re.compile(r'dim')
AUG_PATTERN = re.compile(r'aug')
M7B5_PATTERN = re.compile(r'm7b5')
SEVENTH_SHARP_PATTERN = re.compile(r'7#5')
SEVENTH_FLAT_PATTERN = re.compile(r'7b5')
SEVENTH_SHARP9_PATTERN = re.compile(r'7#9')
SEVENTH_FLAT9_PATTERN = re.compile(r'7b9')

_executor = None


def get_executor():
    global _executor
    if _executor is None:
        _executor = ProcessPoolExecutor(max_workers=4)
    return _executor

def shutdown_executor():
    if _executor is not None:
        _executor.shutdown(wait=True)

atexit.register(shutdown_executor)

# Commented out as per user request for potential future use
# def is_valid_chord_label(chord_label):
#     """
#     Validates whether the chord_label is a non-empty string, matches expected chord patterns,
#     or is 'N' representing no chord.
#
#     Args:
#         chord_label (str): The chord label to validate (e.g., "Amaj7", "Bbmin", "E/B", "N").
#
#     Returns:
#         bool: True if the chord label is valid, False otherwise.
#     """
#     if not isinstance(chord_label, str) or not chord_label.strip():
#         return False
#
#     if chord_label.upper() == 'N':
#         return True
#
#     # Define a regex pattern for valid chord labels
#     chord_pattern = re.compile(
#         r"""
#         ^                       # Start of string
#         [A-G]                   # Root note A-G
#         [b#]?                   # Optional flat or sharp
#         (                       # Start of chord quality group
#             maj7                # Major 7th
#             |maj9               # Major 9th
#             |m7b5               # Minor 7 flat 5
#             |m7                 # Minor 7th
#             |m9                 # Minor 9th
#             |m6                 # Minor 6th
#             |m                  # Minor
#             |dim7               # Diminished 7th
#             |dim                # Diminished
#             |aug                # Augmented
#             |sus4               # Suspended 4th
#             |sus2               # Suspended 2nd
#             |\+                 # Augmented using '+' symbol
#             |6                  # 6th
#             |7[#b]?\d*          # Dominant 7th with optional alterations (e.g., 7, 7#5, 7b9, 7#9)
#         )?                      # Chord quality is optional
#         (\/[A-G][b#]?)?         # Optional bass note (slash chord)
#         $                       # End of string
#         """,
#         re.VERBOSE
#     )
#
#     return bool(chord_pattern.match(chord_label))


@lru_cache(maxsize=20000)
def get_transposed_chord_cached(fixed_label, semitones, prefer_flats):
    """
    Cached function to transpose a single chord.

    Args:
        fixed_label (str): The fixed chord label compatible with music21.
        semitones (int): Number of semitones to transpose.
        prefer_flats (bool): Whether to prefer flats over sharps.

    Returns:
        str: The transposed chord label in standard notation.
    """
    from music21 import harmony

    try:
        chord_symbol = harmony.ChordSymbol(fixed_label)
        chord_symbol_transposed = chord_symbol.transpose(semitones)

        # Handle accidental preference
        for p in chord_symbol_transposed.pitches:
            if prefer_flats:
                if p.accidental and p.accidental.name == 'sharp':
                    enharmonic_pitch = p.getEnharmonic()
                    p.name = enharmonic_pitch.name
            else:
                if p.accidental and p.accidental.name == 'flat':
                    enharmonic_pitch = p.getEnharmonic()
                    p.name = enharmonic_pitch.name

        transposed_chord_label = chord_symbol_transposed.figure
        transposed_chord_label = inv_fix_chord_label(transposed_chord_label)
        return transposed_chord_label
    except Exception as e:
        logging.error(f"Error in get_transposed_chord_cached: {e}")
        return 'N'


def fix_chord_label(chord_label):
    """
    Fix the chord labels to be compatible with music21.

    Args:
        chord_label (str): The original chord label (e.g., "Abmaj7", "Bbmin").

    Returns:
        str: The fixed chord label compatible with music21 (e.g., "A-M7", "B-m").
    """
    # Replace flats with music21-compatible flat symbols
    flat_mappings = {'Ab': 'A-', 'Bb': 'B-', 'Cb': 'C-', 'Db': 'D-', 'Eb': 'E-', 'Fb': 'F-', 'Gb': 'G-'}
    for flat, replacement in flat_mappings.items():
        chord_label = chord_label.replace(flat, replacement)

    # Replace chord suffixes using the optimized regex pattern
    chord_label = FIX_CHORD_SUFFIX_PATTERN.sub(lambda match: CHORD_SUFFIX_REPLACEMENTS.get(match.group(1), match.group(1)), chord_label)

    # Handle slash chords
    if '/' in chord_label:
        base, bass = chord_label.split('/')
        return f"{fix_chord_label(base)}/{fix_chord_label(bass)}"

    return chord_label


def inv_fix_chord_label(fixed_chord_label):
    """
    Convert fixed chord labels from music21 format back to standard notation.

    Args:
        fixed_chord_label (str): The fixed chord label from music21 (e.g., "A-M7", "B-m").

    Returns:
        str: The original chord label in standard notation (e.g., "Abmaj7", "Bbmin").
    """
    # Replace music21 suffixes back to standard chord suffixes using optimized regex
    fixed_chord_label = INV_FIX_CHORD_SUFFIX_PATTERN.sub(lambda match: INV_CHORD_SUFFIX_REPLACEMENTS.get(match.group(1), match.group(1)), fixed_chord_label)

    # Replace music21-compatible flat symbols back to standard flats
    flat_mappings = {'A-': 'Ab', 'B-': 'Bb', 'C-': 'Cb', 'D-': 'Db', 'E-': 'Eb', 'F-': 'Fb', 'G-': 'Gb'}
    for fixed, original in flat_mappings.items():
        fixed_chord_label = fixed_chord_label.replace(fixed, original)

    return fixed_chord_label


def _apply_unicode_formatting(chord_label):
    """
    Apply UTF-8 Unicode formatting to chord labels for better visual representation.

    Args:
        chord_label (str): The chord label in standard notation.

    Returns:
        str: The chord label with UTF-8 Unicode characters.
    """
    # Replace flats and sharps with their Unicode counterparts
    for key, value in FLAT_UNICODE.items():
        chord_label = chord_label.replace(key, value)
    
    # Replace sharps only if no flat symbol is present
    if '♭' not in chord_label:
        for key, value in SHARP_UNICODE.items():
            chord_label = chord_label.replace(key, value)

    # Replace 'dim' with '°' and 'aug' with '+' for better clarity
    chord_label = DIM_PATTERN.sub('°', chord_label)
    chord_label = AUG_PATTERN.sub('+', chord_label)  # Use '+' for augmented chords

    # Replace specific complex suffixes with Unicode
    chord_label = M7B5_PATTERN.sub('m7♭5', chord_label)
    chord_label = SEVENTH_SHARP_PATTERN.sub('7♯5', chord_label)
    chord_label = SEVENTH_FLAT_PATTERN.sub('7♭5', chord_label)
    chord_label = SEVENTH_SHARP9_PATTERN.sub('7♯9', chord_label)
    chord_label = SEVENTH_FLAT9_PATTERN.sub('7♭9', chord_label)

    return chord_label


@lru_cache(maxsize=20000)
def transpose_single_chord(chord_label, semitones, prefer_flats):
    """
    Transpose a single chord, using try-except to handle invalid chord labels.

    Args:
        chord_label (str): The original chord label.
        semitones (int): Number of semitones to transpose.
        prefer_flats (bool): Whether to prefer flats over sharps.

    Returns:
        str: The transposed chord label, or 'N' if the chord cannot be transposed.
    """
    special = chord_label.upper()
    if special in {'N', 'X'}:
        return special

    try:
        fixed_label = fix_chord_label(chord_label)
        transposed_label = get_transposed_chord_cached(fixed_label, semitones, prefer_flats)
        return transposed_label
    except Exception as e:
        logging.error(f"Error transposing chord '{chord_label}': {e}")
        return 'N'


def transpose_chords(chord_list, semitones=0, prefer_flats=True, use_unicode=True, parallel=True):
    """
    Transpose a list of chords represented as (timestamp, chord_label) tuples.

    Args:
        chord_list (list): List of tuples containing (timestamp, chord_label).
        semitones (int): Number of semitones to transpose.
        prefer_flats (bool): If True, output chords using flat notation; otherwise, use sharps.
        use_unicode (bool): If True, format chord labels with UTF-8 Unicode characters.
        parallel (bool): If True, use parallel processing.

    Returns:
        list: List of transposed chords as (timestamp, chord_label) tuples.
    """
    if not chord_list:
        logging.warning("No chords to transpose.")
        return []

    if parallel:
        # Prepare arguments for parallel processing
        args_list = [
            (chord_label, semitones, prefer_flats)
            for _, chord_label in chord_list
        ]

        # Initialize an empty list to store transposed labels
        transposed_labels = ['N'] * len(chord_list)  # Initialize with 'N'

        # Submit all tasks at once to the global executor
        executor = get_executor()
        futures = {executor.submit(transpose_single_chord, *args): idx for idx, args in enumerate(args_list)}

        # Collect results while maintaining the original order
        for future in as_completed(futures):
            idx = futures[future]
            try:
                transposed_labels[idx] = future.result()
            except Exception as e:
                transposed_labels[idx] = 'N'
                logging.error(f"Error during transposition: {e}")

        # Apply Unicode formatting if needed
        if use_unicode:
            transposed_labels = [_apply_unicode_formatting(label) for label in transposed_labels]

        # Pair timestamps with transposed labels
        transposed_chords = [
            (chord_list[i][0], transposed_labels[i])
            for i in range(len(chord_list))
        ]

    else:
        transposed_chords = []
        for timestamp, chord_label in chord_list:
            try:
                transposed_label = transpose_single_chord(chord_label, semitones, prefer_flats)

                if use_unicode and transposed_label != 'N':
                    transposed_label = _apply_unicode_formatting(transposed_label)

                transposed_chords.append((timestamp, transposed_label))
            except Exception as e:
                logging.error(f"Skipping invalid chord '{chord_label}' at {timestamp:.2f}s: {e}")
                transposed_chords.append((timestamp, 'N'))

    # Sort transposed chords by timestamp to ensure they are in the correct order
    transposed_chords.sort(key=lambda x: x[0])
    return transposed_chords


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
    "maj7", "maj9", "m7b5", "min7b5", "m7", "m9", "m6",
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


def detect_tempo_from_audio(audio_file_path="", sr=22050, y=None, plot_onset=False):
    """
    Detects tempo (BPM) of an audio file using onset envelope and beat tracking.

    Args:
        audio_file_path (str): Path to the audio file.
        sr (int): Sample rate.
        y: Preloaded signal (optional).
        plot_onset (bool): If True, plot onset envelope for diagnostics.

    Returns:
        int: Detected BPM.
        list: Beat times in seconds.
    """
    import librosa
    import numpy as np
    import logging

    if y is None:
        y, sr = librosa.load(audio_file_path, sr=sr, mono=True)

    logging.info(f"Signal shape: {y.shape}, Sample rate: {sr}")

    # Apply pre-emphasis and HPSS to enhance percussive content
    #y = librosa.effects.preemphasis(y)   # assume we did it before
    y_harmonic, y_percussive = librosa.effects.hpss(y)

    # Use onset envelope from percussive part
    onset_env = librosa.onset.onset_strength(y=y_percussive, sr=sr, aggregate=np.mean, max_size=7)

    if plot_onset:
        import matplotlib.pyplot as plt
        plt.figure(figsize=(10, 4))
        plt.plot(onset_env, label="Onset Envelope")
        plt.title("Onset Envelope (Percussive)")
        plt.xlabel("Frames")
        plt.ylabel("Amplitude")
        plt.legend()
        plt.tight_layout()
        plt.show()

    # Beat tracking
    tempo, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_env,
        sr=sr,
        start_bpm=80,
        tightness=100,
        units='frames'
    )

    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    if len(beat_times) < 2:
        logging.warning("Not enough beats detected to calculate tempo.")
        return None, []

    # Calculate BPM from average beat intervals
    beat_intervals = np.diff(beat_times)
    interval_std = np.std(beat_intervals)
    bpm = 60 / np.mean(beat_intervals)

    logging.info(f"Raw Tempo: {bpm:.2f} BPM (Interval STD: {interval_std:.4f})")

    if bpm < 59:  # Adjust for halved tempo
        bpm *= 2
    bpm = round(bpm)
    logging.info(f"Adjusted Tempo: {bpm} BPM")

    return bpm, list(beat_times)

def detect_tempo_from_audio_old(audio_file_path="", sr=22050, y=None):

    """
    Detects tempo (BPM) of an audio file by analyzing beat intervals.

    Args:
        audio_file_path (str): Path to the audio file.
        sr (int): Sample rate for loading the audio.
        y: either y from librosa.load or load myself from audio_file_path

    Returns:
        float: Detected BPM of the audio file.
        list: List of beat timestamps in seconds.
    """
    import librosa
    import numpy as np

    if y is None:
       y, sr = librosa.load(audio_file_path, sr=sr, mono=True)

    print(f"Signal shape: {y.shape}, Sample rate: {sr}")
    print(f"Max amplitude: {y.max()}, Min amplitude: {y.min()}")

    #y = y / np.max(np.abs(y))  # Normalize to [-1, 1]
    #y = librosa.effects.preemphasis(y)  # Apply pre-emphasis

    #onset_env = librosa.onset.onset_strength(y=y, sr=sr, aggregate=np.mean, max_size=3)

    #onset_env = librosa.onset.onset_strength(y=y, sr=sr, aggregate=np.max)
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, aggregate=np.mean)

    # beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)[0]

    #tempo, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr, start_bpm=120, tightness=50)
    tempo, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr, start_bpm=40, tightness=50)

    #print(f"{tempo = }")

    #beat_frames = librosa.beat.beat_track(y=y, sr=sr, tightness=100, units='frames')[0]
    #beat_frames = librosa.beat.beat_track(y=y, sr=sr)[0]

    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    #print(beat_frames)
    #print(beat_times)

    if len(beat_times) < 2:
        logging.warning("Not enough beats detected to calculate tempo.")
        return None, []

    # Calculate BPM from average beat intervals
    beat_intervals = np.diff(beat_times)
    bpm = 60 / np.mean(beat_intervals)
    logging.info(f"Detected Tempo: {bpm:.2f} BPM")

    if bpm < 70:  # Threshold to decide if tempo might be halved
        bpm *= 2
    logging.info(f"Adjusted Tempo: {bpm:.2f} BPM")


    return round(bpm), list(beat_times)




def render_chord_line(beat_time, chords, active_index=0, highlight_style="bracket"):
    rendered = []
    for i, chord in enumerate(chords):
        if i == active_index:
            rendered.append(f"[{chord:^6}]")
        else:
            rendered.append(f"{chord:^8}")
    return f"{beat_time:<6.2f}s | " + " | ".join(rendered)


def _format_grid_chord(chord, active=False, width=7):
    if active:
        inner_width = max(width - 2, 1)
        return f"[{chord:^{inner_width}}]"
    return f"{chord:^{width}}"


def render_chord_output(style, beat_time, chords=None, all_chords=None, active_index=0,
                        repeat_mode="chords", beats_per_row=8, rows=8, active_row_start=None):
    if style == "grid":
        return render_chord_grid(
            beat_time,
            all_chords,
            active_index,
            beats_per_row=beats_per_row,
            rows=rows,
            repeat_mode=repeat_mode,
            active_row_start=active_row_start,
        )
    return render_chord_line(beat_time, chords, active_index)

def render_chord_grid(
    beat_time,
    all_chords,
    active_index,
    beats_per_row=8,
    rows=8,
    highlight_style="bracket",
    repeat_mode="chords",
    active_row_start=None,
):
    """
    Render a multiline grid of chords, preserving one chord per beat,
    and highlighting the current active beat index.

    Args:
        beat_time (float): The current beat time.
        all_chords (list): List of (timestamp, chord) tuples.
        active_index (int): Index of the currently active chord.
        beats_per_row (int): Number of chords per row.
        rows (int): Number of rows to display.
        highlight_style (str): Style of highlighting ('bracket' supported).

    Returns:
        str: Multiline formatted chord grid.
    """
    total_chords = beats_per_row * rows
    if active_row_start is None:
        active_row_start = active_index - (active_index % beats_per_row)
    start_index = active_row_start - beats_per_row
    end_index = start_index + total_chords

    display_chords = [
        all_chords[idx] if 0 <= idx < len(all_chords) else (0, '')
        for idx in range(start_index, end_index)
    ]

    output_lines = []
    for row in range(rows):
        line = []
        for col in range(beats_per_row):
            idx = row * beats_per_row + col
            abs_idx = start_index + idx
            _, chord = display_chords[idx]
            if repeat_mode == "changes" and chord and col != 0:
                previous_index = abs_idx - 1
                previous_chord = (
                    all_chords[previous_index][1]
                    if 0 <= previous_index < len(all_chords)
                    else None
                )
                if previous_chord == chord:
                    chord = "_"
            line.append(_format_grid_chord(chord, active=abs_idx == active_index and highlight_style == "bracket"))
        output_lines.append("".join(line))

    header = f"{beat_time:.1f}s\n"
    return header + "\n".join(output_lines)
