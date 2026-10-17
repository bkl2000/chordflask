"""File-only installation hints for startup; never populate GUI probe caches."""

import os
import sys
import time
from pathlib import Path

from . import media_preparation, stem_preparation


def _executable(path):
    return path is not None and path.is_file() and os.access(path, os.X_OK)


def _package_files(runtime, *files):
    # Inspect only the venv's conventional package roots, never import packages
    # or assume that its Python version matches the player's interpreter.
    return any(all((site / name).is_file() for name in files)
               for site in (runtime / "lib").glob("python*/site-packages"))


def _cached(name):
    module = stem_preparation if name == "demucs" else media_preparation
    with module._capability_lock:
        cached = (module._capability_cache if name == "demucs"
                  else module._capability_cache.get(name))
        if (cached and cached["value"] is not None
                and time.monotonic() - cached["at"] < module.CAPABILITY_TTL_SECONDS):
            return dict(cached["value"])
    return None


def _lyrics_installed():
    return _executable(media_preparation.lyrics_command())


def _qwen_installed():
    # Lyrics is deliberately absent from frozen players; inspect its external
    # CLI installation instead of importing the generator or inference worker.
    helper = media_preparation.lyrics_command()
    if not _executable(helper):
        return False
    runtime = Path(os.environ.get("CHORDFLASK_QWEN3_VENV",
                                  Path.home() / ".venvs/chordflask-qwen3-asr"))
    return (
        _executable(helper.parent / "python")
        and (_package_files(helper.parent.parent, "chordflask_lyrics/qwen3_worker.py")
             or (not getattr(sys, "frozen", False)
                 and helper.parent == Path(sys.executable).parent
                 and (Path(__file__).parent.parent / "chordflask_lyrics/qwen3_worker.py").is_file()))
        and _executable(runtime / "bin/python")
        and _package_files(runtime, "qwen_asr/__init__.py", "torch/__init__.py")
        and all((runtime / "models" / name / "config.json").is_file()
                and any(path.is_file() for path in
                        (runtime / "models" / name).glob("*.safetensors"))
                for name in ("Qwen3-ASR-1.7B", "Qwen3-ForcedAligner-0.6B"))
    )


def _btc_installed():
    from chordflask_btc import capability as btc_installation_status

    return btc_installation_status()["complete"]


def _demucs_installed():
    from chordflask_demucs.runtime import venv_python

    python = venv_python()
    return _executable(python) and _package_files(
        python.parent.parent, "demucs/separate.py", "torch/__init__.py"
    )


def _score_installed():
    helper = media_preparation.score_command()
    return _executable(helper) and _executable(helper.parent / "python")


def runtime_status(name):
    """Distinguish installation evidence from a fresh successful probe."""
    details = {"qwen": "CLI only; experimental", "score": "Transkun; experimental"}
    probes = {"lyrics": _lyrics_installed, "qwen": _qwen_installed,
              "btc": _btc_installed, "demucs": _demucs_installed,
              "score": _score_installed}
    detail = details.get(name, "")
    cached = _cached(name)
    if cached and cached["available"] is True:
        if name == "demucs":
            detail = "CUDA" if cached.get("cuda") else "CPU"
        return "available" + (f" ({detail})" if detail else "")
    try:
        installed = probes[name]()
    except (OSError, ValueError, ImportError):
        detail = "; ".join(filter(None, (detail, "installation files could not be inspected")))
        return f"not checked ({detail})"
    status = "installed" if installed else "not installed"
    if installed:
        detail = "; ".join(filter(None, (detail, "not verified")))
    if cached and cached["available"] is False:
        reason = " ".join(cached.get("reason", "runtime unavailable").split())
        detail = "; ".join(filter(None, (detail, f"last check failed: {reason[:90]}")))
    return status + (f" ({detail})" if detail else "")
