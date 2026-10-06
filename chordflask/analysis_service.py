"""Orchestrate chord analysis while letting component failures propagate.

Web, worker, and CLI entry points own user-facing reporting, retry, and exit
behavior. This service does not turn failed analysis into an empty result.
"""

import os

from chordflask_base import (
    ChordData,
    is_canonical_analysis_complete,
    preserve_analysis_user_data,
)


class ChordAnalysisService:
    def __init__(self, converter=None, analyzer=None, exporter=None):
        if converter is None:
            from .media_converter import MediaConverter
            converter = MediaConverter()
        if analyzer is None:
            from .audio_analyzer import AudioAnalyzer
            analyzer = AudioAnalyzer()
        if exporter is None:
            from .chord_exporter import ChordExporter
            exporter = ChordExporter()
        self.converter = converter
        self.analyzer = analyzer
        self.exporter = exporter

    def ensure_analyzed(self, file_repr, use_madmom=False, export_midi=True):
        existing = None
        if os.path.exists(file_repr.get("json")):
            existing = ChordData(file_repr.get("json"))
            if is_canonical_analysis_complete(existing):
                print(f"Chord analysis already exists: {file_repr.get('json')}")
                return existing

        analysis_audio = self.converter.ensure_mp3(file_repr)
        chord_data = self.analyzer.analyze(analysis_audio, use_madmom=use_madmom)
        if not use_madmom and not is_canonical_analysis_complete(chord_data):
            raise RuntimeError("Analysis did not create complete canonical tracks")
        if existing is not None:
            preserve_analysis_user_data(existing, chord_data)
        if export_midi:
            self.exporter.write_midi_and_musicxml(chord_data, file_repr)
        chord_data.save_to_file(file_repr.get("json"))
        print(f"Chord data saved to {file_repr.get('json')}")
        return chord_data
