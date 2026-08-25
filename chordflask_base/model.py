"""Chord data model and persistence (neutral, framework-free).

Part of :mod:`chordflask_base`. Holds ``ChordData`` (the in-memory model with
track selection, beat-aligned tracks, transpose, and grid helpers) and
``ChordTrackRepository`` (load/save/validate). It imports only ``.schema`` and
``.chordlabel``, never the Flask view or any audio/analysis stack.
"""

import bisect
import copy
import json
import logging
import math
from functools import lru_cache

from . import chordlabel
from . import schema
from .schema import ANALYSIS_SAMPLE_RATE, DEFAULT_CHORD_TRACK, DEFAULT_RHYTHM_TRACK

class ChordTrackRepository:
    SCHEMA_VERSION = schema.SCHEMA_VERSION
    SUPPORTED_SCHEMA_VERSIONS = schema.SUPPORTED_SCHEMA_VERSIONS

    def load(self, file_path, chord_data=None):
        track = chord_data or ChordData()
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError(
                f"Invalid chord data in {file_path}: root must be an object"
            )
        version = data.get("schema_version")
        if version is None:
            logging.warning(
                "Chord file %s has no schema_version, treating as legacy format.",
                file_path,
            )
        elif version not in self.SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"Unsupported chord data schema version {version} "
                f"(current: {self.SCHEMA_VERSION}) in {file_path}"
            )

        self._validate(data, file_path)

        track._clear_tracks()

        if version is not None and version >= 3:
            self.__load_v3(track, data)
        else:
            self.__load_legacy(track, data)

        track.user_data = copy.deepcopy(data.get("user_data", {}))
        track.transpose(data.get("transpose", 0))
        track.set_prefer_flats(data.get("prefer_flats", track.prefer_flats))

        track._rebuild_active_view()
        track._get_chords_cached.cache_clear()
        return track

    @staticmethod
    def __load_v3(track, data):
        for tid, entry in data.get("chord_tracks", {}).items():
            if not isinstance(tid, str) or not tid.strip():
                raise ValueError("chord_tracks key must be a non-empty string")
            if not isinstance(entry, dict):
                raise ValueError(f"chord_tracks[\"{tid}\"] must be an object")
            chords = entry.get("chords", [])
            sanitized = track._sanitize_chords(chords)
            track._add_raw_chord_track(tid, {
                "chords": sanitized,
                "metadata": copy.deepcopy(entry.get("metadata", {})),
            })

        for tid, entry in data.get("rhythm_tracks", {}).items():
            if not isinstance(tid, str) or not tid.strip():
                raise ValueError("rhythm_tracks key must be a non-empty string")
            if not isinstance(entry, dict):
                raise ValueError(f"rhythm_tracks[\"{tid}\"] must be an object")
            track._add_raw_rhythm_track(tid, {
                "bpm": entry.get("bpm"),
                "meter_signature": entry.get("meter_signature"),
                "beat_times": list(entry.get("beat_times", [])),
                "beat_numbers": list(entry.get("beat_numbers", [])),
                "metadata": copy.deepcopy(entry.get("metadata", {})),
            })

        for set_id, entry in data.get(schema.AUDIO_TRACKS_KEY, {}).items():
            if not isinstance(set_id, str) or not set_id.strip():
                raise ValueError("audio_tracks key must be a non-empty string")
            track._add_raw_audio_track(set_id, copy.deepcopy(entry))

    @staticmethod
    def __load_legacy(track, data):
        chords = data.get("base_chords", [])
        sanitized = track._sanitize_chords(chords)
        track._add_raw_chord_track("chordino", {
            "chords": sanitized,
            "metadata": {},
        })

        track._add_raw_rhythm_track("qm_barbeattracker", {
            "bpm": data.get("bpm"),
            "meter_signature": data.get("meter_signature"),
            "beat_times": list(data.get("beat_times", [])),
            "beat_numbers": list(data.get("beat_numbers", [])),
            "metadata": {},
        })

    def save(self, chord_data, file_path):
        chord_entries = {}
        for tid in chord_data.available_chord_track_ids:
            chord_entries[tid] = {
                "chords": chord_data.chord_track_chords(tid),
                "metadata": chord_data.chord_track_metadata(tid),
            }
        rhythm_entries = {}
        for tid in chord_data.available_rhythm_track_ids:
            rhythm_entries[tid] = chord_data.rhythm_track_data(tid)

        if not chord_entries and chord_data._base_chords:
            chord_entries["chordino"] = {
                "chords": copy.deepcopy(chord_data._base_chords),
                "metadata": {},
            }
        if not rhythm_entries and (
            chord_data._bpm is not None
            or chord_data._meter_signature is not None
            or chord_data._beat_times
            or chord_data._beat_numbers
        ):
            rhythm_entries["qm_barbeattracker"] = {
                "bpm": chord_data._bpm,
                "meter_signature": chord_data._meter_signature,
                "beat_times": list(chord_data._beat_times),
                "beat_numbers": list(chord_data._beat_numbers),
                "metadata": {},
            }

        data = {
            "schema_version": self.SCHEMA_VERSION,
            "prefer_flats": chord_data.prefer_flats,
            "transpose": chord_data._transpose,
            "user_data": copy.deepcopy(chord_data.user_data),
            "chord_tracks": {},
            "rhythm_tracks": {},
        }
        for tid, entry in chord_entries.items():
            data["chord_tracks"][tid] = {
                "chords": entry["chords"],
                "metadata": copy.deepcopy(entry.get("metadata", {})),
            }
        for tid, entry in rhythm_entries.items():
            data["rhythm_tracks"][tid] = {
                "bpm": entry["bpm"],
                "meter_signature": entry["meter_signature"],
                "beat_times": list(entry.get("beat_times", [])),
                "beat_numbers": list(entry.get("beat_numbers", [])),
                "metadata": copy.deepcopy(entry.get("metadata", {})),
            }
        data[schema.AUDIO_TRACKS_KEY] = {
            set_id: chord_data.audio_track_data(set_id)
            for set_id in chord_data.available_audio_track_ids
        }

        self._validate(data, file_path)

        schema.write_atomic(file_path, data)

    @staticmethod
    def _is_finite_number(value):
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )

    @staticmethod
    def _validate(data, file_path):
        if not isinstance(data, dict):
            raise ValueError(
                f"Invalid chord data in {file_path}: root must be an object"
            )

        version = data.get("schema_version")
        if version is not None and (
            not isinstance(version, int)
            or isinstance(version, bool)
            or version not in ChordTrackRepository.SUPPORTED_SCHEMA_VERSIONS
        ):
            raise ValueError(
                f"Invalid chord data in {file_path}: schema_version must be "
                f"one of {sorted(ChordTrackRepository.SUPPORTED_SCHEMA_VERSIONS)}, "
                f"got {version!r}"
            )

        prefer_flats = data.get("prefer_flats", True)
        if not isinstance(prefer_flats, bool):
            raise ValueError(
                f"Invalid chord data in {file_path}: prefer_flats must be a boolean"
            )

        transpose = data.get("transpose", 0)
        if not isinstance(transpose, int) or isinstance(transpose, bool):
            raise ValueError(
                f"Invalid chord data in {file_path}: transpose must be an integer"
            )

        user_data = data.get("user_data", {})
        if not isinstance(user_data, dict):
            raise ValueError(
                f"Invalid chord data in {file_path}: user_data must be an object"
            )

        if version is not None and version >= 3:
            ChordTrackRepository.__validate_v3(data, file_path)
        else:
            ChordTrackRepository.__validate_legacy(data, file_path)

    @staticmethod
    def __validate_chord_entries(chords, file_path, context):
        schema.validate_chord_entries(chords, file_path, context)

    @staticmethod
    def __validate_rhythm_entry(entry, file_path, context):
        schema.validate_rhythm_entry(entry, file_path, context)

    @staticmethod
    def __validate_v3(data, file_path):
        for required in ("chord_tracks", "rhythm_tracks"):
            if required not in data:
                raise ValueError(
                    f"Invalid chord data in {file_path}: "
                    f"schema v3 must contain \"{required}\""
                )

        chord_tracks = data["chord_tracks"]
        if not isinstance(chord_tracks, dict):
            raise ValueError(
                f"Invalid chord data in {file_path}: chord_tracks must be an object"
            )
        for tid, entry in chord_tracks.items():
            if not isinstance(tid, str) or not tid.strip():
                raise ValueError(
                    f"Invalid chord data in {file_path}: chord_tracks key must be a non-empty string"
                )
            if not isinstance(entry, dict):
                raise ValueError(
                    f"Invalid chord data in {file_path}: chord_tracks[\"{tid}\"] must be an object"
                )
            if "chords" not in entry:
                raise ValueError(
                    f"Invalid chord data in {file_path}: chord_tracks[\"{tid}\"] must contain \"chords\""
                )
            ChordTrackRepository.__validate_chord_entries(
                entry["chords"], file_path, f"chord_tracks[\"{tid}\"].chords"
            )
            metadata = entry.get("metadata", {})
            if not isinstance(metadata, dict):
                raise ValueError(
                    f"Invalid chord data in {file_path}: chord_tracks[\"{tid}\"].metadata must be an object"
                )

        rhythm_tracks = data["rhythm_tracks"]
        if not isinstance(rhythm_tracks, dict):
            raise ValueError(
                f"Invalid chord data in {file_path}: rhythm_tracks must be an object"
            )
        for tid, entry in rhythm_tracks.items():
            if not isinstance(tid, str) or not tid.strip():
                raise ValueError(
                    f"Invalid chord data in {file_path}: rhythm_tracks key must be a non-empty string"
                )
            if not isinstance(entry, dict):
                raise ValueError(
                    f"Invalid chord data in {file_path}: rhythm_tracks[\"{tid}\"] must be an object"
                )
            ChordTrackRepository.__validate_rhythm_entry(
                entry, file_path, f"rhythm_tracks[\"{tid}\"]"
            )

        audio_tracks = data.get(schema.AUDIO_TRACKS_KEY, {})
        if not isinstance(audio_tracks, dict):
            raise ValueError(
                f"Invalid chord data in {file_path}: audio_tracks must be an object"
            )
        for set_id, entry in audio_tracks.items():
            if not isinstance(set_id, str) or not set_id.strip():
                raise ValueError(
                    f"Invalid chord data in {file_path}: "
                    "audio_tracks key must be a non-empty string"
                )
            schema.validate_audio_track_set(
                entry, file_path, f'audio_tracks["{set_id}"]'
            )

    @staticmethod
    def __validate_legacy(data, file_path):
        chords = data.get("base_chords", [])
        ChordTrackRepository.__validate_chord_entries(
            chords, file_path, "base_chords"
        )

        bpm = data.get("bpm")
        if bpm is not None:
            if not ChordTrackRepository._is_finite_number(bpm) or bpm <= 0:
                raise ValueError(
                    f"Invalid chord data in {file_path}: bpm must be positive, got {bpm!r}"
                )

        meter = data.get("meter_signature")
        if meter is not None:
            if not isinstance(meter, int) or isinstance(meter, bool) or meter <= 0:
                raise ValueError(
                    f"Invalid chord data in {file_path}: "
                    f"meter_signature must be a positive integer, got {meter!r}"
                )

        beat_times = data.get("beat_times", [])
        beat_indexes = data.get("beat_chord_indexes")
        if not isinstance(beat_times, list):
            raise ValueError(
                f"Invalid chord data in {file_path}: beat_times must be a list"
            )
        if beat_indexes is not None and not isinstance(beat_indexes, list):
            raise ValueError(
                f"Invalid chord data in {file_path}: beat_chord_indexes must be a list"
            )
        if beat_indexes is not None and len(beat_indexes) != len(beat_times):
            raise ValueError(
                f"Invalid chord data in {file_path}: "
                f"beat_chord_indexes length {len(beat_indexes)} "
                f"does not match beat_times length {len(beat_times)}"
            )

        prev_bt = None
        for i, bt in enumerate(beat_times):
            if not ChordTrackRepository._is_finite_number(bt) or bt < 0:
                raise ValueError(
                    f"Invalid chord data in {file_path}: "
                    f"beat_times[{i}] is negative or not a finite number: {bt!r}"
                )
            if prev_bt is not None and bt < prev_bt:
                raise ValueError(
                    f"Invalid chord data in {file_path}: "
                    f"beat_times[{i}] {bt} is before previous {prev_bt}"
                )
            prev_bt = bt

        max_index = len(chords) - 1
        for i, ci in enumerate(beat_indexes or []):
            if (
                not isinstance(ci, int)
                or isinstance(ci, bool)
                or ci < 0
                or ci > max_index
            ):
                raise ValueError(
                    f"Invalid chord data in {file_path}: "
                    f"beat_chord_indexes[{i}] {ci!r} is out of range [0, {max_index}]"
                )

        beat_numbers = data.get("beat_numbers", [])
        if not isinstance(beat_numbers, list):
            raise ValueError(
                f"Invalid chord data in {file_path}: beat_numbers must be a list"
            )
        if beat_numbers and len(beat_numbers) != len(beat_times):
            raise ValueError(
                f"Invalid chord data in {file_path}: beat_numbers length "
                f"{len(beat_numbers)} does not match beat_times length {len(beat_times)}"
            )
        for i, beat_number in enumerate(beat_numbers):
            if (
                not isinstance(beat_number, int)
                or isinstance(beat_number, bool)
                or beat_number <= 0
            ):
                raise ValueError(
                    f"Invalid chord data in {file_path}: beat_numbers[{i}] must be "
                    f"a positive integer, got {beat_number!r}"
                )
            if meter is not None and beat_number > meter:
                raise ValueError(
                    f"Invalid chord data in {file_path}: beat_numbers[{i}] "
                    f"{beat_number} exceeds meter_signature {meter}"
                )


class ChordData:
    def __init__(self, filename="", prefer_flats=True, use_unicode=False):
        self.filename = filename
        self.prefer_flats = prefer_flats
        self.use_unicode = use_unicode
        self.sr = ANALYSIS_SAMPLE_RATE

        self._base_chords = []
        self._chord_times = []
        self._transpose = 0

        self._bpm = None
        self._beat_times = []
        self._beat_chord_indexes = []
        self._beat_numbers = []
        self._meter_signature = None
        self.user_data = {}

        self.__chord_tracks = {}
        self.__rhythm_tracks = {}
        self.__audio_tracks = {}
        self.__active_chord_track_id = None
        self.__active_rhythm_track_id = None
        self.__chord_selection_explicit = False
        self.__rhythm_selection_explicit = False

        if self.filename:
            self.load_from_file(self.filename)

    # ── input validation helpers ───────────────────────────────────────

    @staticmethod
    def __validate_track_id(track_id):
        if not isinstance(track_id, str) or not track_id.strip():
            raise ValueError("track_id must be a non-empty string")

    @staticmethod
    def __validate_chord_entries(chords):
        if not isinstance(chords, list):
            raise ValueError("chords must be a list")
        prev = None
        for i, entry in enumerate(chords):
            if not isinstance(entry, dict):
                raise ValueError(f"chords[{i}] must be an object")
            ts = entry.get("timestamp")
            ch = entry.get("chord")
            if not (isinstance(ts, (int, float)) and not isinstance(ts, bool)
                    and math.isfinite(ts) and ts >= 0):
                raise ValueError(
                    f"chords[{i}] has invalid or negative timestamp {ts!r}"
                )
            if not isinstance(ch, str) or not ch.strip():
                raise ValueError(
                    f"chords[{i}] has empty or missing chord {ch!r}"
                )
            if prev is not None and ts < prev:
                raise ValueError(
                    f"chords[{i}] timestamp {ts} is before previous {prev}"
                )
            prev = ts

    @staticmethod
    def __validate_metadata(metadata):
        if metadata is None:
            return {}
        if not isinstance(metadata, dict):
            raise ValueError(
                f"metadata must be an object, got {type(metadata).__name__}"
            )
        return metadata

    # ── track storage ──────────────────────────────────────────────────

    def set_chord_track(self, track_id, chords, metadata=None):
        self.__validate_track_id(track_id)
        self.__validate_chord_entries(chords)
        meta = self.__validate_metadata(metadata)
        sanitized = self._sanitize_chords(chords)
        self.__chord_tracks[track_id] = {
            "chords": sanitized,
            "metadata": copy.deepcopy(meta),
        }
        if self.__active_chord_track_id is None or (
            track_id == DEFAULT_CHORD_TRACK and not self.__chord_selection_explicit
        ):
            self.__active_chord_track_id = track_id
        if self.__active_chord_track_id == track_id:
            self._rebuild_active_view()
        self._get_chords_cached.cache_clear()

    def set_rhythm_track(self, track_id, *, bpm=None, meter_signature=None,
                         beat_times=None, beat_numbers=None, metadata=None):
        self.__validate_track_id(track_id)
        meta = self.__validate_metadata(metadata)

        if beat_times is not None and not isinstance(beat_times, list):
            raise ValueError("beat_times must be a list")
        if beat_numbers is not None and not isinstance(beat_numbers, list):
            raise ValueError("beat_numbers must be a list")
        if bpm is not None and not (isinstance(bpm, (int, float))
                                    and not isinstance(bpm, bool)
                                    and math.isfinite(bpm) and bpm > 0):
            raise ValueError("bpm must be a positive finite number")
        if meter_signature is not None and not (
            isinstance(meter_signature, int)
            and not isinstance(meter_signature, bool)
            and meter_signature > 0
        ):
            raise ValueError("meter_signature must be a positive integer")

        bt_list = list(beat_times) if beat_times is not None else []
        bn_list = list(beat_numbers) if beat_numbers is not None else []

        if bn_list and len(bn_list) != len(bt_list):
            raise ValueError("beat_numbers must match beat_times length")

        prev = None
        for i, bt in enumerate(bt_list):
            if not (isinstance(bt, (int, float)) and not isinstance(bt, bool)
                    and math.isfinite(bt) and bt >= 0):
                raise ValueError(f"beat_times[{i}] is not a finite non-negative number")
            if prev is not None and bt < prev:
                raise ValueError(f"beat_times[{i}] {bt} is before previous {prev}")
            prev = bt

        for i, bn in enumerate(bn_list):
            if not isinstance(bn, int) or isinstance(bn, bool) or bn <= 0:
                raise ValueError(f"beat_numbers[{i}] must be a positive integer")
            if meter_signature is not None and bn > meter_signature:
                raise ValueError(
                    f"beat_numbers[{i}] {bn} exceeds meter_signature {meter_signature}"
                )

        self.__rhythm_tracks[track_id] = {
            "bpm": bpm,
            "meter_signature": meter_signature,
            "beat_times": bt_list,
            "beat_numbers": bn_list,
            "metadata": copy.deepcopy(meta),
        }
        if self.__active_rhythm_track_id is None or (
            track_id == DEFAULT_RHYTHM_TRACK
            and not self.__rhythm_selection_explicit
        ):
            self.__active_rhythm_track_id = track_id
        if self.__active_rhythm_track_id == track_id:
            self._rebuild_active_view()
        self._get_chords_cached.cache_clear()

    @property
    def available_chord_track_ids(self):
        ids = list(self.__chord_tracks.keys())
        preferred = []
        for tid in (DEFAULT_CHORD_TRACK,):
            if tid in ids:
                ids.remove(tid)
                preferred.append(tid)
        return preferred + sorted(ids)

    @property
    def available_rhythm_track_ids(self):
        ids = list(self.__rhythm_tracks.keys())
        preferred = []
        for tid in (DEFAULT_RHYTHM_TRACK,):
            if tid in ids:
                ids.remove(tid)
                preferred.append(tid)
        return preferred + sorted(ids)

    @property
    def active_chord_track_id(self):
        return self.__active_chord_track_id

    @property
    def active_rhythm_track_id(self):
        return self.__active_rhythm_track_id

    def select_chord_track(self, track_id):
        self.__validate_track_id(track_id)
        if track_id not in self.__chord_tracks:
            raise ValueError(f"chord track \"{track_id}\" not available")
        self.__chord_selection_explicit = True
        if self.__active_chord_track_id == track_id:
            return
        self.__active_chord_track_id = track_id
        self._rebuild_active_view()
        self._get_chords_cached.cache_clear()

    def select_rhythm_track(self, track_id):
        self.__validate_track_id(track_id)
        if track_id not in self.__rhythm_tracks:
            raise ValueError(f"rhythm track \"{track_id}\" not available")
        self.__rhythm_selection_explicit = True
        if self.__active_rhythm_track_id == track_id:
            return
        self.__active_rhythm_track_id = track_id
        self._rebuild_active_view()
        self._get_chords_cached.cache_clear()

    def chord_track_metadata(self, track_id):
        if track_id not in self.__chord_tracks:
            raise ValueError(f"chord track \"{track_id}\" not available")
        return copy.deepcopy(self.__chord_tracks[track_id].get("metadata", {}))

    def rhythm_track_metadata(self, track_id):
        if track_id not in self.__rhythm_tracks:
            raise ValueError(f"rhythm track \"{track_id}\" not available")
        return copy.deepcopy(self.__rhythm_tracks[track_id].get("metadata", {}))

    def chord_track_chords(self, track_id):
        """Return an isolated copy of one chord track's events."""
        if track_id not in self.__chord_tracks:
            raise ValueError(f"chord track \"{track_id}\" not available")
        return copy.deepcopy(self.__chord_tracks[track_id]["chords"])

    def rhythm_track_data(self, track_id):
        """Return an isolated copy of one rhythm track, including metadata."""
        entry = self.__rhythm_tracks.get(track_id)
        if entry is None:
            raise ValueError(f"rhythm track \"{track_id}\" not available")
        return {
            "bpm": entry["bpm"],
            "meter_signature": entry["meter_signature"],
            "beat_times": list(entry["beat_times"]),
            "beat_numbers": list(entry["beat_numbers"]),
            "metadata": copy.deepcopy(entry["metadata"]),
        }

    @property
    def available_audio_track_ids(self):
        return sorted(self.__audio_tracks)

    def has_audio_track(self, set_id):
        return set_id in self.__audio_tracks

    def audio_track_data(self, set_id):
        """Return an isolated copy of one complete audio-track set."""
        if set_id not in self.__audio_tracks:
            raise ValueError(f"audio track set \"{set_id}\" not available")
        return copy.deepcopy(self.__audio_tracks[set_id])

    def set_audio_track(self, set_id, data):
        """Replace one complete audio-track set after validating it."""
        self.__validate_track_id(set_id)
        schema.validate_audio_track_set(data, "<memory>", f'audio_tracks["{set_id}"]')
        self.__audio_tracks[set_id] = copy.deepcopy(data)

    def remove_audio_track(self, set_id):
        self.__validate_track_id(set_id)
        if set_id not in self.__audio_tracks:
            raise ValueError(f"audio track set \"{set_id}\" not available")
        del self.__audio_tracks[set_id]

    def has_chord_track(self, track_id):
        return track_id in self.__chord_tracks

    def has_rhythm_track(self, track_id):
        return track_id in self.__rhythm_tracks

    def remove_rhythm_track(self, track_id):
        """Remove one rhythm track, restoring the default view when active."""
        self.__validate_track_id(track_id)
        if track_id not in self.__rhythm_tracks:
            raise ValueError(f'rhythm track "{track_id}" not available')
        del self.__rhythm_tracks[track_id]
        if self.__active_rhythm_track_id == track_id:
            self.__active_rhythm_track_id = None
            self.__rhythm_selection_explicit = False
            self._rebuild_active_view()
        self._get_chords_cached.cache_clear()

    # ── beat-aligned chord editing ─────────────────────────────────────

    def create_beat_aligned_track(self, track_id, source_chord_track_id=DEFAULT_CHORD_TRACK,
                                  source_rhythm_track_id=DEFAULT_RHYTHM_TRACK,
                                  metadata=None):
        """Sample a chord track onto a rhythm grid and store it run-length encoded."""
        self.__validate_track_id(track_id)
        chords = self.chord_track_chords(source_chord_track_id)
        rhythm = self.rhythm_track_data(source_rhythm_track_id)
        beat_times = rhythm["beat_times"]
        if not beat_times:
            raise ValueError(
                f"rhythm track \"{source_rhythm_track_id}\" has no beat times"
            )
        times = [entry["timestamp"] for entry in chords]
        labels = []
        for lookup in self._beat_lookup_times_for(beat_times):
            index = bisect.bisect_right(times, lookup) - 1
            labels.append(chords[index]["chord"] if 0 <= index < len(chords) else "N")
        encoded = chordlabel.rle_chord_labels(list(zip(beat_times, labels, strict=True)))
        meta = copy.deepcopy(metadata) if metadata is not None else {}
        meta.setdefault("sources", {
            "chord": source_chord_track_id,
            "rhythm": source_rhythm_track_id,
        })
        self.set_chord_track(track_id, encoded, metadata=meta)

    def edit_chord_track_beat(self, track_id, beat_index, label,
                              rhythm_track_id=DEFAULT_RHYTHM_TRACK):
        """Change one beat's label on a beat-aligned track and re-compress it."""
        self.__validate_track_id(track_id)
        if track_id not in self.__chord_tracks:
            raise ValueError(f"chord track \"{track_id}\" not available")
        rhythm = self.rhythm_track_data(rhythm_track_id)
        beat_times = rhythm["beat_times"]
        if not isinstance(beat_index, int) or isinstance(beat_index, bool):
            raise ValueError("beat_index must be an integer")
        if beat_index < 0 or beat_index >= len(beat_times):
            raise ValueError(
                f"beat_index {beat_index} out of range [0, {len(beat_times)})"
            )
        normalized = chordlabel.validate_chord_label(label)
        per_beat = chordlabel.expand_chord_labels(
            self.chord_track_chords(track_id), beat_times
        )
        per_beat[beat_index] = normalized
        encoded = chordlabel.rle_chord_labels(list(zip(beat_times, per_beat, strict=True)))
        self.set_chord_track(track_id, encoded, metadata=self.chord_track_metadata(track_id))

    def remove_chord_track(self, track_id):
        """Remove one chord track, restoring the default view when it was active."""
        self.__validate_track_id(track_id)
        if track_id not in self.__chord_tracks:
            raise ValueError(f"chord track \"{track_id}\" not available")
        del self.__chord_tracks[track_id]
        if self.__active_chord_track_id == track_id:
            self.__active_chord_track_id = None
            self.__chord_selection_explicit = False
            self._rebuild_active_view()
        self._get_chords_cached.cache_clear()

    # ── active view rebuild ────────────────────────────────────────────

    def _rebuild_active_view(self):
        if self.__active_chord_track_id is None and self.__chord_tracks:
            self.__active_chord_track_id = self._resolve_chord_default()
        if self.__active_rhythm_track_id is None and self.__rhythm_tracks:
            self.__active_rhythm_track_id = self._resolve_rhythm_default()

        active_chord = self.__chord_tracks.get(
            self.__active_chord_track_id or ""
        )
        active_rhythm = self.__rhythm_tracks.get(
            self.__active_rhythm_track_id or ""
        )

        if active_chord is not None:
            self._base_chords = list(active_chord.get("chords", []))
            self._chord_times = [entry['timestamp'] for entry in self._base_chords]

        if active_rhythm is not None:
            self._bpm = active_rhythm.get("bpm")
            self._meter_signature = active_rhythm.get("meter_signature")
            self._beat_times = list(active_rhythm.get("beat_times", []))
            self._beat_numbers = list(active_rhythm.get("beat_numbers", []))

        self._beat_chord_indexes = self._beat_times_to_chord_indexes()

    def _resolve_chord_default(self):
        ids = set(self.__chord_tracks.keys())
        for tid in (DEFAULT_CHORD_TRACK,):
            if tid in ids:
                return tid
        return next(iter(sorted(ids)), None)

    def _resolve_rhythm_default(self):
        ids = set(self.__rhythm_tracks.keys())
        for tid in (DEFAULT_RHYTHM_TRACK,):
            if tid in ids:
                return tid
        return next(iter(sorted(ids)), None)

    # ── sync view fields into backing track (for legacy setter compat) ──

    def __sync_bpm_to_track(self):
        if self.__active_rhythm_track_id is not None:
            self.__rhythm_tracks[self.__active_rhythm_track_id]["bpm"] = self._bpm

    def __sync_meter_to_track(self):
        if self.__active_rhythm_track_id is not None:
            self.__rhythm_tracks[self.__active_rhythm_track_id]["meter_signature"] = self._meter_signature

    def __sync_beats_to_track(self):
        if self.__active_rhythm_track_id is not None:
            t = self.__rhythm_tracks[self.__active_rhythm_track_id]
            t["beat_times"] = list(self._beat_times)
            t["beat_numbers"] = list(self._beat_numbers)

    def __ensure_compat_rhythm_track(self):
        if self.__active_rhythm_track_id is None and DEFAULT_RHYTHM_TRACK not in self.__rhythm_tracks:
            self.__rhythm_tracks[DEFAULT_RHYTHM_TRACK] = {
                "bpm": self._bpm,
                "meter_signature": self._meter_signature,
                "beat_times": list(self._beat_times),
                "beat_numbers": list(self._beat_numbers),
                "metadata": {},
            }
            self.__active_rhythm_track_id = DEFAULT_RHYTHM_TRACK

    # ── repository helpers ─────────────────────────────────────────────

    def _clear_tracks(self):
        self.__chord_tracks.clear()
        self.__rhythm_tracks.clear()
        self.__audio_tracks.clear()
        self.__active_chord_track_id = None
        self.__active_rhythm_track_id = None
        self.__chord_selection_explicit = False
        self.__rhythm_selection_explicit = False
        self._base_chords = []
        self._chord_times = []
        self._bpm = None
        self._meter_signature = None
        self._beat_times = []
        self._beat_chord_indexes = []
        self._beat_numbers = []

    def _add_raw_chord_track(self, track_id, entry):
        self.__chord_tracks[track_id] = entry

    def _add_raw_rhythm_track(self, track_id, entry):
        self.__rhythm_tracks[track_id] = entry

    def _add_raw_audio_track(self, set_id, entry):
        self.__audio_tracks[set_id] = entry

    # ── I/O ────────────────────────────────────────────────────────────

    def load_from_file(self, file_path):
        ChordTrackRepository().load(file_path, self)
        logging.info(f"Chord data loaded from {file_path}")

    def save_to_file(self, file_path):
        ChordTrackRepository().save(self, file_path)

    # ── chord management ───────────────────────────────────────────────

    def set_base_chords(self, chords, beat_times=None, smooth_beats=False):
        self.set_chord_track("chordino", chords)
        if beat_times is not None:
            if smooth_beats:
                beat_times = self._smooth_beats(beat_times, window_size=3)
            self._beat_times = list(beat_times)
            self.__ensure_compat_rhythm_track()
            self.__sync_beats_to_track()
            self._beat_chord_indexes = self._beat_times_to_chord_indexes()
        self._get_chords_cached.cache_clear()

    def transpose(self, semitones):
        if self._transpose != semitones:
            self._transpose = semitones
            self._get_chords_cached.cache_clear()

    @property
    def transpose_semitones(self):
        return self._transpose

    def set_unicode(self, use_unicode):
        self.use_unicode = use_unicode
        self._get_chords_cached.cache_clear()

    def set_prefer_flats(self, prefer_flats):
        self.prefer_flats = prefer_flats
        self._get_chords_cached.cache_clear()

    # ── properties that operate on active tracks ───────────────────────

    @property
    def chord_times(self):
        return self._chord_times

    @property
    def beat_times(self):
        return self._beat_times

    @property
    def beat_chord_indexes(self):
        return self._beat_chord_indexes

    @property
    def beat_numbers(self):
        return self._beat_numbers

    @property
    def bpm(self):
        return self._bpm

    @bpm.setter
    def bpm(self, value):
        self._bpm = value
        self.__sync_bpm_to_track()

    @property
    def meter_signature(self):
        return self._meter_signature

    @meter_signature.setter
    def meter_signature(self, value):
        self._meter_signature = value
        self.__sync_meter_to_track()

    def set_beats(self, beat_times, smooth=False):
        if smooth:
            beat_times = self._smooth_beats(beat_times, window_size=3)
        self._beat_times = list(beat_times)
        self.__sync_beats_to_track()
        self._beat_chord_indexes = self._beat_times_to_chord_indexes()

    def set_beat_numbers(self, beat_numbers):
        numbers = list(beat_numbers)
        if numbers and len(numbers) != len(self._beat_times):
            raise ValueError("beat_numbers must match beat_times")
        self._beat_numbers = numbers
        self.__sync_beats_to_track()

    # ── grid navigation ────────────────────────────────────────────────

    def get_grid_row_start(self, active_index, measures_per_row=2):
        if not self._beat_numbers or active_index >= len(self._beat_numbers):
            return None
        downbeats = [i for i, number in enumerate(self._beat_numbers) if number == 1]
        active_bar = bisect.bisect_right(downbeats, active_index) - 1
        if active_bar < 0:
            return None
        row_bar = active_bar - (active_bar % measures_per_row)
        return downbeats[row_bar]

    # ── chord display ──────────────────────────────────────────────────

    @lru_cache(maxsize=None)  # noqa: B019 - cache is cleared explicitly on mutation
    def _get_chords_cached(self):
        chords = self._transpose_chords()
        if self.use_unicode:
            chords = [(ts, self._ascii_to_unicode(ch)) for ts, ch in chords]
        return tuple(chords)

    def get_chords(self):
        return list(self._get_chords_cached())

    def _transpose_chords(self):
        raw = [(entry['timestamp'], entry['chord']) for entry in self._base_chords]
        return [
            (
                timestamp,
                chordlabel.transpose_chord_pitches(
                    chord, self._transpose, self.prefer_flats
                ),
            )
            for timestamp, chord in raw
        ]

    def get_chord_at(self, time):
        chords = self.get_chords()
        idx = bisect.bisect_right(self._chord_times, time) - 1
        if 0 <= idx < len(chords):
            return chords[idx][1]
        return "N"

    def get_next_chords(self, time, count=4):
        chords = self.get_chords()
        idx = bisect.bisect_right(self._chord_times, time) - 1
        return [
            chords[i] if 0 <= i < len(chords) else (0, '')
            for i in range(idx, idx + count)
        ]

    def _sanitize_chords(self, chords):
        return [{"timestamp": e["timestamp"], "chord": self._unicode_to_ascii(e.get("chord", ""))} for e in chords]

    def get_chord_index_by_timestamp(self, timestamp):
        import bisect
        times = self.chord_times
        idx = bisect.bisect_right(times, timestamp) - 1
        return max(0, idx)

    @staticmethod
    def _ascii_to_unicode(chord):
        return chord.replace('b', '\u266d').replace('#', '\u266f')

    @staticmethod
    def _unicode_to_ascii(chord):
        return chord.replace('\u266d', 'b').replace('\u266f', '#')

    def _beat_times_to_chord_indexes(self):
        indexes = []
        for t in self._beat_lookup_times():
            idx = bisect.bisect_right(self._chord_times, t) - 1
            indexes.append(max(0, idx))
        return indexes

    @staticmethod
    def _beat_lookup_times_for(beat_times):
        if not beat_times:
            return []
        lookup_times = [
            (current + following) / 2
            for current, following in zip(beat_times, beat_times[1:], strict=False)
        ]
        if len(beat_times) == 1:
            lookup_times.append(beat_times[0])
        else:
            last_interval = beat_times[-1] - beat_times[-2]
            lookup_times.append(beat_times[-1] + last_interval / 2)
        return lookup_times

    def _beat_lookup_times(self):
        return self._beat_lookup_times_for(self._beat_times)

    def get_chords_per_beat(self):
        chords = self.get_chords()
        times = self.chord_times
        beat_chords = []
        for bt, lookup_time in zip(self._beat_times, self._beat_lookup_times(), strict=True):
            idx = bisect.bisect_right(times, lookup_time) - 1
            if 0 <= idx < len(chords):
                beat_chords.append((bt, chords[idx][1]))
            else:
                beat_chords.append((bt, "N"))
        return beat_chords

    def get_beat_index_for_position(self, position):
        import bisect
        if not self._beat_times:
            return 0
        idx = bisect.bisect_right(self._beat_times, position) - 1
        return max(0, idx)

    def _smooth_beats(self, times, window_size=3):
        import numpy as np
        if len(times) < window_size:
            return times

        kernel = np.ones(window_size) / window_size
        smoothed = np.convolve(times, kernel, mode='same')
        smoothed[0] = times[0]
        smoothed[-1] = times[-1]
        return smoothed.tolist()
