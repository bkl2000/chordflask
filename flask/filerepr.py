#!/usr/bin/env python3

"""
FileRepr class handles file paths and representations for different file types.
"""

from functools import lru_cache
from pathlib import Path

from chordflask_config import ANALYSIS_DIR_NAME, LEGACY_ANALYSIS_DIR_NAME

class FileRepr:
    def __init__(self, filename, datapath=ANALYSIS_DIR_NAME, create=False):
        self._media_path = Path(filename).resolve()
        data_path = Path(datapath)
        if not data_path.is_absolute():
            data_path = self._media_path.parent / data_path
        default_data_path = self._media_path.parent / ANALYSIS_DIR_NAME
        if data_path.resolve() == default_data_path.resolve() and not data_path.exists():
            legacy_path = self._media_path.parent / LEGACY_ANALYSIS_DIR_NAME
            if legacy_path.is_dir():
                if create:
                    try:
                        legacy_path.rename(data_path)
                    except OSError:
                        data_path = legacy_path
                else:
                    data_path = legacy_path
        self._data_path = data_path.resolve()
        self.datapath = str(self._data_path)
        self.filename = str(self._media_path)
        self.basename = self._media_path.stem
        if create:
            self._data_path.mkdir(parents=True, exist_ok=True)

    @lru_cache(maxsize=None)
    def get(self, suffix=""):
        """
        Get the full path to the file, using the base filename and optional suffix.
        If no suffix is given, returns the original file.
        Known suffixes (like 'json', 'mp3', 'xml', 'mid', 'song_data') go into the data directory.
        """
        if suffix == "":
            return self.filename

        # Custom extension for song metadata
        ext_map = {
            "json": "json",
            "mp3": "mp3",
            "xml": "xml",
            "mid": "mid",
            "song_data": "song"  # maps to *.song
        }

        ext = ext_map.get(suffix, suffix)  # fallback to raw suffix
        return str(self._data_path / f"{self.basename}.{ext}")

    @property
    def media_path(self):
        return self.get()

    @property
    def json_path(self):
        return self.get("json")

    @property
    def mp3_path(self):
        return self.get("mp3")

    @property
    def xml_path(self):
        return self.get("xml")

    @property
    def midi_path(self):
        return self.get("mid")

    @property
    def song_path(self):
        return self.get("song_data")
