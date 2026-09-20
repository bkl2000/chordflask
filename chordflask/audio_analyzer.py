import gc
import logging
import math
import os
import statistics
import subprocess
import tempfile

import librosa
import vamp

from chordflask_base import ChordData
from .chord_postprocess import ChordPostProcessor
from .chordutils import detect_tempo_from_audio
from .chordflask_config import ANALYSIS_SAMPLE_RATE
from .ffmpeg_runtime import require_system_ffmpeg


AUTO_CORRECT_BEAT_GRID_ENV = "CHORDFLASK_AUTO_CORRECT_BEAT_GRID"
ORIGINAL_RHYTHM_TRACK = "qm_barbeattracker_original"


class AudioAnalyzer:
    # Count of detected beats; unit: beats.
    AUTO_GRID_MIN_BEATS = 16
    # Divide the song into at most this many diagnostic sections.
    AUTO_GRID_SECTION_COUNT = 8
    # Minimum section sizes; units: beats and adjacent intervals.
    AUTO_GRID_MIN_SECTION_BEATS = 4
    AUTO_GRID_MIN_SECTION_INTERVALS = 3
    # Long-baseline interval-estimation spans; divisors and minimum in beats.
    AUTO_GRID_INTERVAL_SPAN_DIVISORS = (4, 3, 2)
    AUTO_GRID_MIN_INTERVAL_SPAN_BEATS = 2
    # Allowed adjacent interval range relative to the estimated beat interval.
    AUTO_GRID_MIN_INTERVAL_RATIO = 0.55
    AUTO_GRID_MAX_INTERVAL_RATIO = 1.45
    # Maximum spread of local median intervals relative to one beat interval.
    AUTO_GRID_MAX_LOCAL_INTERVAL_VARIATION = 0.04
    # Maximum section-offset spread relative to one beat interval.
    AUTO_GRID_MAX_SECTION_DRIFT = 0.10
    # Maximum median and 95th-percentile errors relative to one beat interval.
    AUTO_GRID_MAX_MEDIAN_ERROR = 0.06
    AUTO_GRID_ERROR_QUANTILE = 0.95
    AUTO_GRID_MAX_QUANTILE_ERROR = 0.15
    # Rejection begins at this assignment error relative to one beat interval.
    AUTO_GRID_MAX_ASSIGNMENT_ERROR = 0.45
    # Absolute seconds below which an already exact grid is left untouched.
    AUTO_GRID_EXACT_ERROR_SECONDS = 1e-9

    def __init__(
        self,
        sample_rate=ANALYSIS_SAMPLE_RATE,
        quantize_beats=False,
        postprocessor=None,
        beats_per_bar=4,
        *,
        auto_correct_beat_grid=None,
    ):
        if not isinstance(beats_per_bar, int) or not 2 <= beats_per_bar <= 16:
            raise ValueError("beats_per_bar must be an integer from 2 through 16")
        self.sample_rate = sample_rate
        self.quantize_beats = quantize_beats
        if auto_correct_beat_grid is None:
            auto_correct_beat_grid = self._auto_correct_beat_grid_from_environment()
        if not isinstance(auto_correct_beat_grid, bool):
            raise ValueError("auto_correct_beat_grid must be a boolean")
        if quantize_beats and auto_correct_beat_grid:
            raise ValueError(
                "quantize_beats and auto_correct_beat_grid cannot both be enabled"
            )
        self.auto_correct_beat_grid = auto_correct_beat_grid
        self.postprocessor = postprocessor or ChordPostProcessor.from_environment()
        self.beats_per_bar = beats_per_bar

    def analyze(self, mp3_path, use_madmom=False):
        require_system_ffmpeg()
        from .vamp_runtime import require_vamp_plugins
        require_vamp_plugins()
        chord_data = ChordData(prefer_flats=True, use_unicode=False)
        chord_data.sr = self.sample_rate
        print(f"Start analyzing: {mp3_path}")
        print("Load...", flush=True)
        y, sr = librosa.load(mp3_path, sr=self.sample_rate, mono=True)
        print("Beat grid...", flush=True)
        bpm, beat_times, beat_numbers = self._detect_beat_grid(y, sr)
        print("Preemphasis...", flush=True)
        y = librosa.effects.preemphasis(y)
        print("BPM", bpm)
        original_rhythm = None
        if self.quantize_beats:
            beat_times = self._quantize_beats(bpm, beat_times)
        elif self.auto_correct_beat_grid:
            corrected_times, correction = self._auto_correct_beats(
                beat_times, beat_numbers
            )
            self._log_beat_grid_correction(correction)
            if correction["applied"]:
                original_rhythm = {
                    "bpm": bpm,
                    "meter_signature": self.beats_per_bar,
                    "beat_times": beat_times,
                    "beat_numbers": beat_numbers,
                    "metadata": {
                        "display_name": "QM Bar/Beat Tracker (original)",
                    },
                }
                bpm = correction["estimated_bpm"]
                beat_times = corrected_times
        print("Chords...", flush=True)
        if use_madmom:
            chord_source = "madmom"
            chords = self._extract_chords_madmom(mp3_path)
        else:
            chord_source = "chordino"
            chords = self._extract_chords_vamp(y, sr)
        chords = self.postprocessor.process(chords)

        chord_data.set_chord_track(chord_source, chords)
        if original_rhythm is not None:
            chord_data.set_rhythm_track(ORIGINAL_RHYTHM_TRACK, **original_rhythm)
        chord_data.set_rhythm_track(
            "qm_barbeattracker",
            bpm=bpm,
            meter_signature=self.beats_per_bar,
            beat_times=beat_times,
            beat_numbers=beat_numbers,
            metadata=(
                {
                    "display_name": "QM Bar/Beat Tracker (automatic grid correction)",
                    "source_rhythm_track": ORIGINAL_RHYTHM_TRACK,
                }
                if original_rhythm is not None
                else None
            ),
        )
        return chord_data

    @staticmethod
    def _auto_correct_beat_grid_from_environment():
        value = os.environ.get(AUTO_CORRECT_BEAT_GRID_ENV, "0").strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off", ""}:
            return False
        raise ValueError(
            f"{AUTO_CORRECT_BEAT_GRID_ENV} must be one of "
            "0/1, false/true, no/yes, or off/on"
        )

    def _quantize_beats(self, bpm, beat_times):
        if not bpm or len(beat_times) < 2:
            return beat_times
        interval = 60 / bpm
        start = beat_times[0]
        return [round(start + i * interval, 6) for i in range(len(beat_times))]

    def _auto_correct_beats(self, beat_times, beat_numbers):
        """Return a constant grid only when the detected beats support it safely."""
        diagnostics = {
            "estimated_bpm": None,
            "beat_interval": None,
            "median_error": None,
            "p95_error": None,
            "max_error": None,
            "local_interval_variation": None,
            "section_drift": None,
        }

        def rejected(reason, details=None):
            result = {
                "applied": False,
                "reason": reason,
                **diagnostics,
            }
            if details is not None:
                result["details"] = details
            return result

        if len(beat_times) < self.AUTO_GRID_MIN_BEATS:
            return beat_times, rejected(
                "too few beats",
                f"beat_count={len(beat_times)} "
                f"minimum={self.AUTO_GRID_MIN_BEATS}",
            )
        if len(beat_numbers) != len(beat_times):
            return beat_times, rejected("beat numbers are missing or incomplete")
        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < 0
            for value in beat_times
        ):
            return beat_times, rejected("beat timestamps are invalid")
        if any(
            later <= earlier
            for earlier, later in zip(beat_times, beat_times[1:], strict=False)
        ):
            return beat_times, rejected("beat timestamps are not strictly increasing")
        intervals = [
            later - earlier
            for earlier, later in zip(beat_times, beat_times[1:], strict=False)
        ]
        # Long-baseline slopes use the whole song and make periodic jitter or
        # a few timestamp outliers much less influential than adjacent gaps.
        spans = {
            max(
                self.AUTO_GRID_MIN_INTERVAL_SPAN_BEATS,
                len(beat_times) // divisor,
            )
            for divisor in self.AUTO_GRID_INTERVAL_SPAN_DIVISORS
        }
        interval = statistics.median(
            (beat_times[index + span] - beat_times[index]) / span
            for span in spans
            for index in range(len(beat_times) - span)
        )
        estimated_bpm = 60.0 / interval

        origin = statistics.median(
            timestamp - index * interval
            for index, timestamp in enumerate(beat_times)
        )
        residuals = [
            timestamp - (origin + index * interval)
            for index, timestamp in enumerate(beat_times)
        ]
        absolute_errors = sorted(abs(value) for value in residuals)
        median_error = statistics.median(absolute_errors)
        p95_error = absolute_errors[
            math.ceil(self.AUTO_GRID_ERROR_QUANTILE * len(absolute_errors)) - 1
        ]
        max_error = max(absolute_errors)
        diagnostics.update(
            estimated_bpm=estimated_bpm,
            beat_interval=interval,
            median_error=median_error,
            p95_error=p95_error,
            max_error=max_error,
        )

        if any(
            later != (earlier % self.beats_per_bar) + 1
            for earlier, later in zip(beat_numbers, beat_numbers[1:], strict=False)
        ):
            return beat_times, rejected(
                "beat-number sequence indicates a missing or additional beat",
            )

        # An interval outside this range cannot represent the same adjacent beat
        # on the candidate grid. This catches dropped/duplicated beats before a
        # later robust fit could hide their index shift.
        interval_ratios = [value / interval for value in intervals]
        if any(
            not self.AUTO_GRID_MIN_INTERVAL_RATIO * interval
            <= value
            <= self.AUTO_GRID_MAX_INTERVAL_RATIO * interval
            for value in intervals
        ):
            return beat_times, rejected(
                "adjacent intervals do not have an unambiguous one-beat mapping",
                f"interval_ratio_range={min(interval_ratios):.6f}.."
                f"{max(interval_ratios):.6f} allowed="
                f"{self.AUTO_GRID_MIN_INTERVAL_RATIO:.6f}.."
                f"{self.AUTO_GRID_MAX_INTERVAL_RATIO:.6f}",
            )

        section_size = max(
            self.AUTO_GRID_MIN_SECTION_BEATS,
            math.ceil(len(beat_times) / self.AUTO_GRID_SECTION_COUNT),
        )
        sections = [
            residuals[start : start + section_size]
            for start in range(0, len(residuals), section_size)
            if len(residuals[start : start + section_size])
            >= self.AUTO_GRID_MIN_SECTION_BEATS
        ]
        section_offsets = [statistics.median(section) for section in sections]
        local_intervals = []
        for start in range(0, len(intervals), section_size):
            section = intervals[start : start + section_size]
            if len(section) >= self.AUTO_GRID_MIN_SECTION_INTERVALS:
                local_intervals.append(statistics.median(section))

        local_interval_variation = (
            max(local_intervals) - min(local_intervals)
            if local_intervals
            else None
        )
        section_drift = (
            max(section_offsets) - min(section_offsets)
            if section_offsets
            else None
        )
        diagnostics.update(
            local_interval_variation=local_interval_variation,
            section_drift=section_drift,
        )

        if local_intervals and (
            local_interval_variation
            > self.AUTO_GRID_MAX_LOCAL_INTERVAL_VARIATION * interval
        ):
            return beat_times, rejected(
                "local tempo is not constant",
                f"local_interval_variation="
                f"{local_interval_variation / interval:.3%} "
                f"limit={self.AUTO_GRID_MAX_LOCAL_INTERVAL_VARIATION:.3%}",
            )
        if section_offsets and (
            section_drift > self.AUTO_GRID_MAX_SECTION_DRIFT * interval
        ):
            return beat_times, rejected(
                "section offsets show systematic drift",
                f"section_drift={section_drift * 1000:.3f}ms "
                f"({section_drift / interval:.3%} beat) limit="
                f"{self.AUTO_GRID_MAX_SECTION_DRIFT * interval * 1000:.3f}ms "
                f"({self.AUTO_GRID_MAX_SECTION_DRIFT:.3%} beat)",
            )
        if (
            median_error > self.AUTO_GRID_MAX_MEDIAN_ERROR * interval
            or p95_error > self.AUTO_GRID_MAX_QUANTILE_ERROR * interval
        ):
            return beat_times, rejected(
                "grid deviation is too large",
                f"median_limit="
                f"{self.AUTO_GRID_MAX_MEDIAN_ERROR * interval * 1000:.3f}ms "
                f"({self.AUTO_GRID_MAX_MEDIAN_ERROR:.3%} beat) "
                f"p95_limit="
                f"{self.AUTO_GRID_MAX_QUANTILE_ERROR * interval * 1000:.3f}ms "
                f"({self.AUTO_GRID_MAX_QUANTILE_ERROR:.3%} beat)",
            )
        if max_error >= self.AUTO_GRID_MAX_ASSIGNMENT_ERROR * interval:
            return beat_times, rejected(
                "a beat cannot be assigned unambiguously to the grid",
                f"max_error_limit="
                f"{self.AUTO_GRID_MAX_ASSIGNMENT_ERROR * interval * 1000:.3f}ms "
                f"({self.AUTO_GRID_MAX_ASSIGNMENT_ERROR:.3%} beat; reject at >=)",
            )
        if max_error <= self.AUTO_GRID_EXACT_ERROR_SECONDS:
            return beat_times, rejected(
                "beats are already on an exact grid",
                f"max_error={max_error * 1000:.9f}ms limit="
                f"{self.AUTO_GRID_EXACT_ERROR_SECONDS * 1000:.9f}ms",
            )

        corrected = [
            round(origin + index * interval, 6)
            for index in range(len(beat_times))
        ]
        if corrected[0] < 0:
            return beat_times, rejected(
                "estimated grid starts before the media timeline",
                f"grid_start={corrected[0] * 1000:.3f}ms minimum=0.000ms",
            )
        return corrected, {
            "applied": True,
            "reason": "constant tempo and stable grid",
            **diagnostics,
        }

    @staticmethod
    def _log_beat_grid_correction(result):
        status = "applied" if result["applied"] else "rejected"
        bpm = result["estimated_bpm"]
        interval = result["beat_interval"]
        median_error = result["median_error"]
        p95_error = result["p95_error"]
        max_error = result["max_error"]

        def error_text(value):
            if value is None or interval is None:
                return "n/a"
            return f"{value * 1000:.3f}ms ({value / interval:.3%} beat)"

        logging.info(
            "Automatic beat-grid correction %s: bpm=%s median_error=%s "
            "p95_error=%s max_error=%s reason=%s%s",
            status,
            f"{bpm:.6f}" if bpm is not None else "n/a",
            error_text(median_error),
            error_text(p95_error),
            error_text(max_error),
            result["reason"],
            f"; {result['details']}" if "details" in result else "",
        )

    @staticmethod
    def _feature_beat_number(feature):
        label = str(feature.get("label", "")).strip()
        try:
            return int(label)
        except ValueError:
            values = feature.get("values", [])
            if len(values) == 1 and float(values[0]).is_integer():
                return int(values[0])
        return None

    def _detect_beat_grid(self, y, sr):
        """Return QM beat timestamps and their position within each bar."""
        data = vamp.collect(
            y,
            sr,
            "qm-vamp-plugins:qm-barbeattracker",
            output="beatcounts",
            parameters={"bpb": self.beats_per_bar},
        )
        features = data.get("list", [])
        beat_times = []
        beat_numbers = []
        malformed_count = 0
        for feature in features:
            beat_number = self._feature_beat_number(feature)
            if beat_number is None:
                malformed_count += 1
                continue
            if beat_number <= 0:
                continue
            beat_times.append(float(feature["timestamp"]))
            beat_numbers.append(beat_number)

        if malformed_count:
            logging.warning(
                "Ignored %d beat feature(s) with unparseable beat-number labels.",
                malformed_count,
            )

        if len(beat_times) < 2:
            # Keep unusual or beatless material analyzable. It cannot provide a
            # bar phase, so the renderer intentionally uses its legacy fallback.
            bpm, fallback_times = detect_tempo_from_audio(sr=sr, y=y)
            return bpm, fallback_times, []

        intervals = [
            later - earlier
            for earlier, later in zip(beat_times, beat_times[1:], strict=False)
            if later > earlier
        ]
        bpm = round(60 / statistics.median(intervals)) if intervals else None
        return bpm, beat_times, beat_numbers

    def _extract_chords_vamp(self, y, sr):
        params = {"useNNLS": 1, "rollon": 0.02, "tuningmode": 1}
        data = vamp.collect(y, sr, "nnls-chroma:chordino", parameters=params)
        chords = [{"timestamp": float(e['timestamp']), "chord": e['label']} for e in data['list']]
        del y, data
        gc.collect()
        return chords

    def _extract_chords_madmom(self, mp3_path):
        from madmom.features.chords import CRFChordRecognitionProcessor

        ffmpeg_path = require_system_ffmpeg()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmpfile:
            wav_path = tmpfile.name
        try:
            try:
                subprocess.run(
                    [ffmpeg_path, "-y", "-i", mp3_path, wav_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    check=True,
                    text=True,
                )
            except subprocess.CalledProcessError as error:
                diagnostic = (error.stderr or "ffmpeg conversion failed").strip()[-2000:]
                raise RuntimeError(f"Could not convert audio for madmom: {diagnostic}") from error
            proc = CRFChordRecognitionProcessor()
            results = proc(wav_path)
            return [{"timestamp": float(start), "chord": str(label)} for (start, end, label) in results]
        finally:
            try:
                os.unlink(wav_path)
            except FileNotFoundError:
                pass

    def detect_meter(self, mp3_path):
        """Return the configured QM meter for the compatibility facade."""
        return self.beats_per_bar
