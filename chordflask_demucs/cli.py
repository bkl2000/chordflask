"""Command-line batch processing for Demucs stem sets."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from .audio import (
    AudioCommandError,
    convert_wav_to_flac,
    extract_canonical_audio,
    hash_file,
    probe_audio,
    probe_canonical_wav,
    probe_source_timeline,
)
from .constants import CURRENT, ERROR, STALE
from .discovery import DiscoveryError, discover_target
from .runner import DemucsProcessError, run_demucs
from .runtime import DemucsRuntimeError, RuntimeInfo, require_runtime, validate_device
from .storage import DemucsBusyError, DemucsStatus, classify, media_lock, publish_set
from .validation import (
    DemucsValidationError,
    validate_normalized_stems,
    validate_raw_stems,
)


def _process_one(
    media_path: Path,
    runtime: RuntimeInfo,
    *,
    device: str,
    replace: bool = True,
) -> Path | None:
    with media_lock(media_path):
        status = classify(media_path, runtime=runtime, device=device)
        if status.label == ERROR:
            raise RuntimeError(status.reason)
        if status.label == CURRENT and not replace:
            return None
        if status.label == STALE and not replace:
            raise RuntimeError(status.reason)
        analysis_dir = media_path.parent / ".chordflask"
        analysis_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f".{media_path.stem}.demucs-",
            dir=analysis_dir,
        ) as work_name:
            work_dir = Path(work_name)
            source_hash = hash_file(media_path)
            source_size = media_path.stat().st_size
            source_timeline = probe_source_timeline(media_path)
            source_wav = work_dir / "source.wav"
            extract_canonical_audio(media_path, source_wav)
            source = probe_canonical_wav(source_wav)

            raw_dir = work_dir / "raw"
            raw_stems = run_demucs(source_wav, raw_dir, runtime, device=device)
            raw_facts = {stem: probe_audio(path) for stem, path in raw_stems.items()}
            tail_adjustments = validate_raw_stems(source, raw_facts)

            flac_dir = work_dir / "flac"
            flac_dir.mkdir()
            for stem_name, raw_path in raw_stems.items():
                convert_wav_to_flac(
                    raw_path,
                    flac_dir / f"{stem_name}.flac",
                    target_sample_count=source.sample_count,
                )
            flac_facts = {stem: probe_audio(flac_dir / f"{stem}.flac") for stem in raw_stems}
            validate_normalized_stems(source, flac_facts)

            if hash_file(media_path) != source_hash or media_path.stat().st_size != source_size:
                raise RuntimeError("Source media changed while Demucs was processing it")

            return publish_set(
                media_path,
                staged_dir=flac_dir,
                source=source,
                source_hash=source_hash,
                source_size=source_size,
                source_timeline=source_timeline,
                runtime=runtime,
                device=device,
                stem_facts=flac_facts,
                tail_adjustments=tail_adjustments,
            )


def _print_status(index: int, total: int, media_path: Path, status: DemucsStatus) -> None:
    print(f"[{index}/{total}] {media_path.name}")
    suffix = f": {status.reason}" if status.reason else ""
    print(f"       {status.label}{suffix}")


def run(target: Path, *, replace: bool, dry_run: bool, device: str) -> int:
    validate_device(device)
    try:
        media_files = discover_target(target)
    except DiscoveryError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2

    runtime = None
    counts = {"current": 0, "todo": 0, "stale": 0, "processed": 0, "failed": 0}
    for index, media_path in enumerate(media_files, 1):
        try:
            status = classify(media_path, runtime=runtime, device=device)
        except Exception as error:
            status = DemucsStatus(ERROR, str(error))
        if dry_run:
            if status.label in {CURRENT, STALE} and replace:
                status = DemucsStatus("REPLACE", status.reason)
            _print_status(index, len(media_files), media_path, status)
            counts[status.label.lower()] = counts.get(status.label.lower(), 0) + 1
            continue

        if status.label == CURRENT and not replace:
            counts["current"] += 1
            _print_status(index, len(media_files), media_path, status)
            continue
        if status.label == STALE and not replace:
            counts["stale"] += 1
            _print_status(index, len(media_files), media_path, status)
            print("       Use --replace to regenerate the complete stem set")
            continue
        if status.label == ERROR:
            counts["failed"] += 1
            _print_status(index, len(media_files), media_path, status)
            continue

        try:
            if runtime is None:
                runtime = require_runtime()
            json_path = _process_one(media_path, runtime, device=device, replace=replace)
            if json_path is None:
                counts["current"] += 1
                _print_status(index, len(media_files), media_path, DemucsStatus(CURRENT, "already current"))
                continue
            counts["processed"] += 1
            print(f"[{index}/{len(media_files)}] {media_path.name}")
            print(f"       OK: {json_path}")
        except (
            DemucsBusyError,
            DemucsRuntimeError,
            AudioCommandError,
            DemucsProcessError,
            DemucsValidationError,
            OSError,
            RuntimeError,
            ValueError,
        ) as error:
            counts["failed"] += 1
            print(f"[{index}/{len(media_files)}] {media_path.name}", file=sys.stderr)
            print(f"       ERROR: {error}", file=sys.stderr)

    print("")
    print("Demucs dry-run complete" if dry_run else "Demucs processing complete")
    print(f"files:     {len(media_files)}")
    if dry_run:
        print(f"current:   {counts.get('current', 0)}")
        print(f"todo:      {counts.get('todo', 0)}")
        print(f"stale:     {counts.get('stale', 0)}")
        print(f"errors:    {counts.get('error', 0)}")
        return 0
    print(f"processed: {counts['processed']}")
    print(f"current:   {counts['current']}")
    print(f"stale:     {counts['stale']}")
    print(f"failed:    {counts['failed']}")
    return 1 if counts["failed"] or counts["stale"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chordflask-demucs",
        description=(
            "Create and register one complete htdemucs FLAC stem set for an MP3/MP4/WebM file or a directory."
        ),
        epilog=(
            "Examples:\n"
            "  chordflask-demucs song.mp3\n"
            "  chordflask-demucs ~/Music\n"
            "  chordflask-demucs --dry-run ~/Music\n"
            "  chordflask-demucs --replace song.mp3\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Regenerate an existing or stale complete stem set",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show CURRENT/TODO/STALE status without changing files",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda"),
        default="auto",
        help="Demucs device (default: auto)",
    )
    parser.add_argument("target", type=Path, help="Media file or non-recursive directory")
    return parser


def main(argv=None) -> None:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    raise SystemExit(run(args.target, replace=args.replace, dry_run=args.dry_run, device=args.device))


if __name__ == "__main__":
    main()
