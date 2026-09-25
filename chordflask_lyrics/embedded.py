"""Read usable embedded lyrics through ChordFlask's existing ffprobe toolchain."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess

from .lrclib import TimedLyricLine, parse_synced_lyrics


_LYRICS_TAGS = ("syncedlyrics", "lyrics", "unsyncedlyrics")


@dataclass(frozen=True)
class EmbeddedLyrics:
    """Lyrics extracted from media, including their source and timing form."""

    source: str
    text: str
    lines: tuple[TimedLyricLine, ...] = ()

    @property
    def synchronized(self) -> bool:
        return bool(self.lines)


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()
    if (
        not text
        or "\x00" in text
        or "\ufffd" in text
        or not any(character.isalnum() for character in text)
    ):
        return None
    return text


def _lyrics_from_tags(tags: object) -> EmbeddedLyrics | None:
    if not isinstance(tags, dict):
        return None
    folded = {str(key).casefold(): value for key, value in tags.items()}
    plain_candidate = None
    for tag_name in _LYRICS_TAGS:
        text = _clean_text(folded.get(tag_name))
        if text is None:
            continue
        lines = parse_synced_lyrics(text)
        candidate = EmbeddedLyrics(f"ffprobe:{tag_name}", text, lines)
        if candidate.synchronized:
            return candidate
        if plain_candidate is None:
            plain_candidate = candidate
    return plain_candidate


def get_embedded_lyrics(audio_path: Path) -> EmbeddedLyrics | None:
    """Return usable embedded lyrics, or ``None`` when probing cannot provide any."""
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format_tags",
        "-of",
        "json",
        os.fspath(audio_path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except (UnicodeError, json.JSONDecodeError):
        return None
    format_data = data.get("format", {}) if isinstance(data, dict) else {}
    tags = format_data.get("tags", {}) if isinstance(format_data, dict) else {}
    return _lyrics_from_tags(tags)
