#!/usr/bin/env python3

"""Command-line wrapper for the shared ChordFlask PDF renderer."""

import argparse
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chord_sheet_pdf import ChordSheetPdfRenderer  # noqa: E402


def build_argument_parser():
    parser = argparse.ArgumentParser(
        description="Render a ChordFlask Markdown leadsheet as a multi-page PDF."
    )
    parser.add_argument("input", help="Markdown input file")
    parser.add_argument("-o", "--output", help="PDF output file")
    return parser


def main(argv=None):
    args = build_argument_parser().parse_args(argv)
    output = ChordSheetPdfRenderer().render_file(args.input, args.output)
    print(f"Written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
