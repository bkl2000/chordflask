"""BTC-ISMIR19 feature pipeline (modernized).

Reproduces the BTC constant-Q feature: mono 22.05 kHz audio -> 144-bin CQT
(24 bins per octave, hop 2048) -> log magnitude -> z-score using the checkpoint
``mean``/``std``.

Frames are uniformly spaced by ``FRAME_SECONDS`` (``2048 / 22050``). The
original training loader chunked audio into 10-second windows purely to bound
memory; the whole-signal CQT used here yields the same per-frame feature values
with truly uniform timing, which is exactly what the binding timestamp rule
(``frame_index * FRAME_SECONDS``) requires.
"""

from __future__ import annotations

from pathlib import Path

SAMPLE_RATE = 22050
HOP_LENGTH = 2048
N_BINS = 144
BINS_PER_OCTAVE = 24
TIMESTEP = 108
FRAME_SECONDS = HOP_LENGTH / SAMPLE_RATE  # 2048 / 22050


def compute_features(audio_path, mean, std, *, timestep: int = TIMESTEP):
    """Return a ``(frames, 144)`` z-scored CQT feature padded to ``timestep``.

    ``mean`` and ``std`` come from the checkpoint and are broadcast per feature
    bin. NumPy and Librosa stay lazy so importing this module never loads the
    acoustic stack.
    """
    import numpy as np
    import librosa

    samples, sample_rate = librosa.load(str(Path(audio_path)), sr=SAMPLE_RATE, mono=True)
    cqt = librosa.cqt(
        samples,
        sr=sample_rate,
        n_bins=N_BINS,
        bins_per_octave=BINS_PER_OCTAVE,
        hop_length=HOP_LENGTH,
    )
    feature = np.log(np.abs(cqt) + 1e-6)  # [144, frames]
    feature = feature.T  # [frames, 144]
    feature = (feature - np.asarray(mean)) / np.asarray(std)
    padding = (timestep - (feature.shape[0] % timestep)) % timestep
    if padding:
        feature = np.pad(feature, ((0, padding), (0, 0)), mode="constant", constant_values=0)
    return feature
