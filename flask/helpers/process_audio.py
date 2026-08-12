#!/usr/bin/env python3

import sys
import librosa
import numpy as np
from pydub import AudioSegment

def process_audio(input_file, output_file, conv_type):
    """
    Process the audio file to extract vocals or instrumental sound based on the conversion type.

    Args:
        input_file (str): Path to the input MP3 file.
        output_file (str): Path to save the processed MP3 file.
        conv_type (str): Conversion type ('vocals' or 'instrumental').
    """
    # Load the audio file
    y, sr = librosa.load(input_file, sr=None, mono=False)
    
    # Perform Harmonic-Percussive Source Separation (HPSS)
    S_full, phase = librosa.magphase(librosa.stft(y.mean(axis=0)))
    S_filter = librosa.decompose.nn_filter(S_full, aggregate=np.median, metric='cosine', width=int(librosa.time_to_frames(2, sr=sr)))
    S_filter = np.minimum(S_full, S_filter)
    
    # Generate soft masks for vocals and instrumental
    margin_i, margin_v = 2, 10
    power = 2
    mask_v = librosa.util.softmask(S_full - S_filter, margin_v * S_filter, power=power)
    mask_i = librosa.util.softmask(S_filter, margin_i * (S_full - S_filter), power=power)
    
    S_foreground = mask_v * S_full  # Vocals
    S_background = mask_i * S_full  # Instrumental
    
    # Select the appropriate output based on conversion type
    if conv_type == 'vocals':
        output_audio = librosa.istft(S_foreground * phase)
    elif conv_type == 'instrumental':
        output_audio = librosa.istft(S_background * phase)
    else:
        raise ValueError("Invalid conversion type. Use 'vocals' or 'instrumental'.")
    
    # Convert the processed audio to an AudioSegment
    audio_segment = AudioSegment(
        (output_audio * 32767).astype(np.int16).tobytes(),
        frame_rate=sr,
        sample_width=2,
        channels=1
    )
    
    # Export the audio to the output file
    audio_segment.export(output_file, format="mp3")
    print(f"Processed audio saved to: {output_file}")

def main():
    # Parse command-line arguments
    if len(sys.argv) != 3:
        print("Usage: python process_audio.py <filename> <conversion_type>")
        print("Conversion types: -v (vocals), -s (instrumental)")
        sys.exit(1)
    
    input_file = sys.argv[1]
    flag = sys.argv[2]
    
    # Map flags to conversion types
    conv_type_map = {
        '-v': 'vocals',
        '-s': 'instrumental'
    }
    
    if flag not in conv_type_map:
        print("Invalid option. Use '-v' for vocals or '-s' for instrumental.")
        sys.exit(1)
    
    conv_type = conv_type_map[flag]
    output_file = f"processed_{conv_type}.mp3"
    
    # Process the audio
    process_audio(input_file, output_file, conv_type)

if __name__ == "__main__":
    main()


