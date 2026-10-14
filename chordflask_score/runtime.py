"""Lightweight isolated-runtime boundary; no optional library imports."""

import os
from pathlib import Path
import subprocess

from chordflask_demucs.runtime import clean_environment

from .timing import digest

CODE_FILES = ("timing.py", "notation.py", "svg.py", "worker.py", "storage.py", "cli.py", "runtime.py")


def code_identity():
    import hashlib
    root = Path(__file__).parent
    return digest({name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in CODE_FILES})


def check_python(version):
    if tuple(version[:2]) != (3, 12):
        raise ValueError("Score runtime requires Python 3.12 (verified Transkun/PyTorch combination)")


def runtime_python():
    return Path(os.environ.get("CHORDFLASK_SCORE_VENV", "~/.venvs/chordflask-score")).expanduser() / "bin/python"


def execute(arguments, *, timeout=3600):
    python = runtime_python()
    if not python.is_file() or not os.access(python, os.X_OK):
        raise RuntimeError(f"Score runtime missing: {python}. Run make setup-score")
    try:
        result = subprocess.run([str(python), "-I", "-m", "chordflask_score.worker", *arguments],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                timeout=timeout, env=clean_environment(), check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"Score runtime failed: {error}") from error
    if result.returncode:
        raise RuntimeError(f"Score runtime failed: {(result.stderr or result.stdout)[-8000:]}")
    return result.stdout


def require_runtime():
    import json
    report = json.loads(execute(["--check"], timeout=60))
    if report["code"] != code_identity():
        raise RuntimeError("Score runtime code differs from the caller. Rerun make setup-score")
    return report
