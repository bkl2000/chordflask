#!/usr/bin/env python3

from collections import deque

class MP4Player:
    def __init__(self, chord_data=None, semitones=0, sync_chords=True):
        self.chord_data = chord_data
        self.semitones = semitones
        self.sync_chords = sync_chords
        self.callback_output = deque(maxlen=30)
        self.last_chord = None

        if self.chord_data:
            self.chord_data.transpose(semitones)

    def update_position(self, position):
        if not self.chord_data:
            return
        chords = self.chord_data.get_next_chords(position, 4)
        out = f"{position:.2f}s | " + " | ".join(chords)
        if chords[0] != self.last_chord:
            print(out)
            self.callback_output.append(out)
            self.last_chord = chords[0]