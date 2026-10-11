"""Lightweight bridge to isolated, offline Qwen inference; no Torch imports."""
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from .lrclib import TimedLyricLine


class Qwen3AlignmentError(RuntimeError):
    """Friendly CLI failure with the worker's existing stderr diagnostics."""

    def __init__(self, start, end, diagnostic):
        super().__init__(
            f"Lyrics V2 could not be generated: Qwen3 could not reliably align the vocals "
            f"at {start:g}–{end:g} s. This recording is not supported reliably by the "
            "experimental model. No V2 file was written; existing lyrics remain unchanged."
        )
        self.diagnostic = diagnostic


def runtime_directory():
    return Path(os.environ.get("CHORDFLASK_QWEN3_VENV", Path.home() / ".venvs/chordflask-qwen3-asr"))


def audio_input(media):
    """Use only the existing producer's fully validated, current stem set."""
    from chordflask_demucs.storage import CURRENT, classify, AUDIO_SET_ID

    status = classify(media)
    if status.label == CURRENT:
        from chordflask_base import ChordTrackRepository, analysis_json_path
        data = ChordTrackRepository().load(analysis_json_path(media)).audio_track_data(AUDIO_SET_ID)
        return media.parent / data["tracks"]["vocals"]["path"]
    return media


def timed_lyrics(media):
    runtime = runtime_directory()
    python = runtime / "bin" / "python"
    if not python.is_file():
        raise RuntimeError("Qwen3 runtime missing; run make setup-qwen3-asr")
    source = audio_input(media)
    print(f"Qwen3 audio input: {source}", file=sys.stderr)
    environment = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    # Execute the reviewed worker from this installation, not stale code in a second venv.
    command = [str(python), "-I", str(Path(__file__).with_name("qwen3_worker.py")),
               "--models", str(runtime / "models"), "--audio", str(source.resolve())]
    try:
        # Parent ownership also cleans decoded audio if the worker is killed
        # by the subprocess timeout, without depending on worker finalizers.
        with tempfile.TemporaryDirectory(prefix="chordflask-qwen3-job-") as work:
            result = subprocess.run(command + ["--work-directory", work], capture_output=True,
                                    text=True, env=environment, timeout=7200, check=False)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Qwen3 inference timed out; no Lyrics files changed") from error
    if result.returncode:
        diagnostic = f"Qwen3 failed: {result.stderr[-3000:].strip()}"
        try:
            failure = json.loads(result.stdout)
        except (ValueError, TypeError):
            failure = None
        if isinstance(failure, dict) and failure.get("error") == "alignment_no_duration":
            start, end = failure.get("start"), failure.get("end")
            if (all(type(t) in (float, int) and math.isfinite(t) for t in (start, end))
                    and 0 <= start < end):
                raise Qwen3AlignmentError(start, end, diagnostic) from RuntimeError(diagnostic)
        raise RuntimeError(diagnostic)
    try:
        data = json.loads(result.stdout)
        from .qwen3_worker import validate_spans, lines_from_spans
        spans = validate_spans(data["spans"], data["duration"])
        lines = tuple(TimedLyricLine(time, text) for time, text in lines_from_spans(spans))
        languages = data["languages"]
        if not isinstance(languages, list) or not languages or any(
            not isinstance(language, str) or not language.strip() for language in languages
        ):
            raise ValueError("missing detected languages")
        device = data["device"]
        if device not in ("cpu", "cuda:0"):
            raise ValueError("invalid device")
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError(f"Invalid Qwen3 result: {error}") from error
    return lines, {"x_chordflask_analyzer": "qwen3",
                   "x_chordflask_model": "Qwen/Qwen3-ASR-1.7B",
                   "x_chordflask_alignment": "Qwen/Qwen3-ForcedAligner-0.6B; official timestamp correction",
                   "x_chordflask_audio": str(source), "x_chordflask_device": device,
                   "x_chordflask_language": ", ".join(data["languages"])}
