#!/usr/bin/env python3

import sys
import librosa
import numpy as np
import glob

def analyze_pitch_variation(file_path, threshold=0.1):
    # Load the MP3 file
    y, sr = librosa.load(file_path, sr=None)

    # Extract pitch using librosa
    pitches, magnitudes = librosa.piptrack(y=y, sr=sr)

    # Calculate pitch variation
    pitch_values = []
    for t in range(pitches.shape[1]):
        index = magnitudes[:, t].argmax()
        pitch = pitches[index, t]
        if pitch > 0 and magnitudes[index, t] > 0.1:  # Avoid low magnitude values
            pitch_values.append(pitch)

    # Debug output
    print(f"Number of pitch values collected: {len(pitch_values)}")
    if len(pitch_values) == 0:
        return "No valid pitch values found."

    # Calculate mean, standard deviation, and variance of pitch values
    pitch_array = np.array(pitch_values)
    mean_pitch = np.mean(pitch_array)
    std_dev_pitch = np.std(pitch_array)
    variance_pitch = np.var(pitch_array)

    print(f"Mean Pitch: {mean_pitch:.2f} Hz")
    print(f"Standard Deviation: {std_dev_pitch:.2f} Hz")
    print(f"Variance: {variance_pitch:.2f} Hz^2")

    # Check if the standard deviation or variance is below the threshold
    if std_dev_pitch < threshold:
        return "The pitch variation is very low. The audio may have used pitch correction tools like Auto-Tune."
    else:
        return "The pitch variation is normal. The audio may not have used pitch correction tools."

# Check command line arguments
if len(sys.argv) != 2:
    print("Usage: python analyze_pitch.py <directory_path>")
    sys.exit(1)

# Analyze the pitch variation
for filename in glob.glob(f"{sys.argv[1]}/*.mp3"):
    print()
    print(f"Analyzing: {filename}")
    print()
    result = analyze_pitch_variation(filename)
    print(result)

