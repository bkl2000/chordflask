#!/usr/bin/env python3
"""btc-predict-raw: run BTC inference on one audio file and emit JSON to stdout.

Contract:
- stdout carries exactly one JSON array of ``{"timestamp", "chord"}`` objects,
  one entry per chord change, using the raw BTC label notation (e.g. ``F#:7``,
  ``B:maj7``, ``N``, ``X``). Timestamps use ``frame_index * 2048 / 22050``.
- All logging and diagnostics go to stderr.
- This wrapper never reads or writes ChordFlask analysis JSON.

The checkpoint is loaded with ``torch.load(..., weights_only=False)`` only after
``setup-btc`` has verified its SHA-256; the model/checkpoint key sets are checked
explicitly before a strict ``load_state_dict``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

from btc_model import BTC_model  # noqa: E402
from features import FRAME_SECONDS, TIMESTEP, compute_features  # noqa: E402
from vocabulary import label_for_index  # noqa: E402

DEFAULT_CHECKPOINT = _SCRIPT_DIR / "btc_model_large_voca.pt"

MODEL_CONFIG = {
    "feature_size": 144,
    "timestep": TIMESTEP,
    "num_chords": 170,
    "input_dropout": 0.2,
    "layer_dropout": 0.2,
    "attention_dropout": 0.2,
    "relu_dropout": 0.2,
    "num_layers": 8,
    "num_heads": 4,
    "hidden_size": 128,
    "total_key_depth": 128,
    "total_value_depth": 128,
    "filter_size": 128,
    "loss": "ce",
    "probs_out": False,
}


def load_checkpoint(path: Path) -> dict:
    """Load the ``{'model', 'mean', 'std'}`` checkpoint and validate its shape."""
    checkpoint = torch.load(str(path), map_location="cpu", weights_only=False)
    if not isinstance(checkpoint, dict):
        raise ValueError(f"Checkpoint root is not a dict: {path}")
    for key in ("model", "mean", "std"):
        if key not in checkpoint:
            raise ValueError(f"Checkpoint is missing {key!r}: {path}")
    return checkpoint


def _check_state_dict_keys(model: BTC_model, state_dict: dict, path: Path) -> None:
    model_keys = set(model.state_dict().keys())
    state_keys = set(state_dict.keys())
    missing = sorted(model_keys - state_keys)
    unexpected = sorted(state_keys - model_keys)
    if missing or unexpected:
        detail = []
        if missing:
            detail.append("missing=" + ",".join(missing))
        if unexpected:
            detail.append("unexpected=" + ",".join(unexpected))
        raise ValueError(f"Checkpoint/model key mismatch for {path}: " + "; ".join(detail))


def predict_indices(model: BTC_model, feature: np.ndarray, device: torch.device) -> list[int]:
    n_timestep = MODEL_CONFIG["timestep"]
    total_frames = feature.shape[0]
    num_instances = total_frames // n_timestep
    predictions: list[int] = []
    with torch.no_grad():
        for t in range(num_instances):
            chunk = feature[t * n_timestep:(t + 1) * n_timestep]
            chunk_tensor = torch.tensor(chunk, dtype=torch.float32).unsqueeze(0).to(device)
            encoder_output, _ = model.self_attn_layers(chunk_tensor)
            prediction, _ = model.output_layer(encoder_output)
            preds = prediction.squeeze().cpu().numpy()
            if preds.ndim == 0:
                predictions.append(int(preds))
            else:
                predictions.extend(int(p) for p in preds)
    return predictions


def indices_to_events(predictions: list[int]) -> list[dict]:
    """Collapse per-frame indices into ``{timestamp, chord}`` change events."""
    events = []
    previous = None
    for index, class_index in enumerate(predictions):
        label = label_for_index(class_index)
        if label == previous:
            continue
        events.append({"timestamp": round(index * FRAME_SECONDS, 6), "chord": label})
        previous = label
    return events


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="BTC chord inference -> JSON on stdout")
    parser.add_argument("audio_file", help="Audio file (WAV/MP3/MP4/WebM)")
    parser.add_argument("--model", default=None, help="Checkpoint path (default: large vocabulary)")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    args = parser.parse_args(argv)

    audio_path = Path(args.audio_file)
    if not audio_path.is_file():
        print(f"ERROR: audio file not found: {audio_path}", file=sys.stderr)
        return 2

    checkpoint = Path(args.model) if args.model else DEFAULT_CHECKPOINT
    if not checkpoint.is_file():
        print(f"ERROR: model not found: {checkpoint}", file=sys.stderr)
        return 2

    device_name = "cuda" if (args.device != "cpu" and torch.cuda.is_available()) else "cpu"
    device = torch.device(device_name)

    print(f"Loading BTC model from {checkpoint}", file=sys.stderr)
    checkpoint_data = load_checkpoint(checkpoint)
    model = BTC_model(config=MODEL_CONFIG)
    _check_state_dict_keys(model, checkpoint_data["model"], checkpoint)
    model.load_state_dict(checkpoint_data["model"])
    model.to(device)
    model.eval()

    mean = np.asarray(checkpoint_data["mean"], dtype=np.float32)
    std = np.asarray(checkpoint_data["std"], dtype=np.float32)

    print(f"Analyzing {audio_path.name} on {device_name}", file=sys.stderr)
    feature = compute_features(audio_path, mean, std)
    predictions = predict_indices(model, feature, device)
    events = indices_to_events(predictions)

    json.dump(events, sys.stdout, allow_nan=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
