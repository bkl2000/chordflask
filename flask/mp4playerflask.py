#!/usr/bin/env python3

from chorddata import ChordData
from songdata import SongData
from playbackview import PlaybackView
from collections import deque
import logging

_BUILTIN_TRACK_NAMES = {
    "chordino": "Chordino",
    "madmom": "Madmom",
    "qm_barbeattracker": "QM Bar/Beat Tracker",
}


class MP4PlayerFlask:
    def __init__(self, file_repr, semitones=0, max_lines=30, sync_chords=True,
                 position_callback=None, use_unicode=False, display_chord_offset=0.0,
                 metric_chords=False):
        self.file_repr = file_repr
        self.semitones = semitones
        self.max_lines = max_lines
        self.sync_chords = sync_chords
        self.display_chord_offset = display_chord_offset
        self.__metric_chords = metric_chords

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
        self.playback_view = PlaybackView(
            self.chord_data,
            display_chord_offset=self.display_chord_offset,
            metric_chords=self.__metric_chords,
        )

    def analysis_track_state(self):
        cd = self.chord_data
        chord_tracks = []
        for tid in cd.available_chord_track_ids:
            chord_tracks.append({
                "id": tid,
                "display_name": self.__track_display_name(
                    tid, cd.chord_track_metadata(tid)
                ),
            })
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
            if chord_track_id not in available_chords and not soft_fallback:
                raise ValueError(f"chord track \"{chord_track_id}\" not available")

        if rhythm_track_id is not None:
            if not isinstance(rhythm_track_id, str) or not rhythm_track_id.strip():
                if not soft_fallback:
                    raise ValueError("rhythm_track_id must be a non-empty string")
                rhythm_track_id = None
            if rhythm_track_id not in available_rhythms and not soft_fallback:
                raise ValueError(f"rhythm track \"{rhythm_track_id}\" not available")

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

    @staticmethod
    def __track_display_name(track_id, metadata):
        display_name = metadata.get("display_name")
        if isinstance(display_name, str) and display_name.strip():
            return display_name.strip()
        return _BUILTIN_TRACK_NAMES.get(track_id, track_id)

    def set_transpose(self, semitones):
        logging.info(f"Calling set_transpose({semitones})")
        self.chord_data.get_chords.cache_clear()
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

    def update_position(self, position):
        self.position_callback(position)

    def get_callback_output(self):
        return {
            "callback_output": list(self.callback_output),
            "bpm": self.chord_data.bpm,
            "position": self.last_rendered_position,
        }
