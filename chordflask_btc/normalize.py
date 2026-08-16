"""Pure BTC raw-label -> ChordFlask label normalization (no torch/flask imports).

BTC-ISMIR19 emits 170 classes in ``root:quality`` notation (the plain major
quality is emitted as the bare root). This module maps that notation to the
ChordFlask spelling used for storage/display. ``N`` and ``X`` pass through.

The mapping is a fixed table: BTC's output vocabulary contains exactly 12 sharp
roots x 14 qualities plus ``X``/``N`` and never emits slash/inversion chords.
"""

from __future__ import annotations

from typing import Any

BTC_QUALITY_SUFFIX: dict[str, str] = {
    "maj": "",
    "min": "m",
    "dim": "dim",
    "aug": "aug",
    "min6": "m6",
    "maj6": "6",
    "min7": "m7",
    "minmaj7": "mmaj7",
    "maj7": "maj7",
    "7": "7",
    "dim7": "dim7",
    "hdim7": "m7b5",
    "sus2": "sus2",
    "sus4": "sus4",
}


def normalize_btc_label(raw: Any) -> str:
    """Map one BTC label to its ChordFlask spelling.

    ``N``/``X`` pass through unchanged. A bare root is the major quality and is
    returned unchanged (``C`` -> ``C``). A ``root:quality`` label is rewritten
    using :data:`BTC_QUALITY_SUFFIX` (``F#:7`` -> ``F#7``, ``B:maj7`` ->
    ``Bmaj7``). Unknown qualities raise :class:`ValueError`.
    """
    if not isinstance(raw, str):
        raise ValueError(f"BTC chord label must be a string, got {raw!r}")
    text = raw.strip()
    if not text:
        raise ValueError("BTC chord label must not be empty")
    if text in ("N", "X"):
        return text
    if ":" not in text:
        return text
    root, quality = text.split(":", 1)
    suffix = BTC_QUALITY_SUFFIX.get(quality)
    if suffix is None:
        raise ValueError(f"Unknown BTC chord quality {quality!r} in label {raw!r}")
    return root + suffix


def normalize_btc_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return ``{timestamp, chord}`` events with normalized chord labels."""
    result = []
    for entry in events:
        if not isinstance(entry, dict) or "timestamp" not in entry or "chord" not in entry:
            raise ValueError(f"Malformed BTC event: {entry!r}")
        result.append(
            {
                "timestamp": entry["timestamp"],
                "chord": normalize_btc_label(entry["chord"]),
            }
        )
    return result
