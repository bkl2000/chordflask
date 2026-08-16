"""BTC-ISMIR19 large-vocabulary index -> chord-label mapping (170 classes).

Reproduces the exact ``idx2voca_chord`` mapping from the BTC-ISMIR19 project:
12 sharp roots x 14 qualities (= 168) plus ``X`` (unknown, index 168) and ``N``
(no chord, index 169). The model never emits slash/inversion chords; its output
is always one of these 170 classes.

Quality index 1 is the plain major quality and is rendered as the bare root
(``C``) instead of ``C:maj``, exactly as the original project does.
"""

from __future__ import annotations

ROOT_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

QUALITY_NAMES = (
    "min",
    "maj",
    "dim",
    "aug",
    "min6",
    "maj6",
    "min7",
    "minmaj7",
    "maj7",
    "7",
    "dim7",
    "hdim7",
    "sus2",
    "sus4",
)

NUM_ROOTS = len(ROOT_NAMES)
NUM_QUALITIES = len(QUALITY_NAMES)
NUM_CLASSES = NUM_ROOTS * NUM_QUALITIES + 2  # 170
UNKNOWN_INDEX = NUM_ROOTS * NUM_QUALITIES  # 168 -> "X"
NO_CHORD_INDEX = NUM_ROOTS * NUM_QUALITIES + 1  # 169 -> "N"

_IDX_TO_CHORD: dict[int, str] = {
    NO_CHORD_INDEX: "N",
    UNKNOWN_INDEX: "X",
}
for _i in range(NUM_ROOTS * NUM_QUALITIES):
    _root = ROOT_NAMES[_i // NUM_QUALITIES]
    _quality = QUALITY_NAMES[_i % NUM_QUALITIES]
    _IDX_TO_CHORD[_i] = _root if _quality == "maj" else f"{_root}:{_quality}"


def label_for_index(index: int) -> str:
    """Return the BTC chord label for one class index (``X`` when unknown)."""
    if isinstance(index, bool) or not isinstance(index, int):
        raise ValueError(f"Chord index must be an integer, got {index!r}")
    return _IDX_TO_CHORD.get(index, "X")
