"""On-demand Demucs stem preparation for the player UI.

The normal application never imports Torch or the third-party Demucs runtime.
The lightweight, heavy-dependency-free ``chordflask_demucs`` producer package is
bundled with the application (including the standalone). This module lazily
imports that producer, reuses its existing runtime probe for capability
detection, and runs one file's preparation in a background thread. The heavy
Demucs/Torch separation still happens only in the external
``~/.venvs/chordflask-demucs`` interpreter through the producer's subprocess.

The GUI path uses the producer's ``auto`` device resolution: CUDA is used when
the external runtime reports it, otherwise CPU fallback applies exactly like
the CLI. The normal CLI ``auto``/CPU behavior is unchanged.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

CAPABILITY_TTL_SECONDS = 60

_capability_lock = threading.Lock()
_probe_lock = threading.Lock()
_capability_cache: dict = {"at": 0.0, "value": None}


def _probe_capability_uncached() -> dict:
    """Reuse the producer's own isolated-runtime probe."""
    try:
        from chordflask_demucs.runtime import DemucsRuntimeError, require_runtime
    except ImportError:
        return {
            "available": False,
            "cuda": False,
            "reason": "The optional Demucs producer is not installed",
        }
    try:
        info = require_runtime()
    except (DemucsRuntimeError, OSError, ValueError) as error:
        return {
            "available": False,
            "cuda": False,
            "reason": str(error) or "The optional Demucs runtime is unavailable",
        }
    return {
        "available": True,
        "cuda": bool(info.cuda_available),
        "reason": "",
    }


def probe_capability(*, force: bool = False) -> dict:
    """Return the cached runtime/CUDA capability report.

    Only one probe runs at a time; concurrent callers wait and then reuse the
    freshly cached result instead of launching a second runtime probe.
    """
    now = time.monotonic()
    with _capability_lock:
        cached = _capability_cache["value"]
        if not force and cached is not None and now - _capability_cache["at"] < CAPABILITY_TTL_SECONDS:
            return dict(cached)
    with _probe_lock:
        with _capability_lock:
            cached = _capability_cache["value"]
            if (
                not force
                and cached is not None
                and time.monotonic() - _capability_cache["at"] < CAPABILITY_TTL_SECONDS
            ):
                return dict(cached)
        value = _probe_capability_uncached()
        with _capability_lock:
            _capability_cache["value"] = value
            _capability_cache["at"] = time.monotonic()
        return dict(value)


def gui_capability() -> dict:
    """PREPARE needs a usable external runtime; CUDA is informational."""
    capability = probe_capability()
    return {
        "available": capability["available"],
        "cuda": capability["cuda"],
        "reason": capability["reason"],
    }


def run_local_preparation(media_path: Path) -> int:
    """Run the bundled lightweight producer for one file.

    The producer owns locking, validation, and atomic publication; it shells
    out to the external Demucs runtime for the actual separation. The ``auto``
    device lets that runtime resolve CUDA or CPU exactly like the CLI.
    """
    from chordflask_demucs.cli import run

    return run(Path(media_path), replace=True, dry_run=False, device="auto")


class StemPreparationManager:
    """Track at most one background Demucs preparation job per process."""

    def __init__(self, capability_probe=gui_capability, runner=run_local_preparation):
        self._capability_probe = capability_probe
        self._runner = runner
        self._lock = threading.Lock()
        self._job = None

    @staticmethod
    def media_key(media_path: Path) -> str:
        try:
            return str(Path(media_path).resolve())
        except (OSError, RuntimeError):
            return str(media_path)

    def capability(self) -> dict:
        return self._capability_probe()

    def start(self, media_path: Path) -> dict:
        capability = self.capability()
        if not capability["available"]:
            return {
                "status": "unavailable",
                "error": capability["reason"] or "Demucs runtime with CUDA is not available",
            }
        media_path = Path(media_path)
        key = self.media_key(media_path)
        with self._lock:
            job = self._job
            if job is not None and job["state"] == "running":
                if job["key"] == key:
                    return {"status": "already_running"}
                return {"status": "busy"}
            self._job = {
                "key": key,
                "media": media_path,
                "state": "running",
                "message": "",
                "cuda": capability["cuda"],
                "started_at": time.monotonic(),
            }
        thread = threading.Thread(
            target=self._run,
            args=(media_path,),
            daemon=True,
            name="stem-preparation",
        )
        thread.start()
        return {"status": "accepted"}

    def _run(self, media_path: Path) -> None:
        try:
            returncode = self._runner(Path(media_path))
            if returncode != 0:
                raise RuntimeError(f"Demucs preparation failed (exit code {returncode})")
        except Exception as error:  # noqa: BLE001 - background job boundary
            self._finish(media_path, "error", str(error))
        else:
            self._finish(media_path, "ready", "")

    def _finish(self, media_path: Path, state: str, message: str) -> None:
        key = self.media_key(media_path)
        with self._lock:
            if self._job is not None and self._job["key"] == key:
                self._job["state"] = state
                self._job["message"] = message

    def status(self, media_path: Path) -> dict:
        key = self.media_key(media_path)
        with self._lock:
            job = self._job
        if job is not None and job["key"] == key and job["state"] in {"running", "ready", "error"}:
            # Do not re-probe while a job is active; report the facts that were
            # validated when the job started.
            return {
                "state": job["state"],
                "available": True,
                "cuda": job["cuda"],
                "message": job["message"],
            }
        capability = self.capability()
        if not capability["available"]:
            return {
                "state": "unavailable",
                "available": False,
                "cuda": capability["cuda"],
                "message": capability["reason"],
            }
        return {
            "state": "idle",
            "available": True,
            "cuda": capability["cuda"],
            "message": "",
        }


__all__ = [
    "CAPABILITY_TTL_SECONDS",
    "StemPreparationManager",
    "gui_capability",
    "probe_capability",
    "run_local_preparation",
]
