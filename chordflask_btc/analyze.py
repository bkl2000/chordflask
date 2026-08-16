"""Conservative user-facing BTC analysis dispatch.

Requires an existing normal ChordFlask analysis; a file without one is skipped
with ``SKIP: no ChordFlask analysis`` and never gets a BTC-only file. It uses the
installed runtime wrapper (``~/.venvs/chordflask-btc/bin/btc-predict-raw``).
"""

from __future__ import annotations

import sys
from pathlib import Path

from .batch import (
    CLASS_CURRENT,
    CLASS_NO_ANALYSIS,
    CLASS_STALE,
    classify_btc_file,
)
from .discovery import DirectoriesError, discover_media_directory
from .predictor import (
    BtcPredictionError,
    model_sha256,
    predict_btc_media,
    regular_media,
)
from .runtime import BtcRuntimeError, detect_btc_runtime
from .schema import analysis_json_path


def require_btc_runtime_user() -> int:
    """Return 0 when the BTC runtime is complete, else a clear setup hint and 2."""
    state = detect_btc_runtime()
    if state["complete"]:
        return 0
    print("The BTC runtime is not installed or incomplete.", file=sys.stderr)
    for item in state["missing"]:
        print(f"  missing: {item}", file=sys.stderr)
    print("Run: make setup-btc to install it.", file=sys.stderr)
    return 2


def analyze_btc_file(target: Path, *, replace: bool) -> int:
    try:
        media = regular_media(target)
    except BtcPredictionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    code = require_btc_runtime_user()
    if code:
        return code

    if not analysis_json_path(media).exists(follow_symlinks=False):
        print("SKIP: no ChordFlask analysis")
        return 0

    classification, reason = classify_btc_file(media, model_sha256())
    if classification == CLASS_NO_ANALYSIS:
        print(f"SKIP: {reason}")
        return 0
    if classification == CLASS_CURRENT:
        print("SKIP: BTC track already current")
        return 0
    if classification == CLASS_STALE and not replace:
        print("STALE: use --replace")
        return 0

    try:
        result = predict_btc_media(media, replace=replace)
    except BtcPredictionError as exc:
        print(f"ERROR: BTC analysis failed: {exc}", file=sys.stderr)
        return 1
    print(f"OK: {result['events']} events")
    return 0


def analyze_btc_directory(directory: Path, *, dry_run: bool, replace: bool) -> int:
    code = require_btc_runtime_user()
    if code:
        return code

    try:
        media_files = discover_media_directory(directory)
    except DirectoriesError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    model_hash = model_sha256()
    counts = {
        "processed": 0,
        "planned": 0,
        "current": 0,
        "no_analysis": 0,
        "stale": 0,
        "failed": 0,
    }
    for index, media in enumerate(media_files, 1):
        print(f"[{index}/{len(media_files)}] {media.name}")
        if not analysis_json_path(media).exists(follow_symlinks=False):
            print("       SKIP: no ChordFlask analysis")
            counts["no_analysis"] += 1
            continue
        classification, reason = classify_btc_file(media, model_hash)
        if classification == CLASS_NO_ANALYSIS:
            print(f"       SKIP: {reason}")
            counts["no_analysis"] += 1
            continue
        if classification == CLASS_CURRENT:
            print("       SKIP: BTC track already current")
            counts["current"] += 1
            continue
        if classification == CLASS_STALE and not replace:
            print("       STALE: use --replace")
            counts["stale"] += 1
            continue
        if dry_run:
            print("       ANALYZE")
            counts["planned"] += 1
            continue
        try:
            result = predict_btc_media(media, replace=replace)
        except (BtcPredictionError, BtcRuntimeError, OSError, ValueError) as exc:
            print(f"       ERROR: BTC analysis failed: {exc}", file=sys.stderr)
            counts["failed"] += 1
            continue
        if result["status"] == "skipped":
            counts["current"] += 1
            print("       SKIP: BTC track already current")
        else:
            counts["processed"] += 1
            print(f"       OK: {result['events']} events")

    print("")
    print("BTC dry-run complete" if dry_run else "BTC analysis complete")
    print("")
    print(f"files:       {len(media_files)}")
    print(f"processed:   {counts['processed']}")
    print(f"current:     {counts['current']}")
    print(f"no-analysis: {counts['no_analysis']}")
    print(f"stale:       {counts['stale']}")
    print(f"failed:      {counts['failed']}")
    if dry_run:
        print(f"would analyze: {counts['planned']}")
    return 1 if counts["failed"] else 0


def analyze_btc(target: Path, *, replace: bool, dry_run: bool) -> int:
    if target.is_dir():
        return analyze_btc_directory(target, dry_run=dry_run, replace=replace)
    if dry_run:
        print("Error: --dry-run requires a directory", file=sys.stderr)
        return 2
    return analyze_btc_file(target, replace=replace)
