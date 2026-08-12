#!/usr/bin/env python3

import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.dirname(__file__))

from batch_core import run_parallel


def main(argv=None):
    argv = argv or sys.argv[1:]
    media_dir = argv[0] if argv else "data"
    workers = int(argv[1]) if len(argv) > 1 else 2
    try:
        results = run_parallel(media_dir, workers=workers)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 2
    return 1 if any(not result["ok"] for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
