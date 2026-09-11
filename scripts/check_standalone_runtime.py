#!/usr/bin/env python3
"""Reject heavy optional runtimes and model weights from a standalone bundle.

The lightweight ChordFlask Demucs producer (``chordflask_demucs`` and its
submodules) is intentionally bundled. The third-party ``demucs`` package,
Torch, torchaudio, torchcodec, Demucs model weights, and any bundled model
cache must stay external instead.

Usage:
    check_standalone_runtime.py <standalone-executable>

Exits 0 when the archive is clean, 1 on a prohibited entry, and 2 on usage or
listing failure.
"""

from __future__ import annotations

import re
import subprocess
import sys

# Anchored so ``chordflask_demucs`` and the scipy/sklearn
# ``...array_api_compat.torch`` shims are not mistaken for the heavy runtime.
HEAVY_PACKAGE = re.compile(r"^(?:torch|torchaudio|torchcodec|demucs)(?:[./-]|$)")
MODEL_WEIGHT = re.compile(r"\.(?:pt|pth|th|onnx|safetensors|ckpt)$")
MODEL_CACHE = re.compile(r"(?:^|/)(?:htdemucs|htdemucs_ft|mdx_extra)(?:[./-]|$)")


def _recursive_listing(archive: str) -> str:
    result = subprocess.run(
        ["pyi-archive_viewer", "-r", "-l", archive],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr or "pyi-archive_viewer failed\n")
        raise SystemExit(2)
    return result.stdout


def find_offenders(listing: str) -> list[str]:
    offenders = []
    for line in listing.splitlines():
        match = re.search(r"'([^']+)'", line)
        if not match:
            continue
        name = match.group(1)
        if name == "chordflask_demucs" or name.startswith("chordflask_demucs."):
            continue  # allowed lightweight producer/orchestration
        if HEAVY_PACKAGE.match(name) or MODEL_WEIGHT.search(name) or MODEL_CACHE.search(name):
            offenders.append(name)
    return offenders


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_standalone_runtime.py <standalone-executable>", file=sys.stderr)
        return 2
    offenders = find_offenders(_recursive_listing(argv[1]))
    if offenders:
        print("Standalone contains a prohibited heavy runtime or model weight:", file=sys.stderr)
        for name in offenders:
            print(f"  {name}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
