"""Neutral, framework-free base layer.

Contains the Schema-v3 contract (``schema``), pure chord-label logic
(``chordlabel``), and the chord data model (``model``). Both the app (``chordflask/``)
and external chord-track producers import from here, so the model and the schema
stay independent of the Flask view.
"""

from .analysis import (
    canonical_source_status, media_source_identity, record_canonical_source,
    is_canonical_analysis_complete, preserve_analysis_user_data,
)
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
    AnalysisMigrationRequired,
    analysis_schema_status,
    load_analysis,
    read_analysis_json,
    validate_analysis,
    ANALYSIS_DIR_NAME,
    ANALYSIS_SAMPLE_RATE,
    AUDIO_TRACKS_KEY,
    BTC_TRACK_ID,
    DEFAULT_CHORD_TRACK,
    DEFAULT_RHYTHM_TRACK,
    DEMUCS_STEM_NAMES,
    MADMOM_TRACK_ID,
    PYTORCH_TRACK_ID,
    PYTORCH_V2_TRACK_ID,
    REFERENCE_TRACK_ID,
    SCHEMA_VERSION,
    SchemaV3Error,
    SUPPORTED_SCHEMA_VERSIONS,
    USER_EDITED_TRACK_ID,
    USER_EDITED_RHYTHM_TRACK_ID,
    analysis_json_path,
    chord_input_sha256,
    validate_audio_track_set,
    validate_chord_entries,
    validate_rhythm_entry,
    write_atomic,
)

from .storage import analysis_json_lock

__all__ = [
    "analysis_json_lock",
    "AnalysisMigrationRequired",
    "analysis_schema_status",
    "load_analysis",
    "read_analysis_json",
    "validate_analysis",
    "ANALYSIS_DIR_NAME",
    "ANALYSIS_SAMPLE_RATE",
    "AUDIO_TRACKS_KEY",
    "BTC_TRACK_ID",
    "DEFAULT_CHORD_TRACK",
    "DEFAULT_RHYTHM_TRACK",
    "DEMUCS_STEM_NAMES",
    "MADMOM_TRACK_ID",
    "PYTORCH_TRACK_ID",
    "PYTORCH_V2_TRACK_ID",
    "REFERENCE_TRACK_ID",
    "SCHEMA_VERSION",
    "SchemaV3Error",
    "SUPPORTED_SCHEMA_VERSIONS",
    "USER_EDITED_TRACK_ID",
    "USER_EDITED_RHYTHM_TRACK_ID",
    "analysis_json_path",
    "canonical_source_status",
    "media_source_identity",
    "record_canonical_source",
    "is_canonical_analysis_complete",
    "preserve_analysis_user_data",
    "chord_input_sha256",
    "write_atomic",
    "validate_chord_entries",
    "validate_audio_track_set",
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
