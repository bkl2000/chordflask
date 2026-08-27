"""Compatibility re-export of the chord data model.

The implementation lives in :mod:`chordflask_base`. This module only keeps
``from chordflask.chorddata import ChordData, ChordTrackRepository`` for legacy
callers; new code should import from ``chordflask_base``.
"""

from chordflask_base import ChordData, ChordTrackRepository

__all__ = ["ChordData", "ChordTrackRepository"]
