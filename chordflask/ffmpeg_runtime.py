"""Resolve ChordFlask's external FFmpeg runtime at explicit I/O boundaries."""

import os
import shutil
import sys
from pathlib import Path


INSTALL_HINT = "On Ubuntu/Debian install it with: sudo apt install ffmpeg"


def require_system_ffmpeg():
    """Configure ImageIO/MoviePy and return the external FFmpeg command.

    ChordFlask never downloads or selects an executable from the imageio-ffmpeg
    wheel. Callers receive a runtime error before media work starts when the
    target system has no ``ffmpeg`` on ``PATH``.
    """
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise RuntimeError(f"ffmpeg is required but was not found on PATH. {INSTALL_HINT}")
    if getattr(sys, "frozen", False) and sys.platform.startswith("linux"):
        # MoviePy has no per-call subprocess environment parameter. Its command
        # must restore the host linker environment without changing this process.
        os.environ["CHORDFLASK_SYSTEM_FFMPEG"] = ffmpeg_path
        ffmpeg_path = str(Path(__file__).with_name("ffmpeg-system.sh"))
    os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_path
    os.environ["FFMPEG_BINARY"] = ffmpeg_path
    return ffmpeg_path
