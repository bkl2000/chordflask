"""Nonrecursive batch Score CLI, using an optional subprocess runtime."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from chordflask_demucs.audio import executable, extract_canonical_audio
from chordflask_demucs.discovery import discover_target

from .notation import QUANTIZATION
from .runtime import code_identity, execute, require_runtime
from .storage import classify, input_snapshot, publish, safe_path, score_lock


def discover(target):
    if target.is_symlink():
        raise ValueError("Score target must not be a symlink")
    if target.is_file():
        if target.suffix.lower() not in {".mp3", ".mp4"}:
            raise ValueError("Score accepts MP3/MP4 files")
        media = target.resolve()
        preferred = next((p for p in discover_target(media.parent)
                          if p.stem.casefold() == media.stem.casefold()), None)
        if preferred is None:
            raise ValueError(f"Media file disappeared during discovery: {media}")
        if preferred.is_symlink() or media != preferred.resolve():
            raise ValueError(f"Shared QM analysis belongs to preferred media {preferred.name}; use that file")
        return [media]
    if not target.is_dir():
        raise ValueError(f"Media target does not exist: {target}")
    return [p.resolve() for p in discover_target(target)
            if not p.is_symlink() and p.suffix.lower() in {".mp3", ".mp4"}]


def prepare_audio(media, inputs, destination):
    if inputs["audio_source"] == "original":
        extract_canonical_audio(media, destination)
        return
    command = [executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    for name in ("other", "bass", "drums"):
        command += ["-i", str(safe_path(media.parent, inputs["stems"][name]["path"]))]
    command += ["-filter_complex", "[0:a][1:a][2:a]amix=inputs=3:duration=longest:normalize=0[out]",
                "-map", "[out]", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(destination)]
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=600, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"Could not mix no-vocals audio: {error}") from error
    if result.returncode:
        raise RuntimeError(f"Could not mix no-vocals audio: {result.stderr[-4000:]}")


def process_one(media, *, audio_source, device, replace, runtime, quantization="mixed"):
    with score_lock(media) as root:
        status = classify(media, audio_source=audio_source, device=device, runtime=runtime,
                          quantization=quantization)
        if status.label == "ERROR":
            raise ValueError(status.reason)
        if status.label == "CURRENT" and not replace:
            return None
        if status.label == "STALE" and not replace:
            raise ValueError(status.reason + "; use --replace")
        inputs = input_snapshot(media, audio_source)
        resolved = "cuda" if device == "auto" and runtime["cuda"] else "cpu" if device == "auto" else device
        if resolved == "cuda" and not runtime["cuda"]:
            raise ValueError("CUDA is unavailable; choose --device cpu")
        pipeline = {"code": code_identity(), "runtime": runtime,
                    "device_request": device, "device": resolved,
                    "quantization": list(QUANTIZATION[quantization]), "hand_split": 60}
        with tempfile.TemporaryDirectory(prefix=".score-", dir=root) as work:
            work = Path(work)
            audio = work / "input.wav"
            prepare_audio(media, inputs, audio)
            rhythm = work / "rhythm.json"
            rhythm.write_text(json.dumps(inputs["rhythm"], allow_nan=False), encoding="utf-8")
            staged = work / "result"
            execute(["--audio", str(audio), "--rhythm", str(rhythm), "--output", str(staged),
                     "--device", resolved, "--quantization", quantization])
            return publish(media, staged, inputs, pipeline)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Optional QM-aligned piano transcription (Score)")
    parser.add_argument("target", type=Path, help="MP3/MP4 file or nonrecursive directory")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--audio-source", choices=("original", "no-vocals"), default="original")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--quantization", choices=QUANTIZATION, default="mixed",
                        help="notation grid: mixed (sixteenths/triplets, default) or binary (sixteenths only)")
    args = parser.parse_args(argv)
    try:
        media_files = discover(args.target.expanduser())
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    failed = False
    runtime = None
    for media in media_files:
        status = classify(media, audio_source=args.audio_source, device=args.device,
                          quantization=args.quantization)
        if args.dry_run:
            label = "REPLACE" if args.replace and status.label in {"CURRENT", "STALE"} else status.label
            print(f"{media.name}: {label}: {status.reason}")
            failed |= status.label == "ERROR"
            continue
        try:
            if status.label == "ERROR":
                raise ValueError(status.reason)
            if status.label == "STALE" and not args.replace:
                raise ValueError(status.reason + "; use --replace")
            if runtime is None:
                runtime = require_runtime()
            path = process_one(media, audio_source=args.audio_source, device=args.device,
                               replace=args.replace, runtime=runtime, quantization=args.quantization)
            print(f"{media.name}: {'PROCESSED: ' + str(path) if path else 'CURRENT'}")
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            print(f"{media.name}: ERROR: {error}", file=sys.stderr)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
