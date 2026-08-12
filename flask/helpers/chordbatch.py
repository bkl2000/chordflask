#!/usr/bin/env python3

import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.dirname(__file__))

from batch_core import run_serial
from chordanalyzer import ChordAnalyzer


def main(argv=None):
    argv = argv or sys.argv[1:]
    media_dir = argv[0] if argv else "data"
    try:
        results = run_serial(media_dir, ChordAnalyzer)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 2
    return 1 if any(not result["ok"] for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
