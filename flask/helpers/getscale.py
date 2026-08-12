#!/usr/bin/env python3
import vamp
import librosa
import sys

def calculate_key_with_vamp(mp3_file):
    # Load the audio file in mono format
    audio, sr = librosa.load(mp3_file, sr=44100, mono=True)

    # Use the QM Key Detector plugin
    plugin_key = "qm-vamp-plugins:qm-keydetector"

    # Perform analysis and collect results
    results = vamp.collect(audio, sr, plugin_key)

    # Extract key from the results
    key_info = results['list']

    if key_info:
        detected_key = key_info[0]['label']
        print(f"Detected Key: {detected_key}")
    else:
        print("Key could not be determined.")

# Example usage
calculate_key_with_vamp(sys.argv[1])

