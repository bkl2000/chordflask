#!/usr/bin/env python3
"""Read-only diagnostic: print metric-chords classification and per-beat differences.

Usage:
    python scripts/metric_chords_diff.py chord1.json [chord2.json ...]

Never writes or modifies analysis files.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chordflask.chorddata import ChordData, ChordTrackRepository
from chordflask.metric_chords import filter_metric_chords


def diff_one(filename):
    file_path = Path(filename).resolve()
    if not file_path.is_file():
        print(f"SKIP {file_path}: not a file")
        return 1

    print(f"\n=== {file_path.name} ===")
    print(f"Path: {file_path}")

    data = ChordData()
    try:
        ChordTrackRepository().load(file_path, data)
    except (ValueError, OSError) as error:
        print(f"ERROR loading chord data: {error}")
        return 1

    beat_chords = data.get_chords_per_beat()
    if not beat_chords:
        print("No beat-aligned chords available")
        return 0

    filtered, classification = filter_metric_chords(
        beat_chords,
        data.beat_times,
        data.beat_numbers,
        data.beat_chord_indexes,
        data.meter_signature,
        data.chord_times,
    )

    print()
    print("Classification:")
    print(f"  status:        {classification['classification']}")
    print(f"  beat_count:    {classification.get('beat_count', '?')}")
    print(f"  meter:         {classification.get('meter', '?')}")
    if "cv" in classification:
        print(f"  cv:            {classification['cv']}")
        print(f"  mad_ratio:     {classification['mad_ratio']}")
        print(f"  deviant_frac:  {classification['deviant_fraction']}")
        print(f"  cycle_pass:    {classification['cycle_pass_fraction']}")
    if "reason" in classification:
        print(f"  reason:        {classification['reason']}")

    if classification["classification"] != "stable":
        print("\nGrid is not stable. No per-beat differences computed.")
        return 0

    differences = []
    for i in range(len(beat_chords)):
        if filtered[i][1] != beat_chords[i][1]:
            delta = beat_chords[i][0]
            beat_num = data.beat_numbers[i] if i < len(data.beat_numbers) else "?"
            differences.append((i, delta, beat_num, beat_chords[i][1], filtered[i][1]))

    print(f"\nBeats with suppressed chord ({len(differences)} total):")
    if not differences:
        print("  (none)")
    for idx, beat_time, beat_num, original, suppressed in differences:
        print(f"  beat {idx:4d}  time={beat_time:8.3f}s  beat-number={beat_num}  "
              f"{original:>6s} -> {suppressed:<6s}")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Metric-chords read-only diagnostic: classify rhythm and show "
                    "per-beat chord differences"
    )
    parser.add_argument(
        "files", nargs="+", metavar="FILE",
        help="One or more ChordFlask JSON chord analysis files"
    )
    args = parser.parse_args()

    failures = 0
    for filename in args.files:
        exit_code = diff_one(filename)
        if exit_code:
            failures += 1

    raise SystemExit(min(failures, 1))


if __name__ == "__main__":
    main()
