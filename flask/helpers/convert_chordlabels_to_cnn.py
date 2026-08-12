#!/usr/bin/env python3

"""
ChordLabelConverter
====================

This script converts chord label JSON files from ChordAnalyzer format
into CNN-compatible format for PyTorch model training.

Input format (v3 chord data from chordanalyzer.py):
---------------------------------------------------
{
  "schema_version": 3,
  "chord_tracks": {
    "chordino": { "chords": [ {"timestamp": 0.0, "chord": "C:maj"}, ... ] }
  },
  ...
}

Input format (v1/v2 legacy):
----------------------------
{
  "base_chords": [
    { "timestamp": 0.0, "chord": "C:maj" },
    ...
  ],
  ...
}

Output format (expected by chord_dataset_pytorch.py):
------------------------------------------------------
[
  { "time": 0.0, "chord": "C:maj" },
  ...
]

Default usage:
--------------
Terminal:
    $ python convert_chordlabels.py chords vampchords

Python (manual usage):
    from convert_chordlabels import ChordLabelConverter
    converter = ChordLabelConverter()
    converter.convert_dir("chords", "vampchords")
"""

import os
import json

class ChordLabelConverter:
    def __init__(self, verbose=True):
        self.verbose = verbose

    def convert_file(self, in_path, out_path):
        """
        Convert a single JSON file from ChordAnalyzer format to CNN format.
        Renames 'timestamp' → 'time', strips wrapper if needed.
        """
        try:
            with open(in_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            chords = self.__chords_from_document(data, in_path)

            converted = []
            for index, entry in enumerate(chords):
                if not isinstance(entry, dict):
                    raise ValueError(
                        f"Invalid chord entry {index} in {in_path}: expected an object"
                    )
                if "timestamp" in entry and "chord" in entry:
                    converted.append({
                        "time": entry["timestamp"],
                        "chord": entry["chord"]
                    })
                elif "time" in entry and "chord" in entry:
                    converted.append({"time": entry["time"], "chord": entry["chord"]})
                else:
                    raise ValueError(f"Invalid chord entry {index} in {in_path}: {entry}")

            output_dir = os.path.dirname(os.path.abspath(out_path))
            os.makedirs(output_dir, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(converted, f, indent=2)

            if self.verbose:
                print(f"[OK] Converted: {in_path} → {out_path}")

        except Exception:
            if self.verbose:
                print(f"[ERROR] Failed to convert {in_path}")
            raise

    @staticmethod
    def __chords_from_document(data, in_path):
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            raise ValueError(f"Invalid chord document in {in_path}: expected an object")

        version = data.get("schema_version")
        if version == 3:
            chord_tracks = data.get("chord_tracks")
            if not isinstance(chord_tracks, dict):
                raise ValueError(
                    f"Invalid schema v3 chord document in {in_path}: "
                    "chord_tracks must be an object"
                )
            chordino = chord_tracks.get("chordino")
            if not isinstance(chordino, dict) or not isinstance(
                chordino.get("chords"), list
            ):
                raise ValueError(
                    f"Invalid schema v3 chord document in {in_path}: "
                    "chordino.chords is required"
                )
            return chordino["chords"]

        if version not in (None, 1, 2):
            raise ValueError(
                f"Unsupported chord schema version {version!r} in {in_path}"
            )
        chords = data.get("base_chords")
        if not isinstance(chords, list):
            raise ValueError(
                f"Invalid legacy chord document in {in_path}: base_chords is required"
            )
        return chords

    def convert_dir(self, input_dir="chords", output_dir="vampchords"):
        """
        Convert all .json files in input_dir to CNN format.
        Output is saved to output_dir with the same filenames.
        """
        if not os.path.isdir(input_dir):
            raise NotADirectoryError(f"Invalid input directory: {input_dir}")

        os.makedirs(output_dir, exist_ok=True)

        for fname in os.listdir(input_dir):
            if fname.endswith(".json"):
                in_path = os.path.join(input_dir, fname)
                out_path = os.path.join(output_dir, fname)
                self.convert_file(in_path, out_path)


if __name__ == "__main__":

    import sys

    params=sys.argv[1:]
    input_dir   = params.pop(0) if params else "chords"
    output_dir  = params.pop(0) if params else "vampchords"

    converter = ChordLabelConverter()
    converter.convert_dir(input_dir, output_dir)
