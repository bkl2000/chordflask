#!/usr/bin/env python3
"""ChordFlask analysis-storage inspection and cleanup for one media directory.

Usage:
    python scripts/chordflask_storage.py report DIR
    python scripts/chordflask_storage.py cleanup DIR --orphan-temp
    python scripts/chordflask_storage.py cleanup DIR --corrupt-backups --older-than-days N

Operates only on ``DIR/.chordflask`` (never the legacy ``.chordy`` directory and
never the global ``~/.chordflask`` state). ``report`` is always read-only.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FLASK_DIR = REPO_ROOT / "flask"
for _path in (REPO_ROOT, FLASK_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from analysis_storage import (  # noqa: E402
    cleanup_cached_audio,
    cleanup_corrupt_backups,
    cleanup_orphan_temp,
    format_cleanup_result,
    format_storage_report,
    inspect_storage,
)


def _scope(args):
    return str(Path(args.directory).expanduser() / ".chordflask")


def cmd_report(args):
    try:
        inspection = inspect_storage(args.directory)
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(format_storage_report(inspection))
    return 0


def _cleanup_args_error(args):
    if not args.orphan_temp and not args.corrupt_backups and not args.cached_audio:
        return (
            "specify at least one cleanup category: --orphan-temp, "
            "--cached-audio, or --corrupt-backups"
        )
    if args.corrupt_backups:
        if args.older_than_days is None or args.older_than_days <= 0:
            return "--corrupt-backups requires --older-than-days N (a positive integer)"
    elif args.older_than_days is not None:
        return "--older-than-days requires --corrupt-backups"
    return None


def cmd_cleanup(args):
    error = _cleanup_args_error(args)
    if error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    scope = _scope(args)
    exit_code = 0

    if args.orphan_temp:
        try:
            result = cleanup_orphan_temp(args.directory)
        except ValueError as value_error:
            print(f"ERROR: {value_error}", file=sys.stderr)
            return 2
        print(format_cleanup_result(result, scope))
        print()
        if result.refused or result.failures:
            exit_code = 1

    if args.cached_audio:
        try:
            result = cleanup_cached_audio(args.directory)
        except ValueError as value_error:
            print(f"ERROR: {value_error}", file=sys.stderr)
            return 2
        print(format_cleanup_result(result, scope))
        print()
        if result.refused or result.failures:
            exit_code = 1

    if args.corrupt_backups:
        try:
            result = cleanup_corrupt_backups(args.directory, args.older_than_days)
        except ValueError as value_error:
            print(f"ERROR: {value_error}", file=sys.stderr)
            return 2
        print(format_cleanup_result(result, scope))
        if result.failures:
            exit_code = 1

    return exit_code


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="ChordFlask analysis-storage report and cleanup for one media directory."
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    report_parser = subparsers.add_parser(
        "report", help="Inspect one media directory's .chordflask storage (read-only)."
    )
    report_parser.add_argument(
        "directory", metavar="DIR",
        help="Media directory whose .chordflask storage to report",
    )
    report_parser.set_defaults(func=cmd_report)

    cleanup_parser = subparsers.add_parser(
        "cleanup", help="Delete explicit storage-leftover categories in one media directory."
    )
    cleanup_parser.add_argument(
        "directory", metavar="DIR",
        help="Media directory whose .chordflask storage to clean",
    )
    cleanup_parser.add_argument(
        "--orphan-temp", action="store_true",
        help="Delete orphaned analysis/conversion temporary artifacts",
    )
    cleanup_parser.add_argument(
        "--cached-audio", action="store_true",
        help="Delete cached audio (.mp3) regenerable from a video source",
    )
    cleanup_parser.add_argument(
        "--corrupt-backups", action="store_true",
        help="Delete old corrupt-analysis backup files",
    )
    cleanup_parser.add_argument(
        "--older-than-days", type=int, metavar="N",
        help="Retention age in days for --corrupt-backups",
    )
    cleanup_parser.set_defaults(func=cmd_cleanup)

    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
