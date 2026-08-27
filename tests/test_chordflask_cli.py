import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_help_documents_automatic_worker_opt_out():
    result = subprocess.run(
        [sys.executable, "-m", "chordflask", "--help"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--worker" in result.stdout
    assert "--no-worker" in result.stdout


def test_frozen_version_is_read_beside_executable(tmp_path, monkeypatch):
    import chordflask.app as chordflask

    executable = tmp_path / "chordflask"
    executable.touch()
    (tmp_path / "VERSION").write_text("0.5.0 build-id\n")
    monkeypatch.setattr(chordflask.sys, "frozen", True, raising=False)
    monkeypatch.setattr(chordflask.sys, "executable", str(executable))

    assert chordflask._load_version() == "0.5.0 build-id"
