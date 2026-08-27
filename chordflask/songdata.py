#!/usr/bin/env python3

import json
import logging

class SongData:
    def __init__(self, filename=""):
        self.filename = filename
        self.data = {}  # free-form dictionary

        if self.filename:
            self.load_from_file(self.filename)

    def load_from_file(self, file_path):
        try:
            with open(file_path, 'r') as f:
                self.data = json.load(f)
            logging.info(f"Song data loaded from {file_path}")
        except FileNotFoundError:
            logging.warning(f"No song data found at {file_path}, starting fresh.")
            self.data = {}
        except Exception as e:
            logging.error(f"Failed to load song data: {e}")
            self.data = {}

    def save_to_file(self, file_path=None):
        try:
            if file_path:
                self.filename = file_path
            with open(self.filename, 'w') as f:
                json.dump(self.data, f, indent=4)
            logging.info(f"Song data saved to {self.filename}")
        except Exception as e:
            logging.error(f"Failed to save song data: {e}")

