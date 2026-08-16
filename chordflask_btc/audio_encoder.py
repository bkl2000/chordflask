"""Bounded media decoding for the BTC analysis path."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


SAMPLE_RATE = 22_050
FFMPEG_TIMEOUT_SECONDS = 300


class AudioAnalysisError(RuntimeError):
    pass


def decode_mono_audio(
    media_path: Path,
    output_path: Path,
    timeout: int = FFMPEG_TIMEOUT_SECONDS,
    sample_rate: int = SAMPLE_RATE,
) -> None:
    """Decode one media file to an owned mono WAV file."""
    configured_ffmpeg = os.environ.get("CHORDFLASK_BTC_FFMPEG", "ffmpeg")
    ffmpeg = shutil.which(configured_ffmpeg)
    if ffmpeg is None:
        raise AudioAnalysisError(
            f"ffmpeg is missing ({configured_ffmpeg}); install the ffmpeg system package"
        )
    if output_path.exists():
        raise AudioAnalysisError(f"Refusing to replace temporary audio: {output_path}")
    command = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(media_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "wav",
        str(output_path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AudioAnalysisError(f"ffmpeg timed out after {timeout} seconds") from exc
    except OSError as exc:
        raise AudioAnalysisError(f"Could not start ffmpeg: {exc}") from exc
    if result.returncode != 0:
        detail = " ".join(result.stderr.split())[:400]
        raise AudioAnalysisError(f"ffmpeg failed ({result.returncode}): {detail or 'no details'}")
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise AudioAnalysisError("ffmpeg produced no audio data")
