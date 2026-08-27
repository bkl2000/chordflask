"""BTC inference orchestration: run ``btc-predict-raw`` and write ``chord_tracks.btc``.

BTC runs as an isolated subprocess (its own venv); this module only shells out
to the ``btc-predict-raw`` wrapper, normalizes the returned labels, and writes
the protected ``btc`` track atomically through the shared Schema-v3 helpers. It
never imports torch or BTC model code.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .audio_encoder import AudioAnalysisError, decode_mono_audio
from .normalize import normalize_btc_events
from .runtime import checkpoint_path, require_btc_runtime, wrapper_path
from .schema import (
    BTC_TRACK_ID,
    SchemaV3Error,
    analysis_json_path,
    load_analysis,
    write_btc_track,
)

MEDIA_SUFFIXES = {".mp3", ".mp4", ".webm"}
BTC_SAMPLE_RATE = 22050


class BtcPredictionError(RuntimeError):
    """A media file or the BTC runtime cannot produce a safe prediction."""


def regular_media(media_path: Path) -> Path:
    if media_path.is_symlink():
        raise BtcPredictionError(f"Media must not be a symlink: {media_path}")
    resolved = media_path.resolve()
    if not resolved.is_file() or resolved.suffix.lower() not in MEDIA_SUFFIXES:
        raise BtcPredictionError(
            f"Media must be a regular MP3/MP4/WebM file: {resolved}"
        )
    return resolved


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_sha256() -> str:
    """Return the SHA-256 of the verified BTC checkpoint."""
    return sha256(checkpoint_path())


def _run_raw(wrapper: Path, media_path: Path) -> list[dict[str, Any]]:
    try:
        result = subprocess.run(
            [str(wrapper), str(media_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise BtcPredictionError(f"Could not execute BTC wrapper: {exc}") from exc
    if result.returncode != 0:
        detail = " ".join((result.stderr or "").split())[:400]
        raise BtcPredictionError(f"BTC inference failed: {detail or 'no details'}")
    try:
        events = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise BtcPredictionError(f"BTC wrapper produced invalid JSON: {exc}") from exc
    if not isinstance(events, list):
        raise BtcPredictionError("BTC wrapper produced a non-list JSON payload")
    return events


def predict_btc_media(media_path: Path, *, replace: bool = False) -> dict[str, Any]:
    """Predict BTC chords for one media file.

    Returns ``{"status": "predicted"|"skipped", "events": N}``. When the file
    has no analysis yet, a minimal valid Schema-v3 file is created so the BTC
    track always lands somewhere. Raises :class:`BtcPredictionError` for an
    invalid existing analysis, a stale existing track (``use --replace``), or an
    inference failure. A failed run never leaves a partially changed file.
    """
    require_btc_runtime()
    media_path = regular_media(media_path)

    model_hash = model_sha256()
    media_hash = sha256(media_path)

    existing = None
    if analysis_json_path(media_path).exists(follow_symlinks=False):
        try:
            analysis, _ = load_analysis(media_path)
        except SchemaV3Error as exc:
            raise BtcPredictionError(f"invalid ChordFlask analysis ({exc})") from exc
        existing = analysis["chord_tracks"].get(BTC_TRACK_ID)

    if existing is not None:
        existing_metadata = existing.get("metadata", {}) if isinstance(existing, dict) else {}
        if (
            existing_metadata.get("model_sha256") == model_hash
            and existing_metadata.get("media_sha256") == media_hash
            and not replace
        ):
            return {"status": "skipped", "events": 0}
        if not replace:
            raise BtcPredictionError(
                "a different btc chord track already exists; use --replace to overwrite it"
            )

    try:
        with tempfile.TemporaryDirectory(prefix="btc-") as temporary:
            wav_path = Path(temporary) / "audio.wav"
            decode_mono_audio(media_path, wav_path, sample_rate=BTC_SAMPLE_RATE)
            raw_events = _run_raw(wrapper_path(), wav_path)
    except AudioAnalysisError as exc:
        raise BtcPredictionError(f"BTC inference failed: {exc}") from exc
    chords = normalize_btc_events(raw_events)
    metadata = {
        "display_name": "BTC",
        "engine": "BTC-ISMIR19",
        "vocabulary": "large-170",
        "model_sha256": model_hash,
        "media_sha256": media_hash,
        "experimental": True,
    }
    try:
        write_btc_track(
            media_path,
            chords,
            metadata,
            replace=existing is not None and replace,
        )
    except SchemaV3Error as exc:
        raise BtcPredictionError(str(exc)) from exc
    return {"status": "predicted", "events": len(chords)}
