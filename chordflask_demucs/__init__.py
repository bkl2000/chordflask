"""Optional Demucs stem preparation for ChordFlask.

The package itself has no Demucs, Torch, or audio-library imports.  It invokes
the optional Demucs installation as a bounded subprocess and stores the
resulting FLAC stem set through the neutral Schema-v3 model.
"""

from .constants import AUDIO_SET_ID, DEMUCS_MODEL, DEMUCS_STEM_NAMES

__all__ = ["AUDIO_SET_ID", "DEMUCS_MODEL", "DEMUCS_STEM_NAMES"]
