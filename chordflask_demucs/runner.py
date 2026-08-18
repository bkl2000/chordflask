"""Safe invocation of the isolated Demucs command."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .constants import DEFAULT_PROCESS_TIMEOUT_SECONDS, DEMUCS_MODEL, DEMUCS_STEM_NAMES
from .runtime import RuntimeInfo, environment, resolve_device


class DemucsProcessError(RuntimeError):
    """The Demucs subprocess failed or produced an incomplete result."""


def command_for(
    input_wav: Path,
    output_dir: Path,
    runtime: RuntimeInfo,
    *,
    device: str,
) -> list[str]:
    resolved_device = resolve_device(device, runtime)
    return [
        str(runtime.python),
        "-m",
        "demucs.separate",
        "--name",
        DEMUCS_MODEL,
        "--out",
        str(output_dir),
        "--device",
        resolved_device,
        str(input_wav),
    ]


def run_demucs(
    input_wav: Path,
    output_dir: Path,
    runtime: RuntimeInfo,
    *,
    device: str = "auto",
    timeout: int = DEFAULT_PROCESS_TIMEOUT_SECONDS,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    command = command_for(input_wav, output_dir, runtime, device=device)
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env=environment(),
        )
    except OSError as error:
        raise DemucsProcessError(f"Could not execute Demucs: {error}") from error
    except subprocess.TimeoutExpired as error:
        raise DemucsProcessError(f"Demucs timed out after {timeout} seconds") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise DemucsProcessError(
            f"Demucs failed with exit code {result.returncode}:\n{detail or 'no diagnostics'}"
        )

    result_dir = output_dir / DEMUCS_MODEL / input_wav.stem
    stems = {stem: result_dir / f"{stem}.wav" for stem in DEMUCS_STEM_NAMES}
    missing = [stem for stem, path in stems.items() if not path.is_file() or path.is_symlink()]
    if missing:
        raise DemucsProcessError("Demucs did not produce all expected WAV stems: " + ", ".join(missing))
    return stems


__all__ = ["DemucsProcessError", "command_for", "run_demucs"]
