import gc
import logging
import os
import statistics
import subprocess
import tempfile

import librosa
import vamp

from chorddata import ChordData
from chord_postprocess import ChordPostProcessor
from chordutils import detect_tempo_from_audio
from chordflask_config import ANALYSIS_SAMPLE_RATE
from ffmpeg_runtime import require_system_ffmpeg


class AudioAnalyzer:
    def __init__(
        self,
        sample_rate=ANALYSIS_SAMPLE_RATE,
        quantize_beats=False,
        postprocessor=None,
        beats_per_bar=4,
    ):
        if not isinstance(beats_per_bar, int) or not 2 <= beats_per_bar <= 16:
            raise ValueError("beats_per_bar must be an integer from 2 through 16")
        self.sample_rate = sample_rate
        self.quantize_beats = quantize_beats
        self.postprocessor = postprocessor or ChordPostProcessor.from_environment()
        self.beats_per_bar = beats_per_bar

    def analyze(self, mp3_path, use_madmom=False):
        require_system_ffmpeg()
        from vamp_runtime import require_vamp_plugins
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
        if self.quantize_beats:
            beat_times = self._quantize_beats(bpm, beat_times)
        print("Chords...", flush=True)
        if use_madmom:
            chord_source = "madmom"
            chords = self._extract_chords_madmom(mp3_path)
        else:
            chord_source = "chordino"
            chords = self._extract_chords_vamp(y, sr)
        chords = self.postprocessor.process(chords)

        chord_data.set_chord_track(chord_source, chords)
        chord_data.set_rhythm_track(
            "qm_barbeattracker",
            bpm=bpm,
            meter_signature=self.beats_per_bar,
            beat_times=beat_times,
            beat_numbers=beat_numbers,
        )
        return chord_data

    def _quantize_beats(self, bpm, beat_times):
        if not bpm or len(beat_times) < 2:
            return beat_times
        interval = 60 / bpm
        start = beat_times[0]
        return [round(start + i * interval, 6) for i in range(len(beat_times))]

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
