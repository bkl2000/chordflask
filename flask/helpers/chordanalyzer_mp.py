#!/usr/bin/env python3

"""
ChordFlask: Analyze chords from MP4 files, extract them, convert to MIDI/XML, and display during playback.

HOW TO SETUP

1. Create and activate a virtual environment:
   python3 -m venv venv
   source venv/bin/activate

2. Upgrade pip:
   pip install --upgrade pip

3. Install the necessary Python packages:
   pip install moviepy librosa vamp music21 pillow
   sudo apt install ffmpeg 
   sudo apt-get install gstreamer1.0-libav gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly
   sudo apt install libcairo2-dev pkg-config python3-dev
   sudo apt-get install libgirepository1.0-dev gir1.2-glib-2.0
   sudo apt-get install libasound2-dev

4. Install additional dependencies for the `vamp` plugin and MIDI functionality:
   a. For Python:
      pip install vamp music21
   b. Install Vamp Plugin SDK and other system dependencies on Linux:
      sudo apt install vamp-plugin-sdk midicsv timidity cmake

5. Install additional tools for MIDI conversion:
   sudo apt install timidity

6. Upgrade setuptools, wheel, and numpy for better compatibility:
   pip install --upgrade setuptools wheel numpy

7. Ensure the `mp3player.py` and `mp4player.py` files are in the `src` directory:
   Copy the `mp3player.py` and `mp4player.py` files to the `src` directory where `chordanalyzer.py` is located.

8. Freeze installed packages (to save the environment setup):
   pip freeze > requirements.txt

9. Recreate the environment from the saved file:
   a. Create and activate a new virtual environment:
      python3 -m venv venv
      source venv/bin/activate

   b. Install dependencies from the requirements file:
      pip install -r requirements.txt

10. Run the script:
    a. Navigate to the `src` directory:
       cd /path/to/new/venv/src

    b. Run the script with the MP4 file and optional data directory:
       python chordanalyzer.py <mp4_filename> [data_directory]

NOTES:
- The script relies on Vamp plugins to analyze chords and generate music output files (MIDI, XML).
- Ensure you have `ffmpeg` installed in your system as it may be required for `moviepy` to handle audio conversion.
   sudo apt install ffmpeg
"""

import sys
import os
import vamp
import librosa
import json
from music21 import converter, midi, stream, meter, chord as m21_chord, harmony, note, metadata
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from chordflask_config import ANALYSIS_DIR_NAME
from mp3player import MP3Player  # Import MP3Player from mp3player.py
from mp4player import MP4Player  # Import MP4Player from mp4player.py
import multiprocessing as mp


class ChordAnalyzer:
    def __init__(self, mp4_filename, data_dir=ANALYSIS_DIR_NAME):
        self.mp4_filename = mp4_filename
        self.data_dir = data_dir
        self.chords = []
        self.chord_times = []
        self.meter_signature = None
        self.__initialize()

    def __initialize(self):
        """Initialize filenames and ensure the data directory exists."""
        self.base_filename = self._generate_base_filename(self.mp4_filename)
        os.makedirs(self.data_dir, exist_ok=True)
        self.mp3_filename = os.path.join(self.data_dir, f"{self.base_filename}.mp3")
        self.xml_filename = os.path.join(self.data_dir, f"{self.base_filename}.xml")
        self.midi_filename = os.path.join(self.data_dir, f"{self.base_filename}.mid")
        self.json_filename = os.path.join(self.data_dir, f"{self.base_filename}.json")

    def _generate_base_filename(self, mp4_filename):
        return os.path.splitext(os.path.basename(mp4_filename))[0]

    def convert_mp4_to_mp3(self):
        """Convert MP4 to MP3 using moviepy in a separate process."""
        def convert():
            import moviepy.editor as mp
            video = mp.VideoFileClip(self.mp4_filename)
            video.audio.write_audiofile(self.mp3_filename)
            print(f"MP3 file saved: {self.mp3_filename}")

        conversion_process = mp.Process(target=convert)
        conversion_process.start()
        conversion_process.join()

    def analyze_chunk(self, audio_chunk, sr, plugin="nnls-chroma:chordino"):
        """Analyze a chunk of audio for chords using Vamp."""
        params = {"useNNLS": 1, "rollon": 0.02, "tuningmode": 0}
        data = vamp.collect(audio_chunk, sr, plugin, parameters=params)
        return [(float(e['timestamp']), e['label']) for e in data['list']]

    def analyze_chords(self, num_processes=4):
        """Analyze the chords from the audio using Vamp plugin in parallel across multiple cores."""
        # Load the entire audio file
        y, sr = librosa.load(self.mp3_filename, sr=22050, mono=True)
        
        # Split audio into chunks for multiprocessing
        chunk_size = len(y) // num_processes
        audio_chunks = [y[i * chunk_size:(i + 1) * chunk_size] for i in range(num_processes)]
        
        # Use multiprocessing to analyze each chunk in parallel
        with mp.Pool(processes=num_processes) as pool:
            results = pool.starmap(self.analyze_chunk, [(chunk, sr) for chunk in audio_chunks])
        
        # Flatten the list of results
        self.chords = [item for sublist in results for item in sublist]
        
        # Adjust timestamps for each chunk
        for i, chunk_result in enumerate(results):
            time_offset = i * (chunk_size / sr)  # Calculate the time offset for each chunk
            for j in range(len(chunk_result)):
                results[i][j] = (chunk_result[j][0] + time_offset, chunk_result[j][1])
        self.chord_times = [float(chord[0]) for chord in self.chords]

        self.meter_signature = self.detect_meter()

    def detect_meter(self):
        """Detect the meter (time signature) using the Vamp beat tracker plugin."""
        y, sr = librosa.load(self.mp3_filename)
        data = vamp.collect(y, sr, "qm-vamp-plugins:qm-barbeattracker")
        beats_per_bar = [int(e['label']) for e in data['list']]
        return 4 if beats_per_bar.count(4) > beats_per_bar.count(3) else 3

    def fix_chord_label(self, chord_label):
        """Fix the chord labels to be compatible with music21."""
        flat_mappings = {'Ab': 'A-', 'Bb': 'B-', 'Cb': 'C-', 'Db': 'D-', 'Eb': 'E-', 'Fb': 'F-', 'Gb': 'G-'}
        sharp_mappings = {'A#': 'A#', 'B#': 'B#', 'C#': 'C#', 'D#': 'D#', 'E#': 'E#', 'F#': 'F#', 'G#': 'G#'}
        chord_label = chord_label.replace('maj7', 'M7').replace('min', 'm').replace('dim', 'o').replace('aug', '+')
        chord_label = chord_label.replace('sus4', 'sus').replace('sus2', 'sus')
        chord_label = chord_label.replace('m7b5', 'ø7').replace('7#5', '7+5').replace('7b5', '7-5')
        chord_label = chord_label.replace('7#9', '7+9').replace('7b9', '7-9')

        for flat, replacement in flat_mappings.items():
            chord_label = chord_label.replace(flat, replacement)
        for sharp, replacement in sharp_mappings.items():
            chord_label = chord_label.replace(sharp, replacement)

        if '/' in chord_label:
            base, bass = chord_label.split('/')
            return f"{self.fix_chord_label(base)}/{self.fix_chord_label(bass)}"

        return chord_label

    def play_with_chords(self):
        """Play the MP3 file and display chords during playback."""
        def print_chord_at_time(position):
            for idx, timestamp in enumerate(self.chord_times):
                if timestamp <= position < self.chord_times[min(idx + 1, len(self.chord_times) - 1)]:
                    chords_to_display = [f"{self.chords[i][1]:^8}" for i in range(idx, min(idx + 4, len(self.chords)))]
                    print(f"{position:7.2f} |{'|'.join(chords_to_display)}")
                    break

        player = MP3Player(self.mp3_filename, print_chord_at_time)
        player.run()

    def play_mp4_with_chords(self):
        """Play the MP4 file and display chords during playback."""
        def print_chord_at_time(position):
            for idx, timestamp in enumerate(self.chord_times):
                if timestamp <= position < self.chord_times[min(idx + 1, len(self.chord_times) - 1)]:
                    chords_to_display = [f"{self.chords[i][1]:^8}" for i in range(idx, min(idx + 4, len(self.chords)))]
                    print(f"{position:7.2f} |{'|'.join(chords_to_display)}")
                    break

        player = MP4Player(self.mp4_filename, position_callback=print_chord_at_time)

    def process(self):
        """Convert MP4 to MP3, analyze chords, save results as MusicXML, MIDI, and JSON (chords)."""
        self.convert_mp4_to_mp3()
        self.analyze_chords()
        self.print_chords()
        self.save_chords_to_file(self.json_filename)
        self.save_chords_as_midi()

    def print_chords(self):
        """Print analyzed chords to the console."""
        for timestamp, chord_label in self.chords:
            print(f"Time: {timestamp:.2f}s - Chord: {chord_label}")
        print("-" * 40)

    def save_chords_as_midi(self):
        """Save the chords as MusicXML and MIDI files."""
        score = stream.Score(metadata=metadata.Metadata(title="Generated Chords", composer="Chord Conversion Script"))
        part = stream.Part()
        part.append(meter.TimeSignature(f"{self.meter_signature}/4"))
        measure, chord_count, chords_per_bar = stream.Measure(), 0, 4 if self.meter_signature == 4 else 3

        for _, chord_label in self.chords:
            try:
                fixed_chord_label = self.fix_chord_label(chord_label)
                chord_symbol = harmony.ChordSymbol(fixed_chord_label)
                chord_notes = m21_chord.Chord([p for p in chord_symbol.pitches], quarterLength=1.0)
                measure.append(chord_notes)
            except Exception:
                measure.append(note.Rest(quarterLength=1.0))

            chord_count += 1
            if chord_count == chords_per_bar:
                part.append(measure)
                measure, chord_count = stream.Measure(), 0

        if measure.notesAndRests:
            part.append(measure)

        score.append(part)
        score.write('musicxml', fp=self.xml_filename)
        print(f"MusicXML file saved: {self.xml_filename}")

        midi_score = converter.parse(self.xml_filename)
        mf = midi.translate.music21ObjectToMidiFile(midi_score)
        mf.open(self.midi_filename, 'wb')
        mf.write()
        mf.close()
        print(f"MIDI file saved: {self.midi_filename}")

    def create_png(self, output_filename="chord_chart.png"):
        """Create a PNG image displaying the analyzed chords in a grid format."""
        output_filepath = os.path.join(self.data_dir, output_filename)
        cell_width, cell_height, font_size, padding = 100, 100, 36, 10
        columns = 8  # Now assigned correctly before use
        rows = (len(self.chords) // columns) + 1
        img = Image.new("RGB", (columns * cell_width, rows * cell_height), "white")
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except IOError:
            font = ImageFont.load_default()

        for idx, (_, chord_label) in enumerate(self.chords):
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

    def transpose_chords1(self, chord_list, semitones=0):
        """Transpose a given list of chords by the specified number of semitones, ignoring invalid chords."""
        if semitones == 0:
            return chord_list
        print(f"Transposing chords by {semitones} semitones")
        transposed_chords = []
        for timestamp, chord_label in chord_list:
            try:
                fixed_label = self.fix_chord_label(chord_label)
                # Skip 'N' or any other invalid chord labels
                if fixed_label == 'N':
                    transposed_chords.append((timestamp, 'N'))  # Keep it as 'N' (no chord)
                    continue
                transposed_chord = harmony.ChordSymbol(fixed_label).transpose(semitones).figure
                transposed_chords.append((timestamp, self.fix_chord_label(transposed_chord)))
            except ValueError as e:
                print(f"Skipping invalid chord '{chord_label}' at {timestamp:.2f}s: {e}")
                transposed_chords.append((timestamp, 'N'))  # Handle invalid chord gracefully
        return transposed_chords

    def transpose_chords(self, semitones):
        """Transposes the current chords by a given number of semitones."""
        self.chords = self.transpose_chords1(self.chords, semitones)

    def save_chords_to_file(self, file_path):
        """Save the analyzed chords to a JSON file."""
        with open(file_path, 'w') as f:
            json.dump([{'timestamp': t, 'chord': c} for t, c in self.chords], f, indent=4)
        print(f"Chords saved to {file_path}")

    def load_chords_from_file(self, file_path):
        """Load chords from a JSON file and restore them to self.chords."""
        with open(file_path, 'r') as f:
            chord_data = json.load(f)

        self.chords = [(entry['timestamp'], entry['chord']) for entry in chord_data]
        self.chord_times = [entry['timestamp'] for entry in chord_data]
        print(f"Chords loaded from {file_path}")


if __name__ == "__main__":
    mp4_filename = sys.argv[1]
    data_dir = sys.argv[2] if len(sys.argv) > 2 else ANALYSIS_DIR_NAME

    analyzer = ChordAnalyzer(mp4_filename, data_dir)
    analyzer.process()

    # Handle transposition input
    try:
        transpose_input = input("Enter the number of semitones to transpose (positive for up, negative for down): ").strip()
        if transpose_input:
            transpose_by = int(transpose_input)
            analyzer.transpose_chords(transpose_by)
    except ValueError as e:
        print(f"Invalid input for transposition: {e}")

    analyzer.create_png("chord_chart.png")
    analyzer.play_mp4_with_chords()
