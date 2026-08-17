"""``chordflask-analyze`` — analyze a media file or directory with ChordFlask.

Chordino is the built-in default analyzer and runs in-process through the
canonical :class:`AnalysisWorker` / :class:`ChordAnalyzer` path. When the
optional BTC backend is installed, it is reached only through a subprocess
call to its private backend; this module never imports torch, BTC code, or the
private training package.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make the sibling ``flask/`` modules (analysis_worker, chordanalyzer, …)
# importable when this script is run directly. The launcher only adds the
# repository root to PYTHONPATH (for ``chordflask_base``).
_FLASK_DIR = Path(__file__).resolve().parent.parent
if str(_FLASK_DIR) not in sys.path:
    sys.path.insert(0, str(_FLASK_DIR))

_MEDIA_SUFFIXES = {".mp3", ".mp4", ".webm"}


def _btc_backend_available() -> bool:
    from chordflask_btc.runtime import wrapper_path

    script = wrapper_path()
    return script.is_file() and os.access(script, os.X_OK)


def _analyzer_choices() -> tuple[str, ...]:
    return ("chordino", "btc") if _btc_backend_available() else ("chordino",)


def _epilog() -> str:
    lines = [
        "Examples:",
        "  chordflask-analyze song.mp4",
        "  chordflask-analyze /music/videos",
    ]
    if _btc_backend_available():
        lines += [
            "  chordflask-analyze --analyzer btc song.mp4",
            "  chordflask-analyze --analyzer btc /music/videos",
            "  chordflask-analyze --analyzer btc --replace song.mp4",
            "  chordflask-analyze --analyzer btc --dry-run /music/videos",
        ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    description = (
        "Analyze a media file or directory with ChordFlask.\n\n"
        "Chordino is the default built-in analyzer."
    )
    if _btc_backend_available():
        description += "\nBTC is an optional analyzer that adds a separate chord track."
    parser = argparse.ArgumentParser(
        prog="chordflask-analyze",
        description=description,
        epilog=_epilog(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--analyzer",
        choices=_analyzer_choices(),
        default="chordino",
        help="Analyzer to use (default: chordino, the built-in analyzer)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace the selected analyzer's track(s) instead of skipping",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be analyzed without changing anything",
    )
    parser.add_argument(
        "target",
        type=Path,
        help="MP3/MP4/WebM file or a directory of media files",
    )
    return parser


def _run_btc_backend(target: Path, *, replace: bool, dry_run: bool) -> int:
    from chordflask_btc.analyze import analyze_btc

    return analyze_btc(target, replace=replace, dry_run=dry_run)


def _resolve_media_files(target: Path) -> list[Path] | None:
    """Return the media files to process, or None after printing an error."""
    if target.is_dir():
        from batch_core import find_media_files

        try:
            return find_media_files(target)
        except FileNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return None
    if target.is_file():
        if target.suffix.lower() not in _MEDIA_SUFFIXES:
            print(
                f"Error: not a supported media file (MP3/MP4/WebM): {target}",
                file=sys.stderr,
            )
            return None
        return [target]
    print(f"Error: not a file or directory: {target}", file=sys.stderr)
    return None


def _chordino_status(media: Path) -> str:
    """Classify one media file for the Chordino analyzer.

    A valid analysis JSON is not enough to call Chordino "current": in the
    Schema-v3 multi-analyzer model, a file may carry only a BTC track. Chordino
    is current only when both the built-in Chordino chord track and the QM
    rhythm track are present.
    """
    from chordflask_base import (
        DEFAULT_CHORD_TRACK,
        DEFAULT_RHYTHM_TRACK,
        ChordTrackRepository,
        analysis_json_path,
    )

    json_path = analysis_json_path(media)
    if not json_path.exists():
        return "missing"
    try:
        repository = ChordTrackRepository().load(json_path)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        return "invalid"
    has_chordino = DEFAULT_CHORD_TRACK in repository.available_chord_track_ids
    has_rhythm = DEFAULT_RHYTHM_TRACK in repository.available_rhythm_track_ids
    return "current" if (has_chordino and has_rhythm) else "todo"


def _run_chordino(target: Path, *, replace: bool, dry_run: bool) -> int:
    from analysis_worker import AnalysisWorker

    media_files = _resolve_media_files(target)
    if media_files is None:
        return 2

    worker = None
    counts = {"ok": 0, "skipped": 0, "failed": 0}
    total = len(media_files)
    for index, media in enumerate(media_files, 1):
        print(f"[{index}/{total}] {media.name}")
        status = _chordino_status(media)
        if dry_run:
            if status == "current":
                label = "REANALYZE" if replace else "CURRENT"
            elif status == "invalid":
                label = "INVALID"
            else:
                label = "TODO"
            print(f"       {label}")
            continue
        if status == "current" and not replace:
            print("       SKIP: analysis already exists")
            counts["skipped"] += 1
            continue
        if worker is None:
            from chordanalyzer import ChordAnalyzer

            worker = AnalysisWorker(analyzer_cls=ChordAnalyzer)
        try:
            worker._analyze(media, force=status in ("current", "todo"))
        except Exception as exc:
            print(f"       ERROR: {exc}", file=sys.stderr)
            counts["failed"] += 1
            continue
        counts["ok"] += 1
        print("       OK")

    print("")
    print("Chordino dry-run complete" if dry_run else "Chordino analysis complete")
    print("")
    print(f"files:      {total}")
    print(f"analyzed:   {counts['ok']}")
    print(f"skipped:    {counts['skipped']}")
    print(f"failed:     {counts['failed']}")
    return 1 if counts["failed"] else 0


def main(argv=None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        build_parser().print_help()
        raise SystemExit(0)
    args = build_parser().parse_args(argv)
    if args.analyzer == "btc":
        code = _run_btc_backend(args.target, replace=args.replace, dry_run=args.dry_run)
    else:
        code = _run_chordino(args.target, replace=args.replace, dry_run=args.dry_run)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
