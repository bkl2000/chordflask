#!/usr/bin/env python3

"""
Necessary installations for the MP4 player:

1. Install required Python packages via pip:
   pip install ffpyplayer Pillow

2. Install necessary packages via apt (for ffpyplayer and multimedia handling):
   sudo apt update
   sudo apt install ffmpeg libsdl2-dev libsdl2-ttf-2.0-0
"""

#!/usr/bin/env python3

import sys
import os
import time
import tkinter as tk
from tkinter import ttk
from ffpyplayer.player import MediaPlayer
from PIL import Image, ImageTk
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from chordflask_base import ChordData

class MP4Player:
    def __init__(self, mp4_file, json_filename=None, position_callback=None, semitones=0, use_unicode=True):
        self.mp4_file = mp4_file
        self.semitones = semitones
        self.use_unicode = use_unicode
        self.display_chord_offset = 1.0

        # Load chord data
        self.chord_data = ChordData(prefer_flats=True, use_unicode=self.use_unicode)
        if json_filename:
            self.chord_data.load_from_file(json_filename)
        self.chord_data.transpose(self.semitones)

        self.position_callback = position_callback or self._create_default_position_callback()
        self.is_playing = True
        self.total_duration = 0
        self.is_slider_dragging = False
        self.is_running = True

        self.root = tk.Tk()
        self.root.title("MP4 Player with Chords")
        self.root.geometry("800x600")
        self.root.resizable(True, True)
        self.root.bind('<Configure>', self.on_resize)

        control_frame = ttk.Frame(self.root)
        control_frame.pack(side=tk.TOP, fill=tk.X)

        self.play_button = ttk.Button(control_frame, text="Pause", command=self.toggle_playback)
        self.play_button.pack(side=tk.LEFT)

        self.time_slider = ttk.Scale(control_frame, from_=0, to=100, orient=tk.HORIZONTAL)
        self.time_slider.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.time_slider.bind('<ButtonRelease-1>', self.on_slider_release)
        self.time_slider.bind('<B1-Motion>', self.on_slider_drag)

        self.video_label = tk.Label(self.root)
        self.video_label.pack(fill=tk.BOTH, expand=True)

        self.player = MediaPlayer(self.mp4_file, ff_opts={'framedrop': '1', 'threads': '4'})

        self.update_thread = threading.Thread(target=self.update_frame)
        self.update_thread.start()

        self.root.after(100, self.update_position)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()

    def _create_default_position_callback(self):
        chords = self.chord_data.get_chords()
        chord_times = self.chord_data.chord_times

        def _callback(position):
            position += self.display_chord_offset
            idx = next((i for i, t in enumerate(chord_times) if t > position), len(chords)) - 1
            if 0 <= idx < len(chords):
                display = [f"{chords[i][1]:^8}" if i < len(chords) else "" for i in range(idx, idx + 4)]
                print(f"{position:7.2f} | {' | '.join(display)}", flush=True)

        return _callback

    def toggle_playback(self):
        self.is_playing = not self.is_playing
        self.play_button.config(text="Play" if not self.is_playing else "Pause")
        self.player.set_pause(not self.is_playing)

    def update_frame(self):
        while self.is_running:
            if self.is_playing:
                frame, _ = self.player.get_frame()
                if frame:
                    img, _ = frame
                    pil_image = Image.frombytes('RGB', img.get_size(), img.to_bytearray()[0])
                    resized = pil_image.resize((self.root.winfo_width(), self.root.winfo_height()), Image.NEAREST)
                    photo = ImageTk.PhotoImage(resized)
                    self.video_label.config(image=photo)
                    self.video_label.image = photo
            time.sleep(1 / 30)

    def update_position(self):
        if not self.is_slider_dragging:
            audio_pos = self.player.get_pts()
            if audio_pos:
                self.position_callback(audio_pos)
                if self.total_duration == 0:
                    self.total_duration = self.player.get_metadata().get("duration", 0)
                if self.total_duration > 0:
                    self.time_slider.set((audio_pos / self.total_duration) * 100)
        self.root.after(100, self.update_position)

    def on_slider_release(self, event):
        if self.total_duration > 0:
            self.player.set_pause(True)
            new_pos = (self.time_slider.get() / 100) * self.total_duration
            self.player.seek(new_pos, relative=False)
            time.sleep(0.05)
            self.player.set_pause(False)
            self.is_slider_dragging = False

    def on_slider_drag(self, event):
        self.is_slider_dragging = True

    def on_resize(self, event):
        pass  # We already recalculate size dynamically

    def on_closing(self):
        self.is_running = False
        if self.is_playing:
            self.player.set_pause(True)
        try:
            self.player.close_player()
        except Exception as e:
            print(f"Error closing player: {e}")
        if self.update_thread.is_alive():
            self.update_thread.join(timeout=5)
        self.root.quit()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: mp4player_tk.py <mp4_file> [chords.json]")
        sys.exit(1)

    mp4_file = sys.argv[1]
    json_file = sys.argv[2] if len(sys.argv) > 2 else None

    MP4Player(mp4_file, json_filename=json_file)
