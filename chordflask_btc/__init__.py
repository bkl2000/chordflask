"""Optional BTC-ISMIR19 chord-track runtime (public, torch-free orchestration).

This package provides the optional BTC analyzer: it decodes audio, invokes the
isolated BTC inference runtime (``~/.venvs/chordflask-btc/bin/btc-predict-raw``)
as a subprocess, normalizes labels, and writes a ``btc`` chord track into an
existing Schema-v3 analysis file.

It never imports torch, and it is only reachable when the user has installed the
BTC runtime with ``make setup-btc``. The model code under :mod:`chordflask_btc.model`
is loaded only by the ``btc-predict-raw`` subprocess in the dedicated BTC venv.
"""

from __future__ import annotations

__version__ = "0.8.0"
