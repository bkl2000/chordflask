"""Neutral, framework-free base layer.

Contains the Schema-v3 contract (``schema``), pure chord-label logic
(``chordlabel``), and the chord data model (``model``). Both the app (``flask/``)
and external chord-track producers import from here, so the model and the schema
stay independent of the Flask view.
"""

from .chordlabel import (
    expand_chord_labels,
    respell_chord_label,
    respell_pitch,
    rle_chord_labels,
    transpose_chord_pitches,
    transpose_pitch,
    validate_chord_label,
)
from .model import ChordData, ChordTrackRepository
from .schema import (
    ANALYSIS_DIR_NAME,
    ANALYSIS_SAMPLE_RATE,
    BTC_TRACK_ID,
    DEFAULT_CHORD_TRACK,
    DEFAULT_RHYTHM_TRACK,
    MADMOM_TRACK_ID,
    PYTORCH_TRACK_ID,
    PYTORCH_V2_TRACK_ID,
    REFERENCE_TRACK_ID,
    SCHEMA_VERSION,
    SchemaV3Error,
    SUPPORTED_SCHEMA_VERSIONS,
    USER_EDITED_TRACK_ID,
    analysis_json_path,
    validate_chord_entries,
    validate_rhythm_entry,
    write_atomic,
)

__all__ = [
    "ANALYSIS_DIR_NAME",
    "ANALYSIS_SAMPLE_RATE",
    "BTC_TRACK_ID",
    "DEFAULT_CHORD_TRACK",
    "DEFAULT_RHYTHM_TRACK",
    "MADMOM_TRACK_ID",
    "PYTORCH_TRACK_ID",
    "PYTORCH_V2_TRACK_ID",
    "REFERENCE_TRACK_ID",
    "SCHEMA_VERSION",
    "SchemaV3Error",
    "SUPPORTED_SCHEMA_VERSIONS",
    "USER_EDITED_TRACK_ID",
    "analysis_json_path",
    "write_atomic",
    "validate_chord_entries",
    "validate_rhythm_entry",
    "ChordData",
    "ChordTrackRepository",
    "expand_chord_labels",
    "respell_chord_label",
    "respell_pitch",
    "rle_chord_labels",
    "transpose_chord_pitches",
    "transpose_pitch",
    "validate_chord_label",
]
