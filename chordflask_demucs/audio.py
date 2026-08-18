"""FFmpeg boundaries and audio-file facts for Demucs processing."""

from __future__ import annotations

import json
import hashlib
import math
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

from .constants import CHANNELS, SAMPLE_RATE


class AudioCommandError(RuntimeError):
    """An FFmpeg or FFprobe command failed."""


class AudioValidationError(ValueError):
    """An audio file does not contain the expected stream facts."""


@dataclass(frozen=True)
class AudioFacts:
    format: str
    codec: str
    sample_rate: int
    channels: int
    sample_count: int
    duration: float
    start_time: float | None = None
    start_pts: int | None = None
    time_base: str | None = None
    stream_index: int | None = None
    container_start_time: float | None = None


def executable(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise AudioCommandError(
            f"Required executable not found: {name}. Install it with: sudo apt install ffmpeg"
        )
    return path


def _run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except OSError as error:
        raise AudioCommandError(f"Could not execute {command[0]}: {error}") from error
    except subprocess.TimeoutExpired as error:
        raise AudioCommandError(f"Command timed out: {command[0]}") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise AudioCommandError(
            f"Command failed ({result.returncode}): {command[0]}\n{detail or 'no diagnostics'}"
        )
    return result


def _optional_float(value):
    if value is None or value == "N/A":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _optional_int(value):
    if value is None or value == "N/A":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sample_count_from_stream(stream: dict, sample_rate: int, duration: float | None) -> int:
    duration_ts = _optional_int(stream.get("duration_ts"))
    time_base = stream.get("time_base")
    if duration_ts is not None and isinstance(time_base, str) and "/" in time_base:
        numerator, denominator = time_base.split("/", 1)
        try:
            exact = duration_ts * int(numerator) * sample_rate / int(denominator)
        except (TypeError, ValueError, ZeroDivisionError):
            exact = None
        if exact is not None and math.isfinite(exact):
            rounded = round(exact)
            if abs(exact - rounded) < 1e-6:
                return rounded
    for key in ("nb_read_frames", "nb_frames"):
        count = _optional_int(stream.get(key))
        if count is not None and count > 0:
            return count
    if duration is not None:
        return max(1, round(duration * sample_rate))
    raise AudioValidationError("Audio stream has no usable duration or sample count")


def probe_audio(path: Path, *, ffprobe_bin: str | None = None, timeout: int = 120) -> AudioFacts:
    """Probe the first audio stream and return normalized numeric facts."""
    probe = ffprobe_bin or executable("ffprobe")
    command = [
        probe,
        "-v",
        "error",
        "-count_frames",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=index,codec_name,start_time,start_pts,time_base,duration,duration_ts,"
        "sample_rate,channels,nb_frames,nb_read_frames:format=format_name,start_time,duration",
        "-of",
        "json",
        str(path),
    ]
    result = _run(command, timeout=timeout)
    try:
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise AudioValidationError(f"FFprobe returned no usable audio stream for {path}") from error

    sample_rate = _optional_int(stream.get("sample_rate"))
    channels = _optional_int(stream.get("channels"))
    duration = _optional_float(stream.get("duration"))
    if sample_rate is None or sample_rate <= 0:
        raise AudioValidationError(f"Invalid audio sample rate for {path}")
    if channels is None or channels <= 0:
        raise AudioValidationError(f"Invalid audio channel count for {path}")
    if duration is None or duration <= 0:
        duration = _optional_float(payload.get("format", {}).get("duration"))
    if duration is None or duration <= 0:
        raise AudioValidationError(f"Invalid audio duration for {path}")

    format_name = str(payload.get("format", {}).get("format_name", "unknown")).split(",", 1)[0]
    return AudioFacts(
        format=format_name,
        codec=str(stream.get("codec_name", "unknown")),
        sample_rate=sample_rate,
        channels=channels,
        sample_count=_sample_count_from_stream(stream, sample_rate, duration),
        duration=duration,
        start_time=_optional_float(stream.get("start_time")),
        start_pts=_optional_int(stream.get("start_pts")),
        time_base=stream.get("time_base") if isinstance(stream.get("time_base"), str) else None,
        stream_index=_optional_int(stream.get("index")),
        container_start_time=_optional_float(payload.get("format", {}).get("start_time")),
    )


def probe_canonical_wav(path: Path) -> AudioFacts:
    """Read exact frame counts from the temporary PCM WAV reference."""
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            sample_rate = handle.getframerate()
            sample_count = handle.getnframes()
            sample_width = handle.getsampwidth()
    except (OSError, wave.Error) as error:
        raise AudioValidationError(f"Could not read canonical WAV {path}: {error}") from error
    if sample_rate <= 0 or channels <= 0 or sample_count <= 0 or sample_width <= 0:
        raise AudioValidationError(f"Canonical WAV has invalid facts: {path}")
    return AudioFacts(
        format="wav",
        codec=f"pcm_s{sample_width * 8}le",
        sample_rate=sample_rate,
        channels=channels,
        sample_count=sample_count,
        duration=sample_count / sample_rate,
    )


def probe_source_timeline(path: Path, *, ffprobe_bin: str | None = None) -> dict:
    """Return original-container timing fields without changing them."""
    facts = probe_audio(path, ffprobe_bin=ffprobe_bin)
    available = any(
        value is not None
        for value in (facts.start_time, facts.start_pts, facts.time_base, facts.container_start_time)
    )
    return {
        "available": available,
        "audio_stream_index": facts.stream_index,
        "start_time": facts.start_time,
        "start_pts": facts.start_pts,
        "time_base": facts.time_base,
        "container_start_time": facts.container_start_time,
    }


def extract_canonical_audio(media_path: Path, output_wav: Path, *, timeout: int = 600) -> None:
    ffmpeg = executable("ffmpeg")
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(media_path),
            "-map",
            "0:a:0",
            "-vn",
            "-sn",
            "-dn",
            "-ac",
            str(CHANNELS),
            "-ar",
            str(SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            str(output_wav),
        ],
        timeout=timeout,
    )


def convert_wav_to_flac(
    source_wav: Path,
    output_flac: Path,
    *,
    target_sample_count: int,
    timeout: int = 600,
) -> None:
    ffmpeg = executable("ffmpeg")
    output_flac.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(source_wav),
            "-map",
            "0:a:0",
            "-af",
            f"apad=whole_len={target_sample_count},atrim=end_sample={target_sample_count}",
            "-ac",
            str(CHANNELS),
            "-ar",
            str(SAMPLE_RATE),
            "-map_metadata",
            "-1",
            "-c:a",
            "flac",
            "-compression_level",
            "5",
            "-sample_fmt",
            "s16",
            str(output_flac),
        ],
        timeout=timeout,
    )


def hash_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "AudioCommandError",
    "AudioFacts",
    "AudioValidationError",
    "convert_wav_to_flac",
    "executable",
    "extract_canonical_audio",
    "hash_file",
    "probe_audio",
    "probe_canonical_wav",
    "probe_source_timeline",
]
