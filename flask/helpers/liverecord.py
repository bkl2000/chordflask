#!/usr/bin/env python3

"""
LiveRecord: Plays audio from a WAV file or captures from the microphone,
performs live chord analysis, and displays chords in sync with playback or recording.
"""

import os
import sys
import time
import numpy as np
import sounddevice as sd
import threading
import multiprocessing as mp
from queue import Queue, Empty, Full  # Import Empty exception here
import signal
import traceback

# Disable Numba JIT globally before importing librosa
os.environ['NUMBA_DISABLE_JIT'] = '1'

# Parameters for live recording and analysis
SAMPLERATE = 22050     # Sample rate for recording and playback
CHANNELS = 1           # Mono audio

def analyze_chords(samplerate, analysis_queue, result_queue, running_flag, vamp_path):
    """
    Analyzes audio chunks from the analysis queue and sends results to the result queue.
    """
    import os
    import numpy as np
    import librosa
    import vamp
    import traceback

    # Set VAMP_PATH in the child process
    os.environ['VAMP_PATH'] = vamp_path

    # Verify VAMP_PATH
    if not os.path.isdir(vamp_path):
        print(f"Error: VAMP_PATH '{vamp_path}' is not a valid directory.")
        result_queue.put(None)
        return

    # Optionally, print VAMP_PATH for debugging
    print(f"[analyze_chords] VAMP_PATH set to: {os.environ['VAMP_PATH']}")

    while running_flag.value:
        try:
            timestamp, audio_chunk = analysis_queue.get(timeout=0.5)
            if audio_chunk is None:
                result_queue.put(None)  # End signal for the result queue
                print("DONE!", flush=True)
                break  # End of data signal

            # Ensure audio_chunk is in correct format
            audio_chunk = np.ascontiguousarray(audio_chunk)
            if audio_chunk.ndim > 1:
                audio_chunk = audio_chunk.flatten()

            # Debugging: Print the shape of the audio chunk
            #print(f"[analyze_chords] Processing chunk with shape: {audio_chunk.shape}", flush=True)

            # Apply pre-emphasis for better analysis
            audio_chunk = librosa.effects.preemphasis(audio_chunk)
            audio_chunk = librosa.effects.harmonic(audio_chunk)

            # Perform chord analysis on the buffer
            params = {"useNNLS": 1, "rollon": 0.02, "tuningmode": 0}
            data = vamp.collect(audio_chunk, samplerate, "nnls-chroma:chordino", parameters=params)

            if not data or 'list' not in data:
                #print("[analyze_chords] No data returned from Vamp plugin.", flush=True)
                continue

            #print("[analyze_chords] Chord data received from Vamp plugin.", flush=True)

            chords = [
                {"timestamp": timestamp + float(e['timestamp']), "chord": e['label']}
                for e in data['list']
            ]

            # Debugging: Print the raw chords before filtering
            #print(f"[analyze_chords] Raw chords: {chords}", flush=True)

            filtered_chords = _filter_and_extrapolate(chords)

            # Debugging: Print the filtered chords
            #print(f"[analyze_chords] Filtered chords: {filtered_chords}", flush=True)

            result_queue.put(filtered_chords)

        except Empty:
            # No data available; continue waiting
            continue
        except Exception as e:
            print(f"Error in analyze_chords: {e}")
            traceback.print_exc()
            break

def _filter_and_extrapolate(chords):
    """Remove 'N' entries and replace them with the last recognized chord."""
    filtered_chords = []
    last_chord = None

    for entry in chords:
        if entry["chord"] != "N":
            last_chord = entry["chord"]
            filtered_chords.append(entry)
        elif last_chord:
            # Replace 'N' with the last recognized chord
            filtered_chords.append({"timestamp": entry["timestamp"], "chord": last_chord})

    return filtered_chords

def display_chords(mode, result_queue, start_time, display_offset, running_flag):
    """
    Continuously display chords from the result queue.

    - In 'mic' mode, display chords as soon as they are available (non-blocking).
    - In 'file' mode, synchronize chord display with audio playback.
    - Only display chords when they change from the previous chord.
    """
    import time
    import traceback

    last_chord = None  # Keep track of the last displayed chord

    while running_flag.value:
        try:
            # Use non-blocking get in 'mic' mode, blocking get in 'file' mode
            if mode == 'mic':
                chords = result_queue.get_nowait()
            else:
                chords = result_queue.get()

            if chords is None:
                break  # End of data signal

            for chord in chords:
                current_chord = chord['chord']
                # Only display if the chord has changed
                if current_chord != last_chord:
                    chord_time = chord['timestamp'] - start_time + display_offset
                    display_time = max(chord_time, 0.0)

                    if mode == 'mic':
                        # Display the chord immediately
                        print(f"Chord: {current_chord}")
                    else:
                        # Synchronize chord display with playback
                        current_time = time.time() - start_time
                        sleep_time = chord_time - current_time
                        if sleep_time > 0:
                            time.sleep(sleep_time)
                        print(f"Time: {display_time:.2f}s - Chord: {current_chord}")
                    last_chord = current_chord  # Update the last displayed chord
        except Empty:
            # Sleep briefly in 'mic' mode to prevent high CPU usage
            if mode == 'mic':
                time.sleep(0.01)
                continue
        except Exception as e:
            print(f"Error in display_chords: {e}")
            traceback.print_exc()
            break

class LiveChordAnalyzer:
    def __init__(self, audio_source=None, samplerate=SAMPLERATE, channels=CHANNELS, vamp_path=None):
        """
        Initializes the LiveChordAnalyzer with the specified audio source, sample rate, and channels.

        :param audio_source: Path to an MP3 file, or None to use the microphone.
        :param samplerate: Sample rate for analysis and playback.
        :param channels: Number of audio channels.
        :param vamp_path: Path to the Vamp plugins directory.
        """
        self.samplerate = samplerate
        self.channels = channels
        self.audio_source = audio_source
        self.wav_path = None
        self.playback_queue = Queue(maxsize=300)  # Thread-safe queue for playback
        self.analysis_queue = mp.Queue()         # Process-safe queue for analysis
        self.result_queue = mp.Queue()           # Process-safe queue for analysis results
        self.running = True                      # Control variable for stopping the microphone recording
        self.vamp_path = vamp_path or os.environ.get('VAMP_PATH', '/usr/local/lib/vamp')  # Vamp plugin path

        # Set mode-specific attributes based on whether an audio source (file) is provided
        self.mode = 'file' if audio_source else 'mic'

        if self.audio_source:
            self.wav_path = self._prepare_audio_source(audio_source)
        else:
            self.sample_count = 0                # Initialize sample counter for microphone mode

        # Set mode-specific attributes
        self.buffer_duration = 1 if self.mode == 'file' else 1  # 0.2s for file, 0.5s for mic
        self.display_offset  = -1.0 if self.mode == 'file' else 0.0  # Offset slightly earlier in file mode

        # Store thread and process references for proper shutdown
        self.threads = []
        self.processes = []

    def _prepare_audio_source(self, audio_path):
        """Convert audio file to WAV if necessary and return the path."""
        from pydub import AudioSegment  # Import inside function
        if audio_path.endswith(".mp3"):
            # Convert MP3 to WAV
            sound = AudioSegment.from_mp3(audio_path)
            wav_path = audio_path.replace(".mp3", ".wav")
            sound.export(wav_path, format="wav")
            print(f"Converted {audio_path} to WAV: {wav_path}")
            return wav_path
        elif audio_path.endswith(".wav"):
            # Already a WAV file
            return audio_path
        else:
            raise ValueError("Unsupported audio format. Please provide an MP3 or WAV file.")

    def load_audio_chunks(self):
        """Loads audio chunks into the playback and analysis queues from a WAV file."""
        import librosa
        y, _ = librosa.load(self.wav_path, sr=self.samplerate, mono=True)
        chunk_samples = int(self.buffer_duration * self.samplerate)

        start = 0
        while start < len(y) and self.running:
            end = start + chunk_samples
            audio_chunk = y[start:end]

            # Pad the last chunk if it's shorter than expected
            if len(audio_chunk) < chunk_samples:
                audio_chunk = np.pad(audio_chunk, (0, chunk_samples - len(audio_chunk)))

            timestamp = start / self.samplerate + self.start_time  # Adjust timestamp to absolute time

            # Put chunk into playback queue
            try:
                self.playback_queue.put(audio_chunk, timeout=0.5)  # Timeout after 0.5 seconds
            except Full:
                #print("Warning: playback_queue full, skipping chunk to prevent blocking")
                pass

            # Put chunk into analysis queue with timestamp
            try:
                self.analysis_queue.put((timestamp, audio_chunk), timeout=0.5)
            except Full:
                print("Warning: analysis_queue full, skipping chunk to prevent blocking")
                pass

            start += chunk_samples

        # Signal end of data
        self.playback_queue.put(None)
        self.analysis_queue.put((None, None))

    def play_audio(self):
        """Continuously plays audio chunks from the playback queue."""
        with sd.OutputStream(samplerate=self.samplerate, channels=self.channels, dtype='float32') as stream:
            while self.running:
                try:
                    audio_chunk = self.playback_queue.get()
                    if audio_chunk is None:
                        break  # End of data signal
                    stream.write(audio_chunk.astype(np.float32))
                except Exception as e:
                    print(f"Error in play_audio: {e}")
                    break

    def audio_callback(self, indata, frames, time_info, status):
        """
        Callback function for audio input stream. Captures audio and feeds it into the analysis queue.
        """
        if not self.running:
            raise sd.CallbackStop()

        # Calculate timestamp based on sample count
        timestamp = self.sample_count / self.samplerate + self.start_time
        self.sample_count += frames

        # Copy the input data to avoid referencing the same memory
        audio_chunk = np.copy(indata[:, 0])

        # Put the audio chunk into the analysis queue with the timestamp
        self.analysis_queue.put((timestamp, audio_chunk))

    def stop(self):
        """Gracefully stop all threads and processes."""
        print("\nStopping...")
        self.running = False
        self.running_flag.value = False  # Set the shared flag to False

        # Send termination signals to queues
        self.playback_queue.put(None)
        self.analysis_queue.put((None, None))
        self.result_queue.put(None)

        # Join threads
        for thread in self.threads:
            if thread.is_alive():
                thread.join()

        # Terminate and join processes
        for process in self.processes:
            if process.is_alive():
                process.terminate()
                process.join()

        print("All threads and processes have been stopped.")

    def start(self):
        """Starts live chord analysis from the provided audio source or microphone."""
        self.start_time = time.time()  # Record the start time once at the beginning
        self.running_flag = mp.Value('b', True)  # Shared boolean value to control processes

        if self.mode == 'file':
            print(f"Starting chord analysis from file: {self.audio_source}")

            # Start loading audio chunks in a separate thread
            print("Starting audio chunk loader")
            loader_thread = threading.Thread(target=self.load_audio_chunks)
            loader_thread.start()
            self.threads.append(loader_thread)

            # Start audio playback in a separate thread
            print("Starting playback thread")
            playback_thread = threading.Thread(target=self.play_audio)
            playback_thread.start()
            self.threads.append(playback_thread)

            # Start chord analysis in a separate process
            print("Starting chord analysis process")
            analysis_process = mp.Process(target=analyze_chords, args=(
                self.samplerate,
                self.analysis_queue,
                self.result_queue,
                self.running_flag,
                self.vamp_path,  # Pass vamp_path to the process
            ))
            analysis_process.start()
            self.processes.append(analysis_process)

            # Start chord display in a separate process
            print("Starting chord display process")
            display_process = mp.Process(target=display_chords, args=(
                self.mode,
                self.result_queue,
                self.start_time,
                self.display_offset,
                self.running_flag,
            ))
            display_process.start()
            self.processes.append(display_process)

            # Wait for all threads and processes to complete
            try:
                while self.running:
                    time.sleep(0.1)
            except KeyboardInterrupt:
                self.stop()

            print("All Processes completed")

            # Join threads and processes
            for thread in self.threads:
                thread.join()
            for process in self.processes:
                process.join()

        elif self.mode == 'mic':
            print("Starting live chord analysis from the microphone...")

            self.sample_count = 0  # Initialize sample counter for microphone mode

            # Start chord analysis in a separate process
            print("Starting chord analysis process")
            analysis_process = mp.Process(target=analyze_chords, args=(
                self.samplerate,
                self.analysis_queue,
                self.result_queue,
                self.running_flag,
                self.vamp_path,  # Pass vamp_path to the process
            ))
            analysis_process.start()
            self.processes.append(analysis_process)

            # Start chord display in a separate process
            print("Starting chord display process")
            display_process = mp.Process(target=display_chords, args=(
                self.mode,
                self.result_queue,
                self.start_time,
                self.display_offset,
                self.running_flag,
            ))
            display_process.start()
            self.processes.append(display_process)

            # Open the audio input stream
            def run_mic():
                with sd.InputStream(
                    channels=self.channels,
                    samplerate=self.samplerate,
                    callback=self.audio_callback,
                    blocksize=int(self.samplerate * self.buffer_duration),
                ):
                    print("Recording... Press Ctrl+C to stop.")
                    while self.running:
                        time.sleep(0.1)

            try:
                run_mic()
            except KeyboardInterrupt:
                self.stop()

            # Join processes
            for process in self.processes:
                process.join()

            print("Chord analysis stopped.")

        else:
            print("Invalid mode.")

if __name__ == "__main__":
    # Set the multiprocessing start method to 'spawn' for better compatibility
    mp.set_start_method('spawn')

    # Check for an optional audio file path argument
    audio_source = sys.argv[1] if len(sys.argv) > 1 else None

    # Optionally, allow the user to specify the VAMP_PATH as a second argument
    # Usage: python3 liverecord.py path/to/audiofile.mp3 /path/to/vamp/plugins/
    vamp_path = sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser("~/.vamp/")

    # Initialize the analyzer with the specified VAMP_PATH
    analyzer = LiveChordAnalyzer(audio_source=audio_source, vamp_path=vamp_path)

    # Define signal handler for graceful shutdown
    def signal_handler(sig, frame):
        analyzer.stop()
        sys.exit(0)

    # Register signal handler
    signal.signal(signal.SIGINT, signal_handler)

    try:
        analyzer.start()
    except KeyboardInterrupt:
        analyzer.stop()

