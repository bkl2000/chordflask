"""Resolve and inspect the isolated Demucs runtime.

This module deliberately does not import Demucs or Torch.  The optional
runtime is queried and executed only through its virtual-environment Python
interpreter.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .constants import DEFAULT_CACHE, DEFAULT_VENV


class DemucsRuntimeError(RuntimeError):
    """The optional Demucs runtime is missing or unusable."""


@dataclass(frozen=True)
class RuntimeInfo:
    venv: Path
    python: Path
    demucs_version: str
    torch_version: str
    cuda_available: bool = False


def venv_dir() -> Path:
    override = os.environ.get("CHORDFLASK_DEMUCS_VENV")
    return Path(override).expanduser() if override else DEFAULT_VENV


def cache_dir() -> Path:
    override = os.environ.get("CHORDFLASK_DEMUCS_CACHE")
    return Path(override).expanduser() if override else DEFAULT_CACHE


def venv_python() -> Path:
    return venv_dir() / "bin" / "python"


def _probe_script() -> str:
    return (
        "import json, sys; "
        "import demucs, torch; "
        "print(json.dumps({'python': sys.version.split()[0], "
        "'demucs': getattr(demucs, '__version__', 'unknown'), "
        "'torch': torch.__version__, 'cuda': bool(torch.cuda.is_available())}))"
    )


def _probe_runtime(timeout: int = 30) -> RuntimeInfo:
    python = venv_python()
    if not python.is_file() or not os.access(python, os.X_OK):
        raise DemucsRuntimeError(f"Demucs runtime not installed: {python}\nRun: make setup-demucs")
    try:
        result = subprocess.run(
            [str(python), "-c", _probe_script()],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except OSError as error:
        raise DemucsRuntimeError(f"Could not execute Demucs runtime: {error}") from error
    except subprocess.TimeoutExpired as error:
        raise DemucsRuntimeError("Demucs runtime probe timed out") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise DemucsRuntimeError(
            "Demucs runtime is incomplete. Run: make setup-demucs\n"
            + (detail or "Demucs/Torch import failed")
        )
    try:
        report = json.loads(result.stdout)
        return RuntimeInfo(
            venv=venv_dir(),
            python=python,
            demucs_version=str(report["demucs"]),
            torch_version=str(report["torch"]),
            cuda_available=bool(report.get("cuda", False)),
        )
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise DemucsRuntimeError("Demucs runtime returned an invalid version report") from error


def require_runtime() -> RuntimeInfo:
    """Return runtime facts or raise an actionable configuration error."""
    cache_dir().mkdir(parents=True, exist_ok=True)
    return _probe_runtime()


def environment() -> dict[str, str]:
    """Return an isolated subprocess environment with an external model cache."""
    model_cache = cache_dir()
    model_cache.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["TORCH_HOME"] = str(model_cache)
    env["XDG_CACHE_HOME"] = str(model_cache)
    return env


def validate_device(device: str) -> str:
    if device not in {"auto", "cpu", "cuda"}:
        raise ValueError("device must be one of: auto, cpu, cuda")
    return device


def resolve_device(device: str, runtime: RuntimeInfo) -> str:
    """Resolve ChordFlask's convenient ``auto`` value for Demucs/PyTorch."""
    validate_device(device)
    if device == "auto":
        return "cuda" if runtime.cuda_available else "cpu"
    return device


def describe(info: RuntimeInfo) -> dict[str, str]:
    return {
        "venv": str(info.venv),
        "python": str(info.python),
        "demucs_version": info.demucs_version,
        "torch_version": info.torch_version,
    }


__all__ = [
    "DemucsRuntimeError",
    "RuntimeInfo",
    "cache_dir",
    "describe",
    "environment",
    "require_runtime",
    "resolve_device",
    "validate_device",
    "venv_dir",
    "venv_python",
]
