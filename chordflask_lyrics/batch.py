"""Deterministic directory discovery and root-scoped failed-item state."""

import json
import os
from pathlib import Path
import tempfile

from chordflask.chordflask_config import ANALYSIS_DIR_NAME, SUPPORTED_MEDIA_SUFFIXES
from chordflask.media_library import preferred_media_files

from .romanize import SUPPORTED_ENGINES

STATE_NAME = "failures.json"
STATE_DIRECTORY = "lyrics-batch"


def state_path(root):
    """Refuse redirected state storage, including symlinked analysis directories."""
    root = Path(root).resolve()
    directory = root / ANALYSIS_DIR_NAME / STATE_DIRECTORY
    path = directory / STATE_NAME
    if (directory.resolve() != directory or path.is_symlink()
            or (directory.exists() and not directory.is_dir())):
        raise ValueError("Lyrics failure state must stay inside the requested root")
    return path


def recursive_media(root):
    """One preferred format per stem/directory; exclude hidden/cache/symlink dirs."""
    root = Path(root).resolve()
    files = []
    def walk_error(error):
        raise error

    for directory, children, _ in os.walk(root, followlinks=False, onerror=walk_error):
        children[:] = sorted(name for name in children
                             if not name.startswith(".") and not (Path(directory) / name).is_symlink())
        for media in preferred_media_files(directory):
            if not media.is_symlink() and media.resolve().is_relative_to(root):
                files.append(media)
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def generation_options(args):
    return {
        "force": args.force, "lyrics": list(args.lyrics), "track": args.track,
        "romanize": args.romanize, "romanize_engine": args.romanize_engine,
    }


def load_failures(root):
    path = state_path(root)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or type(data.get("format")) is not int
            or data["format"] != 1 or data.get("root") != str(root)):
        raise ValueError("Invalid Lyrics failure state or root mismatch")
    options = data.get("options")
    if (not isinstance(options, dict) or set(options) != {
            "force", "lyrics", "track", "romanize", "romanize_engine"}
            or type(options["force"]) is not bool or type(options["romanize"]) is not bool
            or not isinstance(options["track"], str) or not options["track"].strip()
            or options["romanize_engine"] not in SUPPORTED_ENGINES
            or not isinstance(options["lyrics"], list) or not options["lyrics"]
            or any(source not in ("lrc", "embedded", "lrclib") for source in options["lyrics"])
            or len(set(options["lyrics"])) != len(options["lyrics"])):
        raise ValueError("Invalid saved Lyrics generation options")
    failures = data.get("failed")
    if not isinstance(failures, list):
        raise ValueError("Invalid Lyrics failed-item set")
    seen = set()
    for entry in failures:
        if not isinstance(entry, dict) or not isinstance(entry.get("reason"), str):
            raise ValueError("Invalid Lyrics failed item")
        filename = entry.get("path")
        if not isinstance(filename, str):
            raise ValueError("Invalid Lyrics failed path")
        media = Path(filename)
        if (not media.is_absolute() or not media.is_relative_to(root)
                or media.resolve() != media or media.suffix.lower() not in SUPPORTED_MEDIA_SUFFIXES
                or filename in seen):
            raise ValueError("Lyrics failed path is unsupported or outside the requested root")
        seen.add(filename)
    return data


def save_failures(root, options, failures):
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"format": 1, "root": str(root), "options": options, "failed": failures}
    descriptor, name = tempfile.mkstemp(prefix=".lyrics-failures-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(data, output, indent=2, ensure_ascii=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
