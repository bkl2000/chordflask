# BTC-ISMIR19 runtime

Isolated inference runtime for the BTC-ISMIR19 large-vocabulary chord model.
It runs only through the `btc-predict-raw` subprocess in the dedicated BTC venv;
it never touches the ChordFlask analyzer or the normal ChordFlask virtual
environment. It is only used when the user runs `make setup-btc` and then
`chordflask-analyze --analyzer btc`.

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
