"""Isolated Qwen worker. Only main/check import optional heavy dependencies.

ASR text and word alignment are separate steps. Times are media seconds;
chunk offsets are sample-derived, with no musical offsets or beat estimation.
"""
import argparse
from contextlib import redirect_stdout
import os
import gc
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unicodedata

ASR_MODEL = "Qwen3-ASR-1.7B"
ALIGN_MODEL = "Qwen3-ForcedAligner-0.6B"
LANGUAGES = {"chinese", "english", "cantonese", "french", "german", "italian",
             "japanese", "korean", "portuguese", "russian", "spanish"}


class AlignmentDurationError(ValueError):
    """Official word spans are all points; optional bounds are media seconds."""

    def __init__(self, message, start=None, end=None):
        super().__init__(message)
        self.start = start
        self.end = end


def model_paths(root):
    paths = [Path(root) / name for name in (ASR_MODEL, ALIGN_MODEL)]
    for path in paths:
        if not (path / "config.json").is_file() or not list(path.glob("*.safetensors")):
            raise ValueError(f"Missing model weights at {path}; run make setup-qwen3-asr")
        index = path / "model.safetensors.index.json"
        if index.exists():
            shards = set(json.loads(index.read_text())["weight_map"].values())
            if any(not (path / shard).is_file() for shard in shards):
                raise ValueError(f"Incomplete model weights at {path}")
    return paths


def device_options(torch):
    """CUDA only if usable and this wheel supports the GPU's compute capability."""
    try:
        if torch.cuda.is_available():
            major, minor = torch.cuda.get_device_capability(0)
            architectures = torch.cuda.get_arch_list()
            if f"sm_{major}{minor}" in architectures or f"compute_{major}{minor}" in architectures:
                torch.zeros(1, device="cuda:0")
                return {"device_map": "cuda:0", "dtype": torch.float16}
    except RuntimeError:
        pass
    return {"device_map": "cpu", "dtype": torch.float32}


def recognize_text(model, audio):
    results = model.transcribe(audio=audio, language=None)
    if len(results) != 1:
        raise ValueError("ASR returned an incomplete result")
    text, language = results[0].text, results[0].language
    if not isinstance(text, str) or not isinstance(language, str):
        raise ValueError("ASR returned invalid text/language")
    return text.strip(), language


def normalized_text(text):
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold()
                   if unicodedata.category(c)[0] in "LNM")


def validate_spans(spans, duration):
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid audio duration")
    if not isinstance(spans, list) or not spans:
        raise ValueError("No usable timed lyrics (possibly instrumental)")
    previous_end = 0.0
    for item in spans:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip():
            raise ValueError("Missing aligned text")
        start, end = item.get("start"), item.get("end")
        if any(type(t) not in (float, int) or not math.isfinite(t) for t in (start, end)):
            raise ValueError("Missing or non-finite alignment timestamps")
        if not (previous_end <= start <= end <= duration):
            raise ValueError("Invalid, overlapping or out-of-audio alignment timestamps")
        previous_end = end
    # Upstream quantization/correction can collapse individual word spans.
    # Keep those measured points and their text, without inventing duration.
    if not any(item["end"] > item["start"] for item in spans):
        raise AlignmentDurationError("Alignment has no usable duration")
    return spans


def check_alignment_language(language, model=None):
    supported = LANGUAGES
    if model is not None:
        installed = model.get_supported_languages()
        if installed is None:
            raise ValueError("Installed aligner does not declare supported languages")
        supported = supported.intersection(str(item).lower() for item in installed)
    if language.lower() not in supported:
        raise ValueError(f"Detected language {language} is not officially supported by the installed "
                         "Qwen3 ForcedAligner; no Lyrics V2 file will be generated")


def align_text(model, audio, text, language, duration):
    """Align an independently supplied transcript; reject missing/changed words."""
    check_alignment_language(language, model)
    results = model.align(audio=audio, text=text, language=language)
    if len(results) != 1:
        raise ValueError("Alignment returned an incomplete result")
    spans = [{"text": item.text, "start": item.start_time, "end": item.end_time}
             for item in results[0]]
    validate_spans(spans, duration)
    if normalized_text("".join(item["text"] for item in spans)) != normalized_text(text):
        raise ValueError("Alignment does not cover the complete recognized text")
    # Preserve the ASR spelling, punctuation and Unicode while accepting the
    # aligner's word/character segmentation. No synthesized timestamps.
    cursor = 0
    for item in spans:
        wanted = normalized_text(item["text"])
        end = cursor
        while end <= len(text) and normalized_text(text[cursor:end]) != wanted:
            end += 1
        if end > len(text):
            raise ValueError("Cannot map aligned units to recognized text")
        while end < len(text) and not normalized_text(text[end]):
            end += 1
        item["text"] = text[cursor:end]
        cursor = end
    if cursor != len(text):
        raise ValueError("Incomplete text alignment")
    return spans


def lines_from_spans(spans):
    """Group measured words into readable rows; measured ends delimit pauses."""
    rows = []
    group = []
    for item in spans:
        if group and (item.get("break_before", False) or len(group) >= 8
                      or item["start"] - group[-1]["end"] >= 1.5):
            rows.append((group[0]["start"], "".join(word["text"] for word in group).strip()))
            rows.append((group[-1]["end"], ""))
            group = []
        group.append(item)
    if group:
        rows.append((group[0]["start"], "".join(word["text"] for word in group).strip()))
        rows.append((group[-1]["end"], ""))
    if any(end[0] <= start[0] for start, end in zip(rows[::2], rows[1::2], strict=True)):
        raise ValueError("Lyric row has no usable duration")
    return rows


def infer(audio_path, root, work_directory=None):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    require_package_version()
    import torch
    import soundfile as sf
    from qwen_asr import Qwen3ASRModel, Qwen3ForcedAligner

    asr_path, align_path = model_paths(root)
    options = device_options(torch)
    with tempfile.TemporaryDirectory(prefix="chordflask-qwen3-", dir=work_directory) as directory:
        wav = Path(directory) / "audio.wav"
        result = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(audio_path),
                                 "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)],
                                capture_output=True, text=True, timeout=600, check=False)
        if result.returncode:
            raise ValueError(f"Audio decode failed: {result.stderr[-1000:]}")
        transcripts = []
        model = Qwen3ASRModel.from_pretrained(str(asr_path), **options,
                                             max_inference_batch_size=1, max_new_tokens=4096)
        # Keep chunks well below the aligner's documented 300 second limit and
        # bound attention memory. Both steps see exactly the same sample range.
        with sf.SoundFile(wav) as sound:
            duration = len(sound) / sound.samplerate
            for start in range(0, len(sound), 30 * sound.samplerate):
                samples = sound.read(30 * sound.samplerate, dtype="float32")
                text, language = recognize_text(model, (samples, sound.samplerate))
                print(f"Detected language: {language or 'none'}; audio chunk at {start / sound.samplerate:.1f}s", file=sys.stderr)
                if text:
                    check_alignment_language(language)
                    transcripts.append((start, len(samples), text, language))
        del model
        gc.collect()
        if options["device_map"] != "cpu":
            torch.cuda.empty_cache()
        if not transcripts:
            raise ValueError("No recognized text (possibly instrumental)")
        model = Qwen3ForcedAligner.from_pretrained(str(align_path), **options)
        spans = []
        with sf.SoundFile(wav) as sound:
            for start, count, text, language in transcripts:
                sound.seek(start)
                samples = sound.read(count, dtype="float32")
                try:
                    chunk = align_text(model, (samples, sound.samplerate), text, language,
                                       count / sound.samplerate)
                except AlignmentDurationError as error:
                    raise AlignmentDurationError(
                        f"Alignment failed at {start / sound.samplerate:.1f}s "
                        f"(detected language {language}): {error}",
                        start / sound.samplerate, (start + count) / sound.samplerate,
                    ) from error
                except ValueError as error:
                    raise ValueError(f"Alignment failed at {start / sound.samplerate:.1f}s "
                                     f"(detected language {language}): {error}") from error
                chunk[0]["break_before"] = True
                offset = start / sound.samplerate
                spans.extend(dict(item, start=item["start"] + offset, end=item["end"] + offset)
                             for item in chunk)
        return {"spans": validate_spans(spans, duration), "duration": duration,
                "device": options["device_map"], "languages": sorted({entry[3] for entry in transcripts})}


def require_package_version():
    import importlib.metadata
    if importlib.metadata.version("qwen-asr") != "0.0.6":
        raise ValueError("Incompatible qwen-asr version; expected 0.0.6. Rerun make setup-qwen3-asr")


def check(root):
    require_package_version()
    import importlib.metadata
    import torch
    from qwen_asr import Qwen3ASRModel, Qwen3ForcedAligner

    if not callable(Qwen3ASRModel.from_pretrained) or not callable(Qwen3ForcedAligner.from_pretrained):
        raise ValueError("Incompatible Qwen API")
    print(f"Python: {sys.version.split()[0]}")
    for package in ("qwen-asr", "torch", "transformers", "soundfile", "accelerate"):
        print(f"{package}: {importlib.metadata.version(package)}")
    print(f"CUDA available: {torch.cuda.is_available()}; selected: {device_options(torch)['device_map']}")
    import shutil
    if shutil.which("ffmpeg") is None:
        raise ValueError("System FFmpeg is missing; install it separately")
    from safetensors import safe_open
    for path in model_paths(root):
        for weights in path.glob("*.safetensors"):
            with safe_open(weights, framework="pt", device="cpu") as tensors:
                if not list(tensors.keys()):
                    raise ValueError(f"Empty model weights: {weights}")
        print(f"Model: {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", required=True, type=Path)
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--work-directory", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.check:
            check(args.models)
        elif args.audio is not None:
            with redirect_stdout(sys.stderr):
                result = infer(args.audio, args.models, args.work_directory)
            print(json.dumps(result, ensure_ascii=False))
        else:
            parser.error("--audio or --check required")
    except Exception as error:  # External runtime boundary: preserve sidecars on every failure.
        if isinstance(error, AlignmentDurationError) and error.start is not None:
            print(json.dumps({"error": "alignment_no_duration",
                              "start": error.start, "end": error.end}))
        print(f"{type(error).__name__}: {error}. Check make qwen3-asr-check; "
              "for memory errors use a larger-memory device or CPU (CUDA_VISIBLE_DEVICES='').",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
