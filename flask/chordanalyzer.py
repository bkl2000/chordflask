#!/usr/bin/env python3
"""CLI entry point and backward-compatible analyzer facade.

New orchestration uses :class:`ChordAnalysisService`, whose failures propagate.
The older ``analyze_chords()`` method deliberately retains its boolean result
and console diagnostic for compatibility with existing callers.
"""

import os
import sys
import bisect

from analysis_service import ChordAnalysisService
from audio_analyzer import AudioAnalyzer
from chord_exporter import ChordExporter
from chorddata import ChordData
from chordflask_config import ANALYSIS_DIR_NAME
from filerepr import FileRepr
from media_converter import MediaConverter


class ChordAnalyzer:
    def __init__(self, mp4_filename, data_dir=""):
        if not data_dir:
            dirn = os.path.abspath(os.path.dirname(mp4_filename))
            data_dir = os.path.join(dirn, ANALYSIS_DIR_NAME)
            print("Data path:", data_dir)

        self.file_repr = FileRepr(mp4_filename, data_dir, create=True)
        self.chord_data = ChordData(prefer_flats=True, use_unicode=False)
        self.converter = MediaConverter()
        self.audio_analyzer = AudioAnalyzer(sample_rate=self.chord_data.sr)
        self.exporter = ChordExporter()
        self.analysis_service = ChordAnalysisService(
            converter=self.converter,
            analyzer=self.audio_analyzer,
            exporter=self.exporter,
        )

    def convert_mp4_to_mp3(self):
        self.converter.ensure_mp3(self.file_repr)

    def _extract_chords_vamp(self, y, sr):
        return self.audio_analyzer._extract_chords_vamp(y, sr)

    def _extract_chords_madmom(self, mp3_path):
        return self.audio_analyzer._extract_chords_madmom(mp3_path)

    def analyze_chords(self, use_madmom=False):
        try:
            self.chord_data = self.audio_analyzer.analyze(
                self.file_repr.get("mp3"),
                use_madmom=use_madmom,
            )
            return True
        except Exception as e:
            print(f"Error analyzing chords: {e}")
            return False

    def analyze_chords_check_if_better(self, use_madmom=False):
        return self.analyze_chords(use_madmom=use_madmom)

    def detect_meter(self):
        return self.audio_analyzer.detect_meter(self.file_repr.get("mp3"))

    def play_with_chords(self):
        from mp3player import MP3Player

        def print_chord_at_time(position):
            transposed_chords = self.chord_data.get_chords()
            chord_times = self.chord_data.chord_times
            idx = bisect.bisect_right(chord_times, position) - 1
            if 0 <= idx < len(transposed_chords):
                chords_to_display = [f"{transposed_chords[i][1]:^8}" for i in range(idx, min(idx + 4, len(transposed_chords)))]
                print(f"{position:7.2f} |{'|'.join(chords_to_display)}")
        player = MP3Player(self.file_repr.get("mp3"), position_callback=print_chord_at_time)  # noqa: F841

    def play_mp4_with_chords(self):
        from mp4player import MP4Player

        player = MP4Player(self.file_repr.get(), chord_data=self.chord_data)  # noqa: F841

    def process(self, use_madmom=False):
        self.chord_data = self.analysis_service.ensure_analyzed(
            self.file_repr,
            use_madmom=use_madmom,
        )

    def print_chords(self):
        chords = self.chord_data.get_chords()
        for timestamp, chord_symbol in chords:
            print(f"Time: {timestamp:.2f}s - Chord: {chord_symbol}")
        print("-" * 40)

    def save_chords_as_midi(self):
        self.exporter.write_midi_and_musicxml(self.chord_data, self.file_repr)

    def create_png(self, output_filename="chord_chart.png"):
        self.exporter.write_png(self.chord_data, self.file_repr, output_filename)

    def transpose_chords(self, semitones):
        self.chord_data.transpose(semitones)

    def save_chords_to_file(self):
        self.chord_data.save_to_file(self.file_repr.get("json"))
        print(f"Chord data saved to {self.file_repr.get('json')}")

    def load_chords_from_file(self):
        self.chord_data.load_from_file(self.file_repr.get("json"))
        print(f"Chord data loaded from {self.file_repr.get('json')}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python chordanalyzer.py <mp4_filename> [data_directory] [madmom]")
        sys.exit(1)
    mp4_filename = sys.argv[1]
    data_dir = sys.argv[2] if len(sys.argv) > 2 else ""
    use_madmom = sys.argv[3].lower() in ["true", "1", "yes"] if len(sys.argv) > 3 else False

    analyzer = ChordAnalyzer(mp4_filename, data_dir)
    analyzer.process(use_madmom=use_madmom)

    try:
        transpose_input = input("Enter the number of semitones to transpose (positive for up, negative for down): ").strip()
        if transpose_input:
            transpose_by = int(transpose_input)
            analyzer.transpose_chords(transpose_by)
            analyzer.save_chords_to_file()
    except ValueError as e:
        print(f"Invalid input for transposition: {e}")

    analyzer.create_png("chord_chart.png")

    play_input = input("Do you want to play the video with chords displayed? (y/n): ").strip().lower()
    if play_input == 'y':
        analyzer.play_mp4_with_chords()
