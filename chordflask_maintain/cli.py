"""``chordflask-maintain`` CLI — maintenance for existing ChordFlask data."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _scope(directory: str) -> str:
    return str(Path(directory).expanduser() / ".chordflask")


def _cmd_storage_report(args) -> int:
    from chordflask_maintain.storage import format_storage_report, inspect_storage

    try:
        inspection = inspect_storage(args.directory)
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(format_storage_report(inspection))
    return 0


def _cleanup_args_error(args) -> str | None:
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


def _cmd_storage_cleanup(args) -> int:
    from chordflask_maintain.storage import (
        cleanup_cached_audio,
        cleanup_corrupt_backups,
        cleanup_orphan_temp,
        format_cleanup_result,
    )

    error = _cleanup_args_error(args)
    if error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    scope = _scope(args.directory)
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


def _cmd_migrate_schema(args) -> int:
    from chordflask_maintain.migrate import migrate_directory

    try:
        counts = migrate_directory(args.directory)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print("")
    print("Schema migration complete")
    print("")
    print(f"files:      {counts['files']}")
    print(f"migrated:   {counts['migrated']}")
    print(f"skipped:    {counts['skipped']}")
    print(f"failed:     {counts['failed']}")
    return 1 if counts["failed"] else 0


def _cmd_validate(args) -> int:
    from chordflask_maintain.validate import validate_directory, validate_file

    target = Path(args.target).expanduser()
    if target.is_file():
        kind, message = validate_file(target)
        if kind == "ignore":
            print(f"SKIP: not a ChordFlask analysis: {target}")
            return 0
        if kind == "valid":
            print(f"OK: {target}")
            return 0
        print(f"ERROR: {target}: {message}", file=sys.stderr)
        return 1

    try:
        counts = validate_directory(target)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print("")
    print(f"valid:      {counts['valid']}")
    print(f"invalid:    {counts['invalid']}")
    return 1 if counts["invalid"] else 0


def _cmd_doctor(args) -> int:
    from chordflask_maintain.doctor import doctor_exit_code, format_doctor_report, run_doctor

    report = run_doctor()
    print(format_doctor_report(report))
    return doctor_exit_code(report)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chordflask-maintain",
        description="Maintain existing ChordFlask data and installation.",
        epilog=(
            "Examples:\n"
            "  chordflask-maintain doctor\n"
            "  chordflask-maintain validate /music/videos\n"
            "  chordflask-maintain migrate-schema /music/videos\n"
            "  chordflask-maintain storage report /music/videos\n"
            "\n"
            'Run "chordflask-maintain COMMAND --help" for command-specific options.'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    storage = subparsers.add_parser(
        "storage", help="Inspect or clean one media directory's .chordflask storage"
    )
    storage_sub = storage.add_subparsers(dest="storage_command", required=True, metavar="SUBCOMMAND")

    report = storage_sub.add_parser(
        "report", help="Inspect one media directory's .chordflask storage (read-only)"
    )
    report.add_argument("directory", metavar="DIR", help="Media directory to report")
    report.set_defaults(func=_cmd_storage_report)

    cleanup = storage_sub.add_parser(
        "cleanup", help="Delete explicit storage-leftover categories in one media directory"
    )
    cleanup.add_argument("directory", metavar="DIR", help="Media directory to clean")
    cleanup.add_argument("--orphan-temp", action="store_true", help="Delete orphaned analysis/conversion temp artifacts")
    cleanup.add_argument("--cached-audio", action="store_true", help="Delete cached audio (.mp3) regenerable from a video source")
    cleanup.add_argument("--corrupt-backups", action="store_true", help="Delete old corrupt-analysis backup files")
    cleanup.add_argument("--older-than-days", type=int, metavar="N", help="Retention age in days for --corrupt-backups")
    cleanup.set_defaults(func=_cmd_storage_cleanup)

    migrate = subparsers.add_parser(
        "migrate-schema", help="Migrate legacy Schema 1/2 analysis files to Schema 3 (no reanalysis)"
    )
    migrate.add_argument("directory", metavar="DIR", help="Directory whose .chordflask/*.json files to migrate")
    migrate.set_defaults(func=_cmd_migrate_schema)

    validate = subparsers.add_parser("validate", help="Validate analysis JSON files")
    validate.add_argument("target", metavar="FILE_OR_DIRECTORY", help="Analysis JSON file or media directory to validate")
    validate.set_defaults(func=_cmd_validate)

    subparsers.add_parser("doctor", help="Check the ChordFlask installation state").set_defaults(func=_cmd_doctor)

    return parser


def main(argv=None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        build_parser().print_help()
        raise SystemExit(0)
    args = build_parser().parse_args(argv)
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
