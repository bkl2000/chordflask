"""Fixed Demucs storage and processing constants."""

from pathlib import Path

from chordflask_base import DEMUCS_STEM_NAMES as _DEMUCS_STEM_NAMES

DEMUCS_MODEL = "htdemucs"
AUDIO_SET_ID = f"demucs:{DEMUCS_MODEL}"
DEMUCS_STEM_NAMES = _DEMUCS_STEM_NAMES

PERSISTENT_FORMAT = "flac"
SAMPLE_RATE = 44100
CHANNELS = 2
MAX_TAIL_DELTA_SECONDS = 0.05
DEFAULT_PROCESS_TIMEOUT_SECONDS = 3600

DEFAULT_VENV = Path.home() / ".venvs" / "chordflask-demucs"
DEFAULT_CACHE = Path.home() / ".cache" / "chordflask-demucs"

TODO = "TODO"
CURRENT = "CURRENT"
STALE = "STALE"
ERROR = "ERROR"
