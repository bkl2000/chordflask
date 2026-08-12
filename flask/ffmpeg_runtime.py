"""Resolve ChordFlask's external FFmpeg runtime at explicit I/O boundaries."""

import os
import shutil


INSTALL_HINT = "On Ubuntu/Debian install it with: sudo apt install ffmpeg"


def require_system_ffmpeg():
    """Return the system FFmpeg path and configure ImageIO to use only it.

    ChordFlask never downloads or selects an executable from the imageio-ffmpeg
    wheel. Callers receive a runtime error before media work starts when the
    target system has no ``ffmpeg`` on ``PATH``.
    """
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise RuntimeError(f"ffmpeg is required but was not found on PATH. {INSTALL_HINT}")
    os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_path
    return ffmpeg_path
