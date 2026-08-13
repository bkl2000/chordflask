import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FLASK_DIR = REPO_ROOT / "flask"

if str(FLASK_DIR) not in sys.path:
    sys.path.insert(0, str(FLASK_DIR))

import chordutils


def test_process_pool_is_created_lazily():
    assert chordutils._executor is None


def test_unknown_reference_chord_remains_visible_when_transposed():
    assert chordutils.transpose_single_chord("X", 0, True) == "X"
    assert chordutils.transpose_single_chord("x", 5, False) == "X"
