"""Lightweight external-runtime preparation for the currently loaded song."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

CAPABILITY_TTL_SECONDS = 60

_capability_lock = threading.Lock()
_capability_cache: dict[str, dict] = {}

DEFAULT_LYRICS_VENV = Path.home() / ".venvs" / "chordflask-lyrics"


def lyrics_command() -> Path | None:
    """Resolve the external Lyrics helper, with a source-install fallback."""
    configured = os.environ.get("CHORDFLASK_LYRICS_VENV")
    runtime = Path(configured) if configured else DEFAULT_LYRICS_VENV
    helper = runtime / "bin" / "chordflask-genlyrics"
    if helper.is_file() and os.access(helper, os.X_OK):
        return helper
    if not getattr(sys, "frozen", False):
        sibling = Path(sys.executable).parent / "chordflask-genlyrics"
        if sibling.is_file() and os.access(sibling, os.X_OK):
            return sibling
    return None


def _cached_capability(name: str, probe) -> dict:
    now = time.monotonic()
    with _capability_lock:
        cached = _capability_cache.get(name)
        if cached and now - cached["at"] < CAPABILITY_TTL_SECONDS:
            return dict(cached["value"])
    value = probe()
    with _capability_lock:
        _capability_cache[name] = {"at": time.monotonic(), "value": value}
    return dict(value)


def _unavailable(reason: str) -> dict:
    return {"available": False, "cuda": False, "reason": reason}


def lyrics_capability() -> dict:
    """Verify source snapshots; frozen builds retain external-helper detection."""
    command = lyrics_command()
    if command is None:
        return _unavailable("The external Lyrics runtime is not installed")
    if getattr(sys, "frozen", False):
        return {"available": True, "cuda": False, "reason": ""}
    try:
        from chordflask_lyrics.freshness import check_runtime

        # Do not cache freshness: same-version edits and runtime repairs must
        # be visible immediately, including just before subprocess execution.
        return check_runtime(command.parent.parent, Path(__file__).resolve().parents[1])
    except ImportError:
        return {**_unavailable("Lyrics runtime needs update. Rerun scripts/setup-lyrics.sh (make setup-lyrics)."),
                "needs_update": True}


def btc_capability() -> dict:
    """Require the bundled lightweight connector and complete external runtime."""
    def probe():
        try:
            from chordflask_btc import capability
        except ImportError:
            return _unavailable("BTC integration is not installed")
        try:
            runtime = capability()
        except (OSError, ValueError) as error:
            return _unavailable(str(error))
        if not runtime["complete"]:
            return _unavailable("The optional BTC runtime is incomplete")
        return {"available": True, "cuda": False, "reason": ""}

    return _cached_capability("btc", probe)


def clear_capability_cache() -> None:
    """Clear cached capability results for focused tests."""
    with _capability_lock:
        _capability_cache.clear()


def _run_helper(action: str, command: list[str], *, env=None) -> int:
    logging.info("Starting %s preparation for %s", action, command[-1])
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            shell=False,
            env=env,
        )
    except OSError:
        logging.exception("Could not start %s preparation", action)
        return 127
    output = " ".join((result.stderr or result.stdout).split())[:1000]
    if result.returncode:
        logging.error(
            "%s preparation failed with exit code %s: %s",
            action,
            result.returncode,
            output or "no helper output",
        )
    else:
        logging.info("%s preparation completed", action)
    return result.returncode


def run_lyrics_preparation(media_path: Path) -> int:
    command = lyrics_command()
    if command is None:
        raise RuntimeError("The external Lyrics runtime is not installed")
    capability = lyrics_capability()
    if not capability["available"]:
        raise RuntimeError(capability["reason"])
    if not getattr(sys, "frozen", False):
        # Use the same isolated interpreter whose installed code was verified;
        # inherited PYTHONPATH must not substitute another package snapshot.
        return _run_helper(
            "Lyrics", [str(command.parent / "python"), "-I", str(command), str(media_path)]
        )
    return _run_helper("Lyrics", [str(command), str(media_path)])


def run_btc_preparation(media_path: Path) -> int:
    from chordflask_btc.predictor import predict_btc_media

    predict_btc_media(Path(media_path))
    return 0



def score_command() -> Path | None:
    runtime = Path(os.environ.get("CHORDFLASK_SCORE_VENV", "~/.venvs/chordflask-score")).expanduser()
    helper = runtime / "bin/chordflask-score"
    return helper if helper.is_file() and os.access(helper, os.X_OK) else None


def score_capability() -> dict:
    def probe():
        helper = score_command()
        if helper is None:
            return _unavailable("The external Score runtime is not installed. Run make setup-score")
        from chordflask_demucs.runtime import clean_environment

        try:
            result = subprocess.run(
                [str(helper.parent / "python"), "-I", "-m", "chordflask_score.worker", "--check"],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, check=False,
                env=clean_environment(),
            )
            if result.returncode:
                return _unavailable("Score runtime is incomplete. Run make setup-score")
        except (OSError, subprocess.TimeoutExpired):
            return _unavailable("Score runtime check failed. Run make setup-score")
        return {"available": True, "cuda": False, "reason": ""}
    return _cached_capability("score", probe)


def run_score_preparation(media_path: Path) -> int:
    helper = score_command()
    if helper is None:
        raise RuntimeError("The external Score runtime is not installed. Run make setup-score")
    from chordflask_demucs.runtime import clean_environment

    return _run_helper("Score", [str(helper.parent / "python"), "-I", str(helper), "--replace", str(media_path)],
                       env=clean_environment())


__all__ = [
    "CAPABILITY_TTL_SECONDS",
    "DEFAULT_LYRICS_VENV",
    "btc_capability",
    "clear_capability_cache",
    "lyrics_capability",
    "lyrics_command",
    "score_capability",
    "score_command",
    "run_score_preparation",
    "run_btc_preparation",
    "run_lyrics_preparation",
]
