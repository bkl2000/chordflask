"""Small installation/state checks for ``chordflask-maintain doctor``.

Uses only the Python standard library (plus a subprocess-free ``shutil.which``
lookup): Python/venv, system FFmpeg, Vamp plugin presence, and the global
ChordFlask queue directory. It deliberately imports nothing from ``flask``,
``training``, torch, librosa, or music21.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_REQUIRED_PLUGINS = ("nnls-chroma.so", "qm-vamp-plugins.so")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _vamp_search_dirs() -> list[Path]:
    dirs: list[Path] = []
    vamp_path = os.environ.get("VAMP_PATH")
    if vamp_path:
        dirs.extend(Path(p).expanduser() for p in vamp_path.split(os.pathsep) if p)
    dirs.append(Path.home() / ".vamp")
    dirs.append(_repo_root() / "vendor" / "vamp" / "linux-x86_64")
    return dirs


def _vamp_status() -> tuple[list[str], list[str]]:
    found: set[str] = set()
    for directory in _vamp_search_dirs():
        for name in _REQUIRED_PLUGINS:
            if (directory / name).is_file():
                found.add(name)
    found_list = sorted(found)
    missing = [name for name in _REQUIRED_PLUGINS if name not in found]
    return found_list, missing


def run_doctor() -> dict:
    """Return a small structured set of installation checks."""
    python_ok = sys.executable and Path(sys.executable).is_file()
    ffmpeg = shutil.which("ffmpeg")
    plugins_found, plugins_missing = _vamp_status()

    from chordflask_maintain.storage import queue_dir

    queue = queue_dir()
    queue_writable = False
    if queue.exists():
        queue_writable = os.access(queue, os.W_OK)
    else:
        # Report as writable if the parent exists and is writable (the queue
        # directory is created lazily by the app).
        queue_writable = os.access(queue.parent, os.W_OK)

    return {
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "python_interpreter": str(sys.executable),
        "python_ok": python_ok,
        "ffmpeg": ffmpeg,
        "vamp_found": plugins_found,
        "vamp_missing": plugins_missing,
        "queue_dir": str(queue),
        "queue_writable": queue_writable,
    }


def format_doctor_report(report: dict) -> str:
    lines = ["ChordFlask doctor", ""]

    python_state = "OK" if report["python_ok"] else "MISSING"
    lines.append(f"  Python:      {report['python_version']} ({report['python_interpreter']}) [{python_state}]")

    if report["ffmpeg"]:
        lines.append(f"  ffmpeg:      {report['ffmpeg']}")
    else:
        lines.append("  ffmpeg:      MISSING (sudo apt install ffmpeg)")

    if report["vamp_missing"]:
        lines.append(f"  Vamp plugins: MISSING {', '.join(report['vamp_missing'])}")
    else:
        lines.append(f"  Vamp plugins: {', '.join(report['vamp_found'])}")

    queue_state = "writable" if report["queue_writable"] else "not writable"
    lines.append(f"  Queue dir:   {report['queue_dir']} ({queue_state})")

    return "\n".join(lines)


def doctor_exit_code(report: dict) -> int:
    ok = (
        report["python_ok"]
        and bool(report["ffmpeg"])
        and not report["vamp_missing"]
        and report["queue_writable"]
    )
    return 0 if ok else 1
