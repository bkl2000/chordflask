"""Directory batch planning and execution for the BTC chord track.

The batch is non-recursive, one preferred media file per stem, smallest files
first, and only touches files that already have a valid Schema-v3 analysis.
Per-file errors are isolated so one failure never aborts the batch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .discovery import discover_media_directory
from .predictor import (
    BtcPredictionError,
    model_sha256,
    predict_btc_media,
    sha256,
)
from .runtime import BtcRuntimeError, require_btc_runtime
from .schema import BTC_TRACK_ID, SchemaV3Error, analysis_json_path, load_analysis

CLASS_TODO = "TODO"
CLASS_CURRENT = "CURRENT"
CLASS_STALE = "STALE"
CLASS_NO_ANALYSIS = "NO ANALYSIS"


def classify_btc_file(media_path: Path, model_hash: str) -> tuple[str, str]:
    """Classify one media file for the dry-run / batch planning.

    Returns ``(classification, reason)`` where classification is one of
    ``TODO``, ``CURRENT``, ``STALE``, or ``NO ANALYSIS``. A file without any
    analysis is ``TODO`` (BTC creates a minimal analysis file); only an
    existing but invalid file is ``NO ANALYSIS``.
    """
    json_path = analysis_json_path(media_path)
    if not json_path.exists(follow_symlinks=False):
        return CLASS_TODO, ""
    try:
        data, _ = load_analysis(media_path)
    except SchemaV3Error as exc:
        return CLASS_NO_ANALYSIS, f"invalid ChordFlask analysis ({exc})"
    existing = data["chord_tracks"].get(BTC_TRACK_ID)
    if existing is None:
        return CLASS_TODO, ""
    metadata = existing.get("metadata", {}) if isinstance(existing, dict) else {}
    media_hash = sha256(media_path)
    if (
        metadata.get("model_sha256") == model_hash
        and metadata.get("media_sha256") == media_hash
    ):
        return CLASS_CURRENT, "BTC already current"
    return CLASS_STALE, "use --replace"


def plan_btc_batch(directory: Path) -> list[dict[str, Any]]:
    """Classify every discovered media file without running BTC or writing."""
    require_btc_runtime()
    model_hash = model_sha256()
    plan = []
    for media_path in discover_media_directory(directory):
        classification, reason = classify_btc_file(media_path, model_hash)
        plan.append(
            {
                "media": media_path,
                "size_bytes": media_path.stat().st_size,
                "classification": classification,
                "reason": reason,
            }
        )
    return plan


def format_size(size: int) -> str:
    return f"{size / 1_000_000:.1f} MB"


def print_batch_plan(plan: list[dict[str, Any]]) -> None:
    """Print the dry-run plan without side effects."""
    for index, item in enumerate(plan, 1):
        print(f"[{index}/{len(plan)}] {item['media'].name}  {format_size(item['size_bytes'])}")
        suffix = f": {item['reason']}" if item["reason"] else ""
        print(f"       {item['classification']}{suffix}")


def run_btc_batch(directory: Path, *, replace: bool = False) -> int:
    """Run BTC inference over every discovered media file; return an exit code.

    Exit codes: 0 = everything processed or skipped, 1 = at least one inference
    failure. The caller maps configuration/argument errors to exit code 2.
    """
    require_btc_runtime()
    plan = plan_btc_batch(directory)

    counts = {
        "processed": 0,
        "current": 0,
        "no_analysis": 0,
        "stale": 0,
        "failed": 0,
    }
    for index, item in enumerate(plan, 1):
        print(f"[{index}/{len(plan)}] {item['media'].name}  {format_size(item['size_bytes'])}")
        if item["classification"] == CLASS_NO_ANALYSIS:
            print(f"       SKIP: {item['reason']}")
            counts["no_analysis"] += 1
            continue
        if item["classification"] == CLASS_CURRENT and not replace:
            print("       SKIP: BTC already current")
            counts["current"] += 1
            continue
        if item["classification"] == CLASS_STALE and not replace:
            print("       STALE: use --replace")
            counts["stale"] += 1
            continue
        try:
            result = predict_btc_media(item["media"], replace=replace)
        except (BtcPredictionError, BtcRuntimeError, OSError, ValueError) as exc:
            print(f"       ERROR: BTC inference failed: {exc}")
            counts["failed"] += 1
            continue
        if result["status"] == "skipped":
            counts["current"] += 1
            print("       SKIP: BTC already current")
        else:
            counts["processed"] += 1
            print(f"       OK: {result['events']} events")

    print("")
    print("BTC batch complete")
    print("")
    print(f"files:       {len(plan)}")
    print(f"processed:   {counts['processed']}")
    print(f"current:     {counts['current']}")
    print(f"no-analysis: {counts['no_analysis']}")
    print(f"stale:       {counts['stale']}")
    print(f"failed:      {counts['failed']}")
    return 1 if counts["failed"] else 0
