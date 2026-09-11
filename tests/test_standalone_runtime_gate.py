"""Contracts for the standalone heavy-runtime archive gate."""

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "check_standalone_runtime",
    REPO_ROOT / "scripts" / "check_standalone_runtime.py",
)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)


def _listing(*names):
    return "\n".join(f" 0, 1, 1, '{name}'" for name in names)


def test_lightweight_producer_is_allowed():
    offenders = module.find_offenders(
        _listing(
            "chordflask_demucs",
            "chordflask_demucs.cli",
            "chordflask_demucs.runtime",
            "chordflask_demucs.storage",
            "chordflask_base",
            "chordflask_base.model",
        )
    )

    assert offenders == []


def test_heavy_packages_are_rejected():
    offenders = module.find_offenders(
        _listing(
            "torch",
            "torch.version",
            "torchaudio",
            "torchcodec",
            "demucs",
            "demucs.separate",
            "demucs/pretrained/htdemucs.th",
        )
    )

    for name in (
        "torch",
        "torch.version",
        "torchaudio",
        "torchcodec",
        "demucs",
        "demucs.separate",
        "demucs/pretrained/htdemucs.th",
    ):
        assert name in offenders


def test_model_weights_and_cache_are_rejected():
    for name in (
        "weights.pt",
        "weights.pth",
        "weights.th",
        "weights.onnx",
        "weights.safetensors",
        "checkpoint.ckpt",
        "models/htdemucs.pt",
    ):
        assert module.find_offenders(_listing(name)) == [name]


def test_unrelated_torch_compatibility_shims_are_allowed():
    offenders = module.find_offenders(
        _listing(
            "scipy._external.array_api_compat.torch._aliases",
            "scipy._external.array_api_compat.torch.linalg",
            "sklearn.externals.array_api_compat.torch.fft",
        )
    )

    assert offenders == []
