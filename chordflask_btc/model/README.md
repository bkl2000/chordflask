# BTC-ISMIR19 runtime

Isolated inference runtime for the BTC-ISMIR19 large-vocabulary chord model.
It runs only through the `btc-predict-raw` subprocess in the dedicated BTC venv;
it never touches the ChordFlask analyzer or the normal ChordFlask virtual
environment. It is only used when the user runs `make setup-btc` and then
`chordflask-analyze --analyzer btc`.

## Runtime compatibility

`make setup-btc` uses Python 3.12, 3.13, or 3.14 and installs `torch==2.10.0`
from `https://download.pytorch.org/whl/cu128` in `~/.venvs/chordflask-btc`.
The same setup targets Linux x86_64 on all of these distributions:

| Distribution | Python |
| --- | --- |
| Linux Mint 22.x | 3.12 |
| Ubuntu 24.04 | 3.12 |
| Debian 13 | 3.13 |
| Ubuntu/Xubuntu 26.04 | 3.14 |

The default interpreter is `python3`; override it with
`CHORDFLASK_BTC_PYTHON=/path/to/python3.14`. Setup checks the interpreter before
creating a venv or installing packages. When reusing a venv, it checks that
venv's Python instead. An unsupported existing interpreter requires a new
`CHORDFLASK_BTC_VENV` path with a supported Python.

Rerunning setup on a supported existing BTC venv upgrades torch 2.6 to 2.10
without deleting the venv. Existing checkpoint provenance and hash validation,
numpy/librosa installation, and automatic CPU fallback remain unchanged.
CUDA use requires a compatible NVIDIA GPU and driver.

The maintainer manually verified torch 2.10.0+cu128 on Ubuntu/Xubuntu 26.04,
Python 3.14, and an RTX 5070 Laptop: CUDA 12.8 was available, all 221 checkpoint
state keys matched, `load_state_dict` succeeded, and a CUDA forward pass produced
encoder shape `(1, 108, 128)` and prediction shape `(1, 108)`. This is BTC runtime
validation, not full application or standalone acceptance across the matrix.

## Files

- `btc_model.py`, `transformer_modules.py` — model architecture (adapted from
  the MIT-licensed BTC code; kept verbatim so the checkpoint state dict loads).
- `features.py` — modernized CQT feature pipeline (144 bins, 24 bins/octave,
  hop 2048, sr 22050, log magnitude, z-score, `FRAME_SECONDS = 2048/22050`).
- `vocabulary.py` — the 170-class index → label mapping.
- `predict_raw.py` — `btc-predict-raw` entry point (JSON on stdout).

## Provenance and license

- Code: BTC-ISMIR19 (`jayg996/BTC-ISMIR19`), MIT, "Copyright (c) 2019 Jonggwon
  Park" (ISMIR 2019 paper "A Bi-Directional Transformer for Musical Chord
  Recognition").
- Checkpoint `btc_model_large_voca.pt` (12,229,576 bytes): the pretrained
  large-vocabulary (170-class) weights are redistributed by the
  `benasterisk/stemtube-desktop-app` fork (`external/BTC-ISMIR19/test/`).
  They have **no clearly documented redistribution license** (MIT covers the
  code only) and were trained on the Isophonics / Robbie Williams / UsPop2002
  research datasets.

The checkpoint is therefore **never committed or published**. `setup-btc`
refuses to download it without `BTC_ACKNOWLEDGE_WEIGHTS=1`, verifies its size
and SHA-256, and records the expected hash in `checkpoint.sha256` (tracked) so
future runs validate against it. `torch.load(..., weights_only=False)` is only
used on this verified local checkpoint.
