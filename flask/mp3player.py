import multiprocessing as mp
import simpleaudio as sa
from pydub import AudioSegment
import time
import tempfile

class MP3Player:
    def __init__(self, mp3_file, position_callback, chord_data=None):
        self.mp3_file = mp3_file
        self.position_callback = position_callback
        self.queue = mp.Queue()
        self.chord_data = chord_data  # Add ChordData instance to manage chords during playback

    def _play_audio(self, mp3_file, queue):
        # Load MP3 file using pydub
        audio = AudioSegment.from_mp3(mp3_file)

        # Export to a temporary WAV file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
            audio.export(wav_file.name, format="wav")

        # Load the WAV data from the file using simpleaudio
        wave_obj = sa.WaveObject.from_wave_file(wav_file.name)
        play_obj = wave_obj.play()  # Play the audio file

        # Track the position in the queue every 250ms
        start_time = time.time()
        duration = len(audio) / 1000.0  # Audio duration in seconds

        while time.time() - start_time < duration:
            elapsed_time = time.time() - start_time
            queue.put(elapsed_time)
            time.sleep(0.25)

        play_obj.stop()  # Stop playback
        queue.put(None)  # Signal end of playback

    def _read_queue(self, queue):
        while True:
            try:
                position = queue.get_nowait()
                if position is None:
                    break

                # Use the position callback to show current position or chord information
                self.position_callback(position)

                # If we have chord data, we can also print the relevant chord
                if self.chord_data:
                    self.display_chord_at_position(position)

            except mp.queues.Empty:
                time.sleep(0.08)  # Avoid busy waiting

    def display_chord_at_position(self, position):
        """Display chord information for the current playback position."""
        if not self.chord_data.chords:
            return

        for chord in self.chord_data.chords:
            if chord["timestamp"] <= position:
                print(f"Chord at {position:.2f}s: {chord['chord']}")
            else:
                break

    def run(self):
        # Create and start the process for playing the MP3 file
        audio_process = mp.Process(target=self._play_audio, args=(self.mp3_file, self.queue))
        audio_process.start()

        # Create and start the process for reading the queue
        read_process = mp.Process(target=self._read_queue, args=(self.queue,))
        read_process.start()

        # Wait for the processes to finish
        audio_process.join()
        read_process.join()

# Function to be called for displaying position
def print_position(position):
    print(f"Current position: {position:.2f} seconds")

