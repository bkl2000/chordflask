"""``chordflask-export`` — export playable leadsheets (Markdown and/or PDF).

The canonical user command for exporting chord leadsheets. It reuses the shared
Markdown formatter (``chord_markdown``) and PDF renderer (``chord_sheet_pdf``)
plus the same track/transpose/repeat logic as the internal batch helper, and
supports one file or a whole directory with a chosen format.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .batch_core import find_media_files
from .chordleadsheet_batch import (
    LeadsheetExportError,
    add_export_options,
    export_file,
)

_MEDIA_SUFFIXES = {".mp3", ".mp4", ".webm"}

_EPILOG = """\
Examples:
  chordflask-export song.mp4
  chordflask-export /music/videos
  chordflask-export --format markdown song.mp4
  chordflask-export --format pdf /music/videos
  chordflask-export --format both /music/videos
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chordflask-export",
        description="Export playable leadsheets (Markdown and/or PDF) for media files.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "target",
        type=Path,
        help="MP3/MP4/WebM file or a directory of media files (non-recursive)",
    )
    add_export_options(parser)
    return parser


def _resolve_files(target: Path) -> list[Path] | None:
    if target.is_dir():
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


def main(argv=None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        build_parser().print_help()
        raise SystemExit(0)
    args = build_parser().parse_args(argv)
    files = _resolve_files(args.target)
    if files is None:
        raise SystemExit(2)

    failures = 0
    for path in files:
        try:
            export_file(path, args)
        except (LeadsheetExportError, Exception) as error:  # noqa: BLE001
            failures += 1
            print(f"Error: {path}: {error}", file=sys.stderr)
            continue
        print(f"Exported: {path}")

    print("")
    print(f"Done: {len(files)} files, {failures} failed")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
