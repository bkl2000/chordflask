#!/usr/bin/env python3

import logging

from chordutils import render_chord_output
from metric_chords import filter_metric_chords, format_classification_diagnostic


class PlaybackView:
    __GRID_MEASURES_PER_ROW = 2
    __GRID_ROWS = 16

    def __init__(
        self,
        chord_data,
        display_chord_offset=0.0,
        use_beat_sync=True,
        repeat_mode="changes",
        metric_chords=False,
    ):
        self.chord_data = chord_data
        self.display_chord_offset = display_chord_offset
        self.use_beat_sync = use_beat_sync
        self.repeat_mode = repeat_mode
        self.__metric_chords = metric_chords
        self.__suppressed_beats = set()

        if self.__metric_chords:
            self.__apply_metric_filter()

    def __apply_metric_filter(self):
        beat_chords = self.chord_data.get_chords_per_beat()
        if not beat_chords:
            logging.info("metric_chords: no beat chords available")
            return

        filtered, classification = filter_metric_chords(
            beat_chords,
            self.chord_data.beat_times,
            self.chord_data.beat_numbers,
            self.chord_data.beat_chord_indexes,
            self.chord_data.meter_signature,
            self.chord_data.chord_times,
        )
        logging.info(format_classification_diagnostic(classification))

        if classification["classification"] == "stable":
            for i in range(1, len(beat_chords) - 1):
                if filtered[i][1] != beat_chords[i][1]:
                    self.__suppressed_beats.add(i)

    def __get_metric_chords(self, beat_chords):
        if not self.__suppressed_beats:
            return beat_chords
        result = list(beat_chords)
        for i in sorted(self.__suppressed_beats):
            if 0 <= i - 1 < len(result):
                result[i] = (result[i][0], result[i - 1][1])
        return result

    def full_beat_view(self):
        """Return one displayed chord per beat after the metric filter."""
        beat_chords = self.chord_data.get_chords_per_beat()
        if self.__metric_chords:
            beat_chords = self.__get_metric_chords(beat_chords)
        return [chord for _, chord in beat_chords]

    def render(self, position):
        lookup_position = position + self.display_chord_offset

        if self.use_beat_sync:
            current_index = self.chord_data.get_beat_index_for_position(lookup_position)
        else:
            chords = self.chord_data.get_next_chords(lookup_position, 4)
            if not chords:
                return None
            current_index = self.chord_data.get_chord_index_by_timestamp(chords[0][0])

        full_chords = self.chord_data.get_chords_per_beat()
        if self.__metric_chords:
            full_chords = self.__get_metric_chords(full_chords)
        if current_index >= len(self.chord_data.beat_times):
            logging.info(f"PlaybackView beat_times: {full_chords[:10]} ... total: {len(full_chords)}")
            logging.info(f"PlaybackView current index too big: {current_index}")
            return None

        beat_time = self.chord_data.beat_times[current_index]
        chords = full_chords[current_index:current_index + 4]
        output = render_chord_output(
            style="grid",
            beat_time=beat_time,
            chords=[ch for _, ch in chords],
            all_chords=full_chords,
            active_index=current_index,
            beats_per_row=(
                (self.chord_data.meter_signature or 4)
                * self.__GRID_MEASURES_PER_ROW
            ),
            rows=self.__GRID_ROWS,
            active_row_start=self.chord_data.get_grid_row_start(current_index),
            repeat_mode=self.repeat_mode
        )
        return {
            "index": current_index,
            "output": output,
            "bpm": self.chord_data.bpm,
            "position": position,
        }
