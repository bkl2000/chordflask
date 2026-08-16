"""``chordflask-maintain`` — maintenance for existing ChordFlask data.

This package is framework-free: it imports only the Python standard library and
``chordflask_base``. It never imports ``flask``, ``training``, torch, librosa, or
music21, so it can inspect, migrate, validate, and report on ChordFlask analysis
data and installation state without loading the web app or the analysis engine.
"""

from __future__ import annotations

__version__ = "0.7.0"
