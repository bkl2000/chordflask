import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHORDFLASK = REPO_ROOT / "flask" / "chordflask.py"


def test_help_documents_automatic_worker_opt_out():
    result = subprocess.run(
        [sys.executable, str(CHORDFLASK), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--worker" in result.stdout
    assert "--no-worker" in result.stdout
