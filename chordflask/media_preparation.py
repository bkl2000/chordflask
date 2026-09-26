"""Source-only Lyrics and BTC preparation for the currently loaded song.

This module contains only lightweight integration.  Lyrics and BTC work is
started through the installed source environment's console commands; the BTC
command retains its existing isolated predictor subprocess boundary.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

CAPABILITY_TTL_SECONDS = 60

_capability_lock = threading.Lock()
_capability_cache: dict[str, dict] = {}


def source_command(name: str) -> Path | None:
    """Resolve a source-installation helper, never one from a frozen bundle."""
    if getattr(sys, "frozen", False):
        return None
    sibling = Path(sys.executable).parent / name
    if sibling.is_file() and os.access(sibling, os.X_OK):
        return sibling
    found = shutil.which(name)
    if found and os.access(found, os.X_OK):
        return Path(found)
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
    """Require the installed Lyrics console helper in a source environment."""
    def probe():
        if source_command("chordflask-genlyrics") is None:
            return _unavailable("The Lyrics generator is not installed")
        return {"available": True, "cuda": False, "reason": ""}

    return _cached_capability("lyrics", probe)


def btc_capability() -> dict:
    """Require source BTC integration, its helper, and the complete runtime."""
    def probe():
        if getattr(sys, "frozen", False):
            return _unavailable("BTC generation is not included in the standalone")
        if source_command("chordflask-analyze") is None:
            return _unavailable("The analysis helper is not installed")
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


def _run_helper(action: str, command: list[str]) -> int:
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
    command = source_command("chordflask-genlyrics")
    if command is None:
        raise RuntimeError("The Lyrics generator is not installed")
    return _run_helper("Lyrics", [str(command), str(media_path)])


def run_btc_preparation(media_path: Path) -> int:
    command = source_command("chordflask-analyze")
    if command is None:
        raise RuntimeError("The analysis helper is not installed")
    return _run_helper(
        "BTC", [str(command), "--analyzer", "btc", str(media_path)]
    )


__all__ = [
    "CAPABILITY_TTL_SECONDS",
    "btc_capability",
    "clear_capability_cache",
    "lyrics_capability",
    "run_btc_preparation",
    "run_lyrics_preparation",
    "source_command",
]
