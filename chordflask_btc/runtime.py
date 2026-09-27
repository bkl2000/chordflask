"""Locate and validate the isolated BTC runtime without importing it.

BTC runs as a separate subprocess (``btc-predict-raw``) in its own venv
(``~/.venvs/chordflask-btc``). This module only resolves paths and checks that
the runtime is present, so the analyze command can fail early with an
actionable message instead of importing torch or BTC model code.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_VENV = Path.home() / ".venvs" / "chordflask-btc"
CHECKPOINT_NAME = "btc_model_large_voca.pt"
PREDICTOR_FILES = (
    "btc_model.py",
    "features.py",
    "predict_raw.py",
    "transformer_modules.py",
    "vocabulary.py",
)


class BtcRuntimeError(RuntimeError):
    """The BTC runtime is not installed or is incomplete."""


def btc_venv_dir() -> Path:
    override = os.environ.get("CHORDFLASK_BTC_VENV")
    return Path(override) if override else DEFAULT_VENV


def btc_dir() -> Path:
    override = os.environ.get("CHORDFLASK_BTC_DIR")
    return Path(override) if override else btc_venv_dir() / "share" / "chordflask-btc"


def checkpoint_path() -> Path:
    return btc_dir() / CHECKPOINT_NAME


def raw_script_path() -> Path:
    return btc_dir() / "predict_raw.py"


def wrapper_path() -> Path:
    return btc_venv_dir() / "bin" / "btc-predict-raw"


def venv_python() -> Path:
    return btc_venv_dir() / "bin" / "python"


def detect_btc_runtime() -> dict:
    """Return the runtime status; ``complete`` is False when anything is missing."""
    missing: list[str] = []
    if not venv_python().is_file() or not os.access(venv_python(), os.X_OK):
        missing.append(f"venv python ({venv_python()})")
    for filename in PREDICTOR_FILES:
        path = btc_dir() / filename
        if not path.is_file():
            missing.append(f"predictor source ({path})")
    if not wrapper_path().is_file() or not os.access(wrapper_path(), os.X_OK):
        missing.append(f"executable wrapper ({wrapper_path()})")
    checkpoint = checkpoint_path()
    if not checkpoint.is_file():
        missing.append(f"checkpoint ({checkpoint})")
    return {
        "venv": str(btc_venv_dir()),
        "checkpoint": str(checkpoint),
        "wrapper": str(wrapper_path()),
        "complete": not missing,
        "missing": missing,
    }


def require_btc_runtime() -> dict:
    """Return the runtime status or raise :class:`BtcRuntimeError` when missing."""
    state = detect_btc_runtime()
    if not state["complete"]:
        detail = "\n".join(f"  missing: {item}" for item in state["missing"])
        raise BtcRuntimeError(
            "BTC runtime not installed.\n"
            "Check: make btc-check\n"
            "Install: make setup-btc BTC_ACKNOWLEDGE_WEIGHTS=1\n"
            + detail
        )
    return state
