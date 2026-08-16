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


def _run_chordino(target: Path, *, replace: bool, dry_run: bool) -> int:
    from analysis_worker import AnalysisWorker
    from chordflask_base import analysis_json_path

    media_files = _resolve_media_files(target)
    if media_files is None:
        return 2

    worker = None
    counts = {"ok": 0, "skipped": 0, "failed": 0}
    total = len(media_files)
    for index, media in enumerate(media_files, 1):
        print(f"[{index}/{total}] {media.name}")
        valid = AnalysisWorker._json_is_valid(analysis_json_path(media))
        if dry_run:
            if valid and replace:
                label = "REANALYZE"
            elif valid:
                label = "CURRENT"
            else:
                label = "TODO"
            print(f"       {label}")
            continue
        if valid and not replace:
            print("       SKIP: analysis already exists")
            counts["skipped"] += 1
            continue
        if worker is None:
            from chordanalyzer import ChordAnalyzer

            worker = AnalysisWorker(analyzer_cls=ChordAnalyzer)
        try:
            worker._analyze(media, force=replace and valid)
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
