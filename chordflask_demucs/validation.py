"""Demucs source/stem validation and Schema-v3 set construction."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from .audio import AudioFacts
from .constants import (
    CHANNELS,
    DEMUCS_MODEL,
    DEMUCS_STEM_NAMES,
    MAX_TAIL_DELTA_SECONDS,
    SAMPLE_RATE,
)
from .runtime import RuntimeInfo


class DemucsValidationError(ValueError):
    """Source or stem facts violate the Demucs timing contract."""


def max_tail_delta_samples(sample_rate: int = SAMPLE_RATE) -> int:
    return max(1, round(MAX_TAIL_DELTA_SECONDS * sample_rate))


def validate_canonical_source(source: AudioFacts) -> None:
    if source.sample_rate != SAMPLE_RATE:
        raise DemucsValidationError(f"Canonical source sample rate {source.sample_rate} != {SAMPLE_RATE}")
    if source.channels != CHANNELS:
        raise DemucsValidationError(f"Canonical source channels {source.channels} != {CHANNELS}")
    if source.sample_count <= 0 or not math.isfinite(source.duration) or source.duration <= 0:
        raise DemucsValidationError("Canonical source has invalid duration")


def validate_raw_stems(
    source: AudioFacts,
    stems: dict[str, AudioFacts],
) -> dict[str, int]:
    """Validate raw Demucs timing and return signed tail adjustments."""
    validate_canonical_source(source)
    if set(stems) != set(DEMUCS_STEM_NAMES):
        raise DemucsValidationError("Demucs result does not contain exactly four expected stems")
    limit = max_tail_delta_samples(source.sample_rate)
    adjustments = {}
    for stem_name in DEMUCS_STEM_NAMES:
        facts = stems[stem_name]
        if facts.sample_count <= 0 or not math.isfinite(facts.duration) or facts.duration <= 0:
            raise DemucsValidationError(f"Stem {stem_name} has invalid duration")
        if facts.sample_rate != source.sample_rate or facts.channels != source.channels:
            raise DemucsValidationError(f"Stem {stem_name} has incompatible audio dimensions")
        if facts.start_time is not None and abs(facts.start_time) > 1 / source.sample_rate:
            raise DemucsValidationError(f"Stem {stem_name} has a non-zero start time")
        delta = source.sample_count - facts.sample_count
        if abs(delta) > limit:
            raise DemucsValidationError(
                f"Stem {stem_name} differs from the source by {abs(delta)} samples; "
                f"maximum allowed is {limit}"
            )
        adjustments[stem_name] = delta
    return adjustments


def validate_normalized_stems(
    source: AudioFacts,
    stems: dict[str, AudioFacts],
) -> None:
    """Require FLAC stems to share the exact canonical source timeline."""
    validate_canonical_source(source)
    if set(stems) != set(DEMUCS_STEM_NAMES):
        raise DemucsValidationError("Normalized result does not contain exactly four stems")
    for stem_name in DEMUCS_STEM_NAMES:
        facts = stems[stem_name]
        if facts.sample_count <= 0 or not math.isfinite(facts.duration) or facts.duration <= 0:
            raise DemucsValidationError(f"Stem {stem_name} has invalid duration")
        if facts.format != "flac" or facts.codec != "flac":
            raise DemucsValidationError(f"Stem {stem_name} is not FLAC")
        if (
            facts.sample_rate != source.sample_rate
            or facts.channels != source.channels
            or facts.sample_count != source.sample_count
        ):
            raise DemucsValidationError(f"Stem {stem_name} is not sample-aligned with the canonical source")


def pipeline_fingerprint(runtime: RuntimeInfo, *, device: str) -> str:
    payload = {
        "model": DEMUCS_MODEL,
        "demucs_version": runtime.demucs_version,
        "torch_version": runtime.torch_version,
        "device": device,
        "sample_rate": SAMPLE_RATE,
        "channels": CHANNELS,
        "format": "flac",
        "tail_policy_seconds": MAX_TAIL_DELTA_SECONDS,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialized).hexdigest()


def build_audio_track_set(
    *,
    source: AudioFacts,
    source_hash: str,
    source_size: int,
    source_timeline: dict,
    runtime: RuntimeInfo,
    device: str,
    stem_paths: dict[str, Path],
    stem_facts: dict[str, AudioFacts],
    stem_hashes: dict[str, str],
    stem_sizes: dict[str, int],
    tail_adjustments: dict[str, int],
    relative_to: Path,
) -> dict:
    sync = {
        "reference": "canonical_extracted_audio",
        "start_sample": 0,
        "source_sample_count": source.sample_count,
        "stem_sample_count": source.sample_count,
        "max_tail_delta_samples": max_tail_delta_samples(source.sample_rate),
        "tail_adjustment_samples": {stem: tail_adjustments[stem] for stem in DEMUCS_STEM_NAMES},
    }
    metadata = {
        "source": {
            "sha256": source_hash,
            "size": source_size,
            "sample_rate": source.sample_rate,
            "channels": source.channels,
            "sample_count": source.sample_count,
            "duration": source.duration,
        },
        "sync": sync,
        "source_timeline": source_timeline,
        "demucs_version": runtime.demucs_version,
        "torch_version": runtime.torch_version,
        "device": device,
        "pipeline_fingerprint": pipeline_fingerprint(runtime, device=device),
    }
    tracks = {}
    for stem_name in DEMUCS_STEM_NAMES:
        facts = stem_facts[stem_name]
        tracks[stem_name] = {
            "path": stem_paths[stem_name].relative_to(relative_to).as_posix(),
            "format": "flac",
            "sample_rate": facts.sample_rate,
            "channels": facts.channels,
            "sample_count": facts.sample_count,
            "duration": facts.duration,
            "size": stem_sizes[stem_name],
            "sha256": stem_hashes[stem_name],
        }
    return {
        "provider": "demucs",
        "model": DEMUCS_MODEL,
        "tracks": tracks,
        "metadata": metadata,
    }


__all__ = [
    "DemucsValidationError",
    "build_audio_track_set",
    "max_tail_delta_samples",
    "pipeline_fingerprint",
    "validate_canonical_source",
    "validate_normalized_stems",
    "validate_raw_stems",
]
