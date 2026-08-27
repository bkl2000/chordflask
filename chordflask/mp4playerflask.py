#!/usr/bin/env python3

from chordflask_base import ChordData
from .songdata import SongData
from .playbackview import PlaybackView
from collections import deque
import logging

from pathlib import Path

from . import chordutils

from chordflask_base import (
    DEFAULT_CHORD_TRACK,
    DEFAULT_RHYTHM_TRACK,
    DEMUCS_STEM_NAMES,
    MADMOM_TRACK_ID,
    USER_EDITED_RHYTHM_TRACK_ID,
    USER_EDITED_TRACK_ID,
)
from .playbackview import GRID_MODES

_BUILTIN_TRACK_NAMES = {
    DEFAULT_CHORD_TRACK: "Chordino",
    MADMOM_TRACK_ID: "Madmom",
    DEFAULT_RHYTHM_TRACK: "QM Bar/Beat Tracker",
}

_EDITED_TRACK_ID = USER_EDITED_TRACK_ID
_EDITED_SOURCE_CHORD = DEFAULT_CHORD_TRACK
_EDIT_GRID_ROWS = 16
_EDIT_GRID_MEASURES_PER_ROW = 2

# Consumer-side identifier for the grouped Demucs stem set. It intentionally
# matches the producer's AUDIO_SET_ID ("demucs:htdemucs") but is defined here
# instead of importing the optional producer package, which stays out of the
# player runtime.
STEMS_AUDIO_SET_ID = "demucs:htdemucs"


class MP4PlayerFlask:
    def __init__(self, file_repr, semitones=0, max_lines=30, sync_chords=True,
                 position_callback=None, use_unicode=False, display_chord_offset=0.0,
                 metric_chords=False, grid_mode="compact"):
        self.file_repr = file_repr
        self.semitones = semitones
        self.max_lines = max_lines
        self.sync_chords = sync_chords
        self.display_chord_offset = display_chord_offset
        self.__metric_chords = metric_chords
        if grid_mode not in GRID_MODES:
            raise ValueError(f"grid_mode must be one of: {', '.join(sorted(GRID_MODES))}")
        self.grid_mode = grid_mode

        self.chord_data = ChordData(use_unicode=use_unicode)
        self.song_data = None

        self.callback_output = deque(maxlen=self.max_lines)
        self.last_chord = None
        self.last_rendered_position = None

        self._load_chords()
        self.chord_data.transpose(self.semitones)
        self.__build_playback_view()

        self.position_callback = position_callback or self._default_callback

    def __build_playback_view(self):
        repeat_mode = getattr(self.playback_view, "repeat_mode", "changes") if hasattr(
            self, "playback_view"
        ) else "changes"
        self.playback_view = PlaybackView(
            self.chord_data,
            display_chord_offset=self.display_chord_offset,
            repeat_mode=repeat_mode,
            metric_chords=self.__metric_chords,
            grid_mode=self.grid_mode,
        )

    def analysis_track_state(self):
        cd = self.chord_data
        chord_tracks = []
        for tid in cd.available_chord_track_ids:
            display_name = (
                "Own modification"
                if tid == _EDITED_TRACK_ID
                else self.__track_display_name(tid, cd.chord_track_metadata(tid))
            )
            chord_tracks.append({"id": tid, "display_name": display_name})
        rhythm_tracks = []
        for tid in cd.available_rhythm_track_ids:
            rhythm_tracks.append({
                "id": tid,
                "display_name": self.__track_display_name(
                    tid, cd.rhythm_track_metadata(tid)
                ),
            })
        return {
            "active_chord_track_id": cd.active_chord_track_id,
            "active_rhythm_track_id": cd.active_rhythm_track_id,
            "available_chord_tracks": chord_tracks,
            "available_rhythm_tracks": rhythm_tracks,
            "has_edited": cd.has_chord_track(_EDITED_TRACK_ID),
            "active_chord_version": self.active_chord_version(),
        }

    def select_analysis_tracks(self, chord_track_id=None, rhythm_track_id=None,
                               soft_fallback=False):
        available_chords = set(self.chord_data.available_chord_track_ids)
        available_rhythms = set(self.chord_data.available_rhythm_track_ids)

        # Validate the complete request before changing either active track.
        if chord_track_id is not None:
            if not isinstance(chord_track_id, str) or not chord_track_id.strip():
                if not soft_fallback:
                    raise ValueError("chord_track_id must be a non-empty string")
                chord_track_id = None
            if chord_track_id not in available_chords:
                if not soft_fallback:
                    raise ValueError(f"chord track \"{chord_track_id}\" not available")
                chord_track_id = None

        if rhythm_track_id is not None:
            if not isinstance(rhythm_track_id, str) or not rhythm_track_id.strip():
                if not soft_fallback:
                    raise ValueError("rhythm_track_id must be a non-empty string")
                rhythm_track_id = None
            if rhythm_track_id not in available_rhythms:
                if not soft_fallback:
                    raise ValueError(f"rhythm track \"{rhythm_track_id}\" not available")
                rhythm_track_id = None

        effective_chord = (
            chord_track_id if chord_track_id in available_chords
            else self.chord_data.active_chord_track_id
        )
        if effective_chord == _EDITED_TRACK_ID:
            edited_rhythm_id = self.__edited_rhythm_track_id()
            if rhythm_track_id is not None and rhythm_track_id != edited_rhythm_id:
                raise ValueError(
                    "Rhythm source is fixed to the Edited rhythm grid while the "
                    "Edited version is active"
                )
            rhythm_track_id = edited_rhythm_id

        changed = False
        if chord_track_id in available_chords:
            changed = chord_track_id != self.chord_data.active_chord_track_id
            self.chord_data.select_chord_track(chord_track_id)
        if rhythm_track_id in available_rhythms:
            changed = (
                rhythm_track_id != self.chord_data.active_rhythm_track_id
                or changed
            )
            self.chord_data.select_rhythm_track(rhythm_track_id)

        if changed:
            self.__build_playback_view()
            self.reset_render_cache()

    def select_chord_track(self, track_id):
        self.select_analysis_tracks(chord_track_id=track_id)

    def select_rhythm_track(self, track_id):
        self.select_analysis_tracks(rhythm_track_id=track_id)

    def track_summary(self):
        state = self.analysis_track_state()
        return {
            "chord": state["available_chord_tracks"],
            "rhythm": state["available_rhythm_tracks"],
        }

    def audio_stems_state(self, include_versions=False):
        """Return the complete Demucs stem set, or None when unavailable.

        Only a complete grouped set with all four expected FLAC stems that
        actually exist as regular files inside the media's analysis storage
        boundary is reported. Malformed metadata, incomplete sets, and missing
        or unsafe files all yield None. The player consumes the generic
        ChordData audio-track contract and never imports the optional producer
        package.

        When ``include_versions`` is true, a per-stem version token derived
        from the file's ``st_mtime_ns`` and ``st_size`` is included so the
        frontend can build stable, cache-friendly URLs that change only when a
        stem file is regenerated or replaced.
        """
        if getattr(self, "file_repr", None) is None:
            return None
        cd = self.chord_data
        if not cd.has_audio_track(STEMS_AUDIO_SET_ID):
            return None
        try:
            set_data = cd.audio_track_data(STEMS_AUDIO_SET_ID)
        except (KeyError, ValueError):
            return None
        tracks = set_data.get("tracks")
        if not isinstance(tracks, dict):
            return None
        media_path = Path(self.file_repr.get())
        storage_root = Path(self.file_repr.get("json")).resolve().parent
        stems = []
        versions = {}
        for stem_name in DEMUCS_STEM_NAMES:
            stem = tracks.get(stem_name)
            if not isinstance(stem, dict) or stem.get("format") != "flac":
                return None
            raw_path = stem.get("path")
            if not isinstance(raw_path, str) or not raw_path.strip():
                return None
            try:
                candidate = media_path.parent.joinpath(raw_path)
                if candidate.is_symlink():
                    return None
                resolved = candidate.resolve()
            except (OSError, RuntimeError, KeyError, TypeError, ValueError):
                return None
            if not resolved.is_relative_to(storage_root) or not resolved.is_file():
                return None
            if include_versions:
                try:
                    stat = resolved.stat()
                    versions[stem_name] = f"{stat.st_mtime_ns}-{stat.st_size}"
                except OSError:
                    return None
            stems.append(stem_name)
        result = {
            "set_id": STEMS_AUDIO_SET_ID,
            "stems": stems,
        }
        if include_versions:
            result["versions"] = versions
        return result

    # ── chord editing ─────────────────────────────────────────────────

    def has_edited_chords(self):
        return self.chord_data.has_chord_track(_EDITED_TRACK_ID)

    def active_chord_version(self):
        active = self.chord_data.active_chord_track_id
        return "edited" if active == _EDITED_TRACK_ID else "original"

    def start_chord_editing(self):
        cd = self.chord_data
        if not cd.has_chord_track(_EDITED_SOURCE_CHORD):
            raise ValueError("Chordino analysis is not available")
        if not cd.has_rhythm_track(DEFAULT_RHYTHM_TRACK):
            raise ValueError("QM beat track is not available")
        if not cd.rhythm_track_data(DEFAULT_RHYTHM_TRACK)["beat_times"]:
            raise ValueError("QM beat track has no beat times")
        if not cd.has_chord_track(_EDITED_TRACK_ID):
            cd.create_beat_aligned_track(
                _EDITED_TRACK_ID,
                source_chord_track_id=_EDITED_SOURCE_CHORD,
                source_rhythm_track_id=DEFAULT_RHYTHM_TRACK,
                metadata={"display_name": "Edited"},
            )
        self.select_analysis_tracks(chord_track_id=_EDITED_TRACK_ID)
        return self.analysis_track_state()

    def set_chord_version(self, version):
        if version == "edited":
            if not self.has_edited_chords():
                raise ValueError("No edited chord version exists")
            self.select_analysis_tracks(chord_track_id=_EDITED_TRACK_ID)
        elif version == "original":
            self.select_analysis_tracks(chord_track_id=_EDITED_SOURCE_CHORD)
        else:
            raise ValueError("version must be 'original' or 'edited'")

    def edit_chord(self, beat_index, label):
        cd = self.chord_data
        normalized = chordutils.validate_chord_label(label)
        if normalized in ("N", "X"):
            canonical = normalized
        else:
            canonical = chordutils.transpose_chord_pitches(
                normalized, -cd.transpose_semitones, cd.prefer_flats
            )

        rhythm_track_id = (
            self.__edited_rhythm_track_id()
            if cd.has_chord_track(_EDITED_TRACK_ID)
            else DEFAULT_RHYTHM_TRACK
        )
        beat_times = cd.rhythm_track_data(rhythm_track_id)["beat_times"]
        if not isinstance(beat_index, int) or isinstance(beat_index, bool):
            raise ValueError("beat_index must be an integer")
        if beat_index < 0 or beat_index >= len(beat_times):
            raise ValueError(
                f"beat_index {beat_index} out of range [0, {len(beat_times)})"
            )

        if not cd.has_chord_track(_EDITED_TRACK_ID):
            self.start_chord_editing()
        elif cd.active_chord_track_id != _EDITED_TRACK_ID:
            self.select_analysis_tracks(chord_track_id=_EDITED_TRACK_ID)
        cd.edit_chord_track_beat(
            _EDITED_TRACK_ID,
            beat_index,
            canonical,
            rhythm_track_id=rhythm_track_id,
        )
        self.__build_playback_view()
        self.reset_render_cache()

    def reset_edited_chords(self):
        if not self.has_edited_chords():
            raise ValueError("No edited chord version exists")
        if not self.chord_data.has_chord_track(_EDITED_SOURCE_CHORD):
            raise ValueError("Chordino analysis is not available")
        if not self.chord_data.has_rhythm_track(DEFAULT_RHYTHM_TRACK):
            raise ValueError("QM beat track is not available")
        metadata = self.chord_data.chord_track_metadata(_EDITED_TRACK_ID)
        sources = metadata.get("sources", {})
        edited_rhythm_id = sources.get("rhythm")
        self.chord_data.remove_chord_track(_EDITED_TRACK_ID)
        if (
            edited_rhythm_id == USER_EDITED_RHYTHM_TRACK_ID
            and self.chord_data.has_rhythm_track(edited_rhythm_id)
        ):
            self.chord_data.remove_rhythm_track(edited_rhythm_id)
        self.chord_data.select_chord_track(_EDITED_SOURCE_CHORD)
        self.chord_data.select_rhythm_track(DEFAULT_RHYTHM_TRACK)
        self.__build_playback_view()
        self.reset_render_cache()

    def __edited_rhythm_track_id(self):
        metadata = self.chord_data.chord_track_metadata(_EDITED_TRACK_ID)
        sources = metadata.get("sources")
        rhythm_track_id = sources.get("rhythm") if isinstance(sources, dict) else None
        if not isinstance(rhythm_track_id, str) or not rhythm_track_id:
            raise ValueError("Edited chord rhythm source metadata is invalid")
        if not self.chord_data.has_rhythm_track(rhythm_track_id):
            raise ValueError(
                f'Edited chord rhythm source "{rhythm_track_id}" is not available'
            )
        return rhythm_track_id

    def reload_chord_data(self, chord_track_id=None, rhythm_track_id=None,
                          soft_fallback=False):
        """Restore persisted chord data and the active view after a failed save.

        Reloads from the unchanged JSON on disk without altering display
        settings, the requested active analysis tracks, or the playback view.
        """
        use_unicode = self.chord_data.use_unicode
        prefer_flats = self.chord_data.prefer_flats
        repeat_mode = self.playback_view.repeat_mode
        self.chord_data = ChordData(use_unicode=use_unicode)
        self.chord_data.load_from_file(self.file_repr.get("json"))
        self.chord_data.transpose(self.semitones)
        self.chord_data.set_prefer_flats(prefer_flats)
        self.select_analysis_tracks(
            chord_track_id=chord_track_id,
            rhythm_track_id=rhythm_track_id,
            soft_fallback=soft_fallback,
        )
        self.__build_playback_view()
        self.playback_view.repeat_mode = repeat_mode
        self.reset_render_cache()

    def edit_grid(self, position=0.0):
        cd = self.chord_data
        beat_chords = cd.get_chords_per_beat()
        beat_count = len(beat_chords)
        meter = cd.meter_signature or 4
        beats_per_row = meter * _EDIT_GRID_MEASURES_PER_ROW
        empty = {
            "beat_time": 0.0,
            "active_beat_index": 0,
            "beats_per_row": beats_per_row,
            "beat_count": 0,
            "meter_signature": cd.meter_signature,
            "rows": [],
        }
        if beat_count == 0:
            return empty

        current_index = min(cd.get_beat_index_for_position(position), beat_count - 1)
        active_row_start = cd.get_grid_row_start(current_index)
        if active_row_start is None:
            active_row_start = current_index - (current_index % beats_per_row)
        start_index = active_row_start - beats_per_row

        rows = []
        for row in range(_EDIT_GRID_ROWS):
            cells = []
            for col in range(beats_per_row):
                abs_index = start_index + row * beats_per_row + col
                if 0 <= abs_index < beat_count:
                    chord = beat_chords[abs_index][1]
                    cells.append({
                        "beat_index": abs_index,
                        "chord": chord,
                        "active": abs_index == current_index,
                        "repeat": abs_index > 0 and beat_chords[abs_index - 1][1] == chord,
                    })
                else:
                    cells.append({
                        "beat_index": abs_index,
                        "chord": "",
                        "active": False,
                        "repeat": False,
                    })
            rows.append(cells)

        return {
            "beat_time": cd.beat_times[current_index],
            "active_beat_index": current_index,
            "beats_per_row": beats_per_row,
            "beat_count": beat_count,
            "meter_signature": cd.meter_signature,
            "rows": rows,
        }

    def chord_download_snapshot(self):
        """Return the plain display state for a Markdown leadsheet download."""
        cd = self.chord_data
        chord_id = cd.active_chord_track_id
        rhythm_id = cd.active_rhythm_track_id
        if chord_id and cd.has_chord_track(chord_id):
            chord_label = self.__track_display_name(
                chord_id, cd.chord_track_metadata(chord_id)
            )
        else:
            chord_label = chord_id or ""
        if rhythm_id and cd.has_rhythm_track(rhythm_id):
            rhythm_label = self.__track_display_name(
                rhythm_id, cd.rhythm_track_metadata(rhythm_id)
            )
        else:
            rhythm_label = rhythm_id or ""

        beat_chords = self.playback_view.full_beat_view()
        beat_numbers = cd.beat_numbers
        beats = [
            (beat_numbers[i] if i < len(beat_numbers) else "", chord)
            for i, chord in enumerate(beat_chords)
        ]
        return {
            "chord_track_id": chord_id,
            "chord_track_label": chord_label,
            "rhythm_track_label": rhythm_label,
            "version": self.active_chord_version(),
            "transpose": cd.transpose_semitones,
            "prefer_flats": cd.prefer_flats,
            "use_unicode": cd.use_unicode,
            "bpm": cd.bpm,
            "meter": cd.meter_signature,
            "repeat_mode": self.playback_view.repeat_mode,
            "beats": beats,
        }

    @staticmethod
    def __track_display_name(track_id, metadata):
        display_name = metadata.get("display_name")
        if isinstance(display_name, str) and display_name.strip():
            return display_name.strip()
        return _BUILTIN_TRACK_NAMES.get(track_id, track_id)

    def set_transpose(self, semitones):
        logging.info(f"Calling set_transpose({semitones})")
        self.chord_data._get_chords_cached.cache_clear()
        self.semitones = semitones
        self.chord_data.transpose(semitones)
        self.reset_render_cache()

    def set_prefer_flats(self, prefer_flats):
        self.chord_data.set_prefer_flats(prefer_flats)
        self.reset_render_cache()

    def set_repeat_mode(self, repeat_mode):
        self.playback_view.repeat_mode = repeat_mode
        self.reset_render_cache()

    def reset_render_cache(self):
        if hasattr(self, "last_index"):
            del self.last_index

    def _load_chords(self):
        try:
            self.chord_data.load_from_file(self.file_repr.get("json"))
            logging.info(f"Chords loaded from {self.file_repr.get('json')}")
        except Exception as e:
            logging.error(f"Error loading chords: {e}")

        try:
            self.song_data = SongData(self.file_repr.get("song_data"))
            logging.info(f"Songdata loaded from {self.file_repr.get('song_data')}")
        except Exception as e:
            logging.error(f"No Song File: {e}")

    def _default_callback(self, position):
        rendered = self.playback_view.render(position)
        if not rendered:
            return
        self.last_rendered_position = rendered["position"]

        if hasattr(self, "last_index") and self.last_index == rendered["index"]:
            return

        output = rendered["output"]
        print(output)
        self.callback_output.clear()
        self.callback_output.append(output)
        self.last_index = rendered["index"]

    def update_position(self, position, grid_mode=None):
        if grid_mode is not None:
            if grid_mode not in GRID_MODES:
                raise ValueError(
                    f"grid_mode must be one of: {', '.join(sorted(GRID_MODES))}"
                )
            if grid_mode != self.grid_mode:
                self.grid_mode = grid_mode
                self.__build_playback_view()
                self.reset_render_cache()
        self.position_callback(position)

    def get_callback_output(self):
        return {
            "callback_output": list(self.callback_output),
            "bpm": self.chord_data.bpm,
            "position": self.last_rendered_position,
        }
