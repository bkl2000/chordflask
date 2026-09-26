# BTC-ISMIR19 runtime

Isolated inference runtime for the BTC-ISMIR19 large-vocabulary chord model.
It runs only through the `btc-predict-raw` subprocess in the dedicated BTC venv;
it never touches the ChordFlask analyzer or the normal ChordFlask virtual
environment. It is only used when the user runs `make setup-btc` and then
`chordflask-analyze --analyzer btc`.

Chordino remains ChordFlask's built-in default. BTC is optional and writes an
additional named chord track; it does not replace or modify Chordino.

## Installation and weights acknowledgement

From a source checkout:

```bash
make setup-btc BTC_ACKNOWLEDGE_WEIGHTS=1
make btc-check
```

Setup creates the isolated `~/.venvs/chordflask-btc` environment and downloads
the model checkpoint only after the explicit acknowledgement. The checkpoint
has no clearly documented redistribution licence, so it is neither committed
to this repository nor included in releases or standalone bundles. Setup checks
its fixed size and SHA-256 before it can be loaded.

`make btc-check` reports the selected interpreter, installed model/runtime, and
whether a compatible CUDA device is available. CUDA is used when the runtime
can use it; otherwise inference falls back to CPU. CPU works but is normally
slower.

## Analyze and select the BTC track

Analyze one song or a non-recursive directory explicitly:

```bash
chordflask-analyze --analyzer btc song.mp3
chordflask-analyze --analyzer btc ~/Music/Album
```

In a source checkout, `scripts/chordflask-analyze` is equivalent. BTC is
integrated as the separate `btc` chord track while the existing Chordino and
rhythm tracks remain available. Open the song and select BTC in the chord-track
selector to compare it with Chordino or Edited data.

In a source/virtualenv installation, desktop ChordFlask can also offer
**Prepare: BTC** for the currently loaded song when this runtime is complete.
The action invokes the same installed one-file analyzer helper in the
background and refreshes the selector afterward. Directory analysis remains a
CLI workflow. BTC generation stays excluded from the standalone, which can
still read an existing `btc` track.

Repeat runs reuse the existing BTC result. Use `--replace` only to regenerate
that selected analyzer's track:

```bash
chordflask-analyze --analyzer btc --replace song.mp3
```

Exports and lyrics generation can select it by track ID:

```bash
chordflask-export --chord-track btc song.mp3
chordflask-genlyrics --track btc song.mp3
```

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

The runtime is separate from the core ChordFlask and Demucs environments. A
working core installation does not imply that BTC's PyTorch/CUDA stack is
installed, and a BTC setup problem does not disable Chordino. See
[platform and runtime compatibility](../../docs/COMPATIBILITY.md#optional-btc-runtime)
for the relationship between these matrices.

The maintainer manually verified torch 2.10.0+cu128 on Ubuntu/Xubuntu 26.04,
Python 3.14, and an RTX 5070 Laptop: CUDA 12.8 was available, all 221 checkpoint
state keys matched, `load_state_dict` succeeded, and a CUDA forward pass produced
encoder shape `(1, 108, 128)` and prediction shape `(1, 108)`. This is BTC runtime
validation, not full application or standalone acceptance across the matrix.

## Availability and limitations

- BTC produces chord labels only; it uses ChordFlask's existing rhythm-track
  contracts for display and export.
- Recognition remains automatic and approximate. A different model can produce
  different errors, vocabulary choices, or boundaries; BTC is not an
  authoritative transcription.
- GPU use depends on the installed NVIDIA driver and PyTorch wheel. Automatic
  CPU fallback is expected when CUDA is unavailable.
- Model download is a one-time external network operation and requires the
  explicit weights acknowledgement.
- BTC generation is source-installation only and is not part of the standalone
  bundle. A standalone can read an already stored compatible `btc` track but
  cannot install the runtime or run inference.

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
