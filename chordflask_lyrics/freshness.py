"""Source/snapshot identity for the isolated Lyrics runtime (stdlib only)."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile

MARKER_PATH = Path("share/chordflask-lyrics/source-identity.json")
FORMAT_VERSION = 1
# Pure core helpers imported by Lyrics; package code below is discovered once
# here for both source and installed snapshots. No models or presentation assets.
CORE_FILES = (
    "__init__.py", "chordflask_config.py", "filerepr.py", "media_library.py",
    "playbackview.py", "metric_chords.py", "chordutils.py", "chord_markdown.py",
    "chord_export_sheet.py", "chordpro_song.py",
)
UPDATE_GUIDANCE = "Rerun scripts/setup-lyrics.sh (make setup-lyrics) from the current source checkout."


def fingerprint(root: Path) -> str:
    """Hash ordered relative paths and bytes, including additions/deletions."""
    root = Path(root)
    paths = [root / "chordflask" / name for name in CORE_FILES]
    for package in ("chordflask_lyrics", "chordflask_base"):
        package_dir = root / package
        if not (package_dir / "__init__.py").is_file():
            raise ValueError(f"Missing Lyrics fingerprint package: {package}")
        paths.extend(
            path for path in package_dir.rglob("*.py")
            if not any(part.startswith(".") or part in {"__pycache__", "tests"}
                       for part in path.relative_to(package_dir).parts)
        )
    digest = hashlib.sha256()
    digest.update(f"chordflask-lyrics-fingerprint-{FORMAT_VERSION}\0".encode())
    for path in sorted(paths):
        name = path.relative_to(root).as_posix().encode()
        content = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def installed_fingerprint() -> str:
    """Locate packages as the selected runtime interpreter would import them."""
    roots = []
    for package in ("chordflask", "chordflask_base", "chordflask_lyrics"):
        spec = importlib.util.find_spec(package)
        if spec is None or spec.origin is None:
            raise ValueError(f"Missing installed package: {package}")
        roots.append(Path(spec.origin).resolve().parent.parent)
    if len(set(roots)) != 1:
        raise ValueError("Lyrics packages resolve to different installation roots")
    return fingerprint(roots[0])


def read_identity(runtime: Path) -> str:
    data = json.loads((Path(runtime) / MARKER_PATH).read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or type(data.get("format")) is not int
            or data["format"] != FORMAT_VERSION):
        raise ValueError("Unsupported Lyrics identity marker")
    identity = data.get("sha256")
    if (not isinstance(identity, str) or len(identity) != 64
            or any(character not in "0123456789abcdef" for character in identity)):
        raise ValueError("Malformed Lyrics identity marker")
    return identity


def record_identity(runtime: Path, source: Path, expected: str) -> None:
    """Publish only after source and installed bytes match the pre-install hash."""
    if fingerprint(source) != expected or installed_fingerprint() != expected:
        raise ValueError("Lyrics source changed during setup or installed code does not match")
    destination = Path(runtime) / MARKER_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".source-identity-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"format": FORMAT_VERSION, "sha256": expected}, handle)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def check_runtime(runtime: Path, source: Path) -> dict:
    """Fail closed for old, changed or unverifiable source/runtime identities."""
    try:
        expected = fingerprint(source)
        if read_identity(runtime) != expected:
            raise ValueError("source fingerprint differs")
        result = subprocess.run(
            [str(Path(runtime) / "bin/python"), "-I", "-B", str(Path(__file__).resolve()),
             "fingerprint", "--installed"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        if result.returncode != 0 or result.stdout.strip() != expected:
            raise ValueError("installed code cannot be verified against source")
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        return {"available": False, "cuda": False,
                "reason": f"Lyrics runtime needs update. {UPDATE_GUIDANCE}",
                "needs_update": True}
    return {"available": True, "cuda": False, "reason": "", "needs_update": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("fingerprint", "record", "check"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--expected")
    parser.add_argument("--installed", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "fingerprint":
            print(installed_fingerprint() if args.installed else fingerprint(args.source))
        elif args.action == "record":
            record_identity(args.runtime, args.source, args.expected)
        else:
            result = check_runtime(args.runtime, args.source)
            print("Lyrics freshness: CURRENT" if result["available"] else result["reason"])
            return 0 if result["available"] else 1
    except (OSError, ValueError, TypeError) as error:
        parser.exit(1, f"Lyrics identity verification failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
