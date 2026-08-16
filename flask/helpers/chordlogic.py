#!/usr/bin/env python3

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from chordflask_base import ChordData

class ChordAnalyzer:
    def __init__(self):
        self.chord_data = ChordData()
        self.chord_data.set_base_chords([
            {"timestamp": 0.0, "chord": "C"},
            {"timestamp": 1.0, "chord": "G"},
            {"timestamp": 2.0, "chord": "Am"},
            {"timestamp": 3.0, "chord": "F"},
        ])

    def print_chords(self):
        chords = self.chord_data.get_chords()
        for t, c in chords:
            print(f"{t:.2f}s -> {c}")
