#!/usr/bin/env python3

"""
ChordFlask: Analyze chords from MP4 files, extract them, convert to MIDI/XML, and display during playback.

HOW TO SETUP

1. Create and activate a virtual environment:
   python3 -m venv venv
   source venv/bin/activate

2. Upgrade pip:
   pip install --upgrade pip

2.1. First Upgrade setuptools, wheel, and numpy for better compatibility:
   pip install --upgrade setuptools wheel numpy
   pip install flask-socketio eventlet

3. Install the necessary Python packages:
   pip install Cython ffpyplayer pillow librosa vamp music21 simpleaudio pydub tbb
   pip install pyinstaller pyinstaller-hooks-contrib

4. Install system dependencies:
   sudo apt install cython3 ffmpeg vamp-plugin-sdk midicsv timidity cmake libcairo2-dev python3-tk vim
   sudo apt install python3-venv python3-dev cython3 ffmpeg vamp-plugin-sdk midicsv timidity cmake
   sudo apt install libcairo2-dev build-essential curl libasound2-dev libtbb12 libtbb-dev

8. Freeze installed packages (to save the environment setup):
   pip freeze > requirements.txt

9. Recreate the environment from the saved file:
   a. Create and activate a new virtual environment:
      python3 -m venv venv
      source venv/bin/activate

   b. Install dependencies from the requirements file:
      pip install -r requirements.txt

10. Run the script:
    a. Navigate to the directory where `chordanalyzer.py` is located:
       cd /path/to/your/directory

    b. Run the script with the MP4 file and optional data directory:
       python chordanalyzer.py <mp4_filename> [data_directory]

NOTES:
- The script relies on Vamp plugins to analyze chords and generate music output files (MIDI, XML).
- Ensure you have `ffmpeg` installed in your system as it may be required for `ffpyplayer` to handle video/audio playback.
   sudo apt install ffmpeg

- No need for VLC, and `pygame` is no longer required for any functionality in this setup.
"""

import sys
import os
import vamp
import librosa
import bisect
import gc
from music21 import converter, midi, stream, meter, note, chord as m21_chord, metadata, harmony
from PIL import Image, ImageDraw, ImageFont
import multiprocessing as mp
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from chorddata import ChordData
from chordutils import fix_chord_label, inv_fix_chord_label, detect_tempo_from_audio
from chordflask_config import ANALYSIS_DIR_NAME
from filerepr import FileRepr
from mp3player import MP3Player  # Ensure mp3player.py is available
from mp4player import MP4Player  # Ensure mp4player.py is available

from moviepy.video.io.VideoFileClip import VideoFileClip

class ChordAnalyzer:
    def __init__(self, mp4_filename, data_dir=""):
        """
        Initializes the ChordAnalyzer object, sets up paths for different files using FileRepr.
        :param mp4_filename: The MP4 file to analyze.
        :param data_dir: Directory where output files (MP3, JSON, MIDI, XML) are stored.
        """
        # If no data directory is provided, create a '.chordflask' folder in the same directory as the MP4 file
        if not data_dir:
            dirn = os.path.abspath(os.path.dirname(mp4_filename))
            data_dir = os.path.join(dirn, ANALYSIS_DIR_NAME)
            print("Data path:", data_dir)

        self.file_repr = FileRepr(mp4_filename, data_dir, create=True)  # Initialize FileRepr for managing file paths
        self.chord_data = ChordData(prefer_flats=True, use_unicode=False)

    def convert_mp4_to_mp3(self):
        """Convert MP4 to MP3 using moviepy."""
        #import moviepy.editor as mp_video
        #video = mp_video.VideoFileClip(self.file_repr.get())  # Use FileRepr to get the mp4 file path
        from moviepy.video.io.VideoFileClip import VideoFileClip
        video = VideoFileClip(self.file_repr.get())  # Use FileRepr to get the mp4 file path
        video.audio.write_audiofile(self.file_repr.get("mp3"))
        print(f"MP3 file saved: {self.file_repr.get('mp3')}")

    def analyze_chords(self):
        """Analyze the chords from the audio using Vamp plugin."""
        print(f"Start analyzing: {self.file_repr.get('mp3')}")
        ok = False
        try:

            print(f"Load...",flush=True)
            y, sr = librosa.load(self.file_repr.get("mp3"), sr=self.chord_data.sr, mono=True)

            print(f"Preemphasis...",flush=True)
            y = librosa.effects.preemphasis(y)   # we need this for beat detection

            print(f"Tempo...",flush=True)
            bpm, beat_times= detect_tempo_from_audio(sr=self.chord_data.sr,y=y)
            print("BPM",bpm)
            self.chord_data._bpm,self.chord_data._beat_times=bpm,beat_times
            # Quantize beat times to regular grid
            interval = 60 / bpm
            start = beat_times[0]
            end = beat_times[-1]
            beat_times = [round(start + i * interval, 6) for i in range(int((end - start) / interval) + 1)]

            #print(f"Harmonic...",flush=True)
            #y = librosa.effects.harmonic(y)     # duplicates memory!

            print(f"Chords...",flush=True)
            params = {"useNNLS": 1, "rollon": 0.02, "tuningmode": 0}
            data = vamp.collect(y, sr, "nnls-chroma:chordino", parameters=params)
            y=None
            chords = [{"timestamp": float(e['timestamp']), "chord": e['label']} for e in data['list']]

            # Set the analyzed chords into ChordData
            self.chord_data.set_base_chords(chords,beat_times=beat_times)
            self.chord_data._meter_signature = self.detect_meter()


            ok = True
        except FileNotFoundError as fnf_error:
            print(f"Error: File not found - {fnf_error}")
        except Exception as e:
            print(f"Error analyzing chords: {e}")

        del y, chords, data
        gc.collect()

        if not ok:
            self.chord_data = None
            #self.chord_data._meter_signature = None
            return False
        return True


    def detect_meter(self):
        # Detect the meter (time signature) using the Vamp beat tracker plugin.
        print("Meter...",flush=True)
        y, sr = librosa.load(self.file_repr.get("mp3"))
        data = vamp.collect(y, sr, "qm-vamp-plugins:qm-barbeattracker")
        beats_per_bar = [int(e['label']) for e in data['list']]
        return 4 if beats_per_bar.count(4) > beats_per_bar.count(3) else 3




    def play_with_chords(self):
        """Play the MP3 file and display chords during playback."""
        def print_chord_at_time(position):
            # Get transposed chords
            transposed_chords = self.chord_data.get_chords()
            chord_times = self.chord_data.chord_times
            idx = bisect.bisect_right(chord_times, position) - 1
            if 0 <= idx < len(transposed_chords):
                chords_to_display = [f"{transposed_chords[i][1]:^8}" for i in range(idx, min(idx + 4, len(transposed_chords)))]
                print(f"{position:7.2f} |{'|'.join(chords_to_display)}")

        player = MP3Player(self.file_repr.get("mp3"), position_callback=print_chord_at_time)
        # player.run()  # Start the MP3 player with the chord display

    def play_mp4_with_chords(self):
        """Play the MP4 file and display chords during playback."""
        # Create an instance of MP4Player with the current chords
        player = MP4Player(self.file_repr.get(), chord_data=self.chord_data)
        # player.run()  # Start the MP4 player with the chord display

    def process(self):
        """Convert MP4 to MP3, analyze chords, save results as MusicXML, MIDI, and JSON (chords)."""
        if not os.path.exists(self.file_repr.get("mp3")):
            self.convert_mp4_to_mp3()
        else:
            print(f"MP3 file already exists: {self.file_repr.get('mp3')}")

        if not os.path.exists(self.file_repr.get("json")):
            if self.analyze_chords():
                self.save_chords_to_file()
                self.save_chords_as_midi()
        else:
            print(f"Chord analysis already exists: {self.file_repr.get('json')}")
            self.load_chords_from_file()

    def print_chords(self):
        """Print analyzed chords to the console."""
        chords = self.chord_data.get_chords()
        for timestamp, chord_symbol in chords:
            print(f"Time: {timestamp:.2f}s - Chord: {chord_symbol}")
        print("-" * 40)

    def save_chords_as_midi(self):
        """Save the chords as MusicXML and MIDI files."""
        score = stream.Score(metadata=metadata.Metadata(title="Generated Chords", composer="Chord Conversion Script"))
        part = stream.Part()
        time_signature = f"{self.chord_data._meter_signature}/4" if self.chord_data._meter_signature else "4/4"
        part.append(meter.TimeSignature(time_signature))
        measure = stream.Measure()
        chord_count = 0
        chords_per_bar = int(self.chord_data._meter_signature) if self.chord_data._meter_signature else 4

        chords = self.chord_data.get_chords()
        for timestamp, chord_label in chords:
            try:
                fixed_chord_label = fix_chord_label(chord_label)
                chord_symbol = harmony.ChordSymbol(fixed_chord_label)
                chord_notes = m21_chord.Chord([p for p in chord_symbol.pitches], quarterLength=1.0)
                measure.append(chord_notes)
            except Exception:
                measure.append(note.Rest(quarterLength=1.0))

            chord_count += 1
            if chord_count == chords_per_bar:
                part.append(measure)
                measure = stream.Measure()
                chord_count = 0

        if measure.notesAndRests:
            part.append(measure)

        score.append(part)
        score.write('musicxml', fp=self.file_repr.get("xml"))
        print(f"MusicXML file saved: {self.file_repr.get('xml')}")

        midi_score = converter.parse(self.file_repr.get("xml"))
        mf = midi.translate.music21ObjectToMidiFile(midi_score)
        mf.open(self.file_repr.get("mid"), 'wb')
        mf.write()
        mf.close()
        print(f"MIDI file saved: {self.file_repr.get('mid')}")

        del score, mf

    def create_png(self, output_filename="chord_chart.png"):
        """Create a PNG image displaying the analyzed chords in a grid format."""
        output_filepath = self.file_repr.get(output_filename)
        cell_width, cell_height, font_size, padding = 100, 100, 36, 10
        columns = 8
        chords = self.chord_data.get_chords()
        rows = (len(chords) // columns) + 1
        img = Image.new("RGB", (columns * cell_width, rows * cell_height), "white")
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except IOError:
            font = ImageFont.load_default()

        for idx, (timestamp, chord_label) in enumerate(chords):
            col, row = idx % columns, idx // columns
            x, y = col * cell_width + padding, row * cell_height + padding
            draw.rectangle([col * cell_width, row * cell_height, (col + 1) * cell_width, (row + 1) * cell_height],
                           outline="black", width=2)
            bbox = draw.textbbox((0, 0), chord_label, font=font)
            text_width, text_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text((x + (cell_width - text_width) / 2, y + (cell_height - text_height) / 2),
                      chord_label, fill="black", font=font)

        img.save(output_filepath)
        print(f"Chord chart saved as: {output_filepath}")

    def transpose_chords(self, semitones):
        """Transposes the current chords by a given number of semitones."""
        # Set the transposition amount in ChordData
        self.chord_data.transpose(semitones)
        # Transposed chords are automatically handled by ChordData

    def save_chords_to_file(self):
        """Save the analyzed chords to a JSON file."""
        self.chord_data.save_to_file(self.file_repr.get("json"))
        print(f"Chord data saved to {self.file_repr.get('json')}")

    def load_chords_from_file(self):
        """Load chords from a JSON file."""
        self.chord_data.load_from_file(self.file_repr.get("json"))
        print(f"Chord data loaded from {self.file_repr.get('json')}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python chordanalyzer.py <mp4_filename> [data_directory]")
        sys.exit(1)
    mp4_filename = sys.argv[1]
    data_dir = sys.argv[2] if len(sys.argv) > 2 else ""

    analyzer = ChordAnalyzer(mp4_filename, data_dir)
    analyzer.process()

    # Input handling for transposition
    try:
        transpose_input = input("Enter the number of semitones to transpose (positive for up, negative for down): ").strip()
        if transpose_input:
            transpose_by = int(transpose_input)
            analyzer.transpose_chords(transpose_by)
            analyzer.save_chords_to_file()
    except ValueError as e:
        print(f"Invalid input for transposition: {e}")

    # Create the chord chart image
    analyzer.create_png("chord_chart.png")

    # Optionally play the MP4 with chords displayed
    play_input = input("Do you want to play the video with chords displayed? (y/n): ").strip().lower()
    if play_input == 'y':
        analyzer.play_mp4_with_chords()
