"""Check isolated Lyrics setup without installing packages."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "setup-lyrics.sh"
CHECK_SCRIPT = ROOT / "scripts" / "lyrics-check.sh"


@pytest.fixture
def lyrics_setup(tmp_path):
    def run(version, *, existing=False):
        log = tmp_path / "calls"
        venv = tmp_path / "venv"
        interpreter = tmp_path / "python"
        interpreter.write_text(
            f"#!{sys.executable}\n"
            "import pathlib, sys\n"
            f"log = pathlib.Path({str(log)!r})\n"
            "with log.open('a') as stream:\n"
            "    stream.write(repr(sys.argv[1:]) + '\\n')\n"
            "if sys.argv[1:] == ['-']:\n"
            f"    sys.version_info = {version!r}\n"
            "    exec(sys.stdin.read())\n"
            "elif sys.argv[1:3] == ['-m', 'venv']:\n"
            "    target = pathlib.Path(sys.argv[3]) / 'bin'\n"
            "    target.mkdir(parents=True)\n"
            "    (target / 'python').symlink_to(sys.argv[0])\n"
            "elif sys.argv[1:3] == ['-m', 'pip'] and 'install' in sys.argv:\n"
            "    helper = pathlib.Path(sys.argv[0]).parent / 'chordflask-genlyrics'\n"
            "    helper.write_text('#!/bin/sh\\nexit 0\\n')\n"
            "    helper.chmod(0o755)\n"
        )
        interpreter.chmod(0o755)
        if existing:
            (venv / "bin").mkdir(parents=True)
            (venv / "bin/python").symlink_to(interpreter)
        env = dict(
            os.environ,
            CHORDFLASK_LYRICS_VENV=str(venv),
            CHORDFLASK_LYRICS_PYTHON=str(interpreter) if not existing else "/unused-python",
        )
        result = subprocess.run(
            ["bash", str(SCRIPT)], env=env, text=True, capture_output=True, timeout=10
        )
        return result, log.read_text(), venv

    return run


@pytest.mark.parametrize("version", [(3, 10), (3, 12), (3, 14)])
@pytest.mark.parametrize("existing", [False, True])
def test_setup_installs_self_contained_helper(lyrics_setup, version, existing):
    result, calls, venv = lyrics_setup(version, existing=existing)

    assert result.returncode == 0, result.stderr
    assert ("'-m', 'venv'" in calls) == (not existing)
    assert str(ROOT / "requirements-lyrics.txt") in calls
    assert str(ROOT) in calls
    assert "'--no-deps'" in calls
    assert "'uninstall', '--quiet', '--yes', 'tltk', 'pandas', 'requests'" in calls
    assert (venv / "bin" / "chordflask-genlyrics").is_file()


@pytest.mark.parametrize("version", [(3, 9), (3, 15), (4, 0)])
def test_unsupported_python_fails_before_install(lyrics_setup, version):
    result, calls, venv = lyrics_setup(version)

    assert result.returncode != 0
    assert "Lyrics requires Python 3.10 through 3.14" in result.stderr
    assert "CHORDFLASK_LYRICS_PYTHON" in result.stderr
    assert calls == "['-']\n"
    assert not venv.exists()


def test_external_runtime_contains_only_supported_romanization_stack():
    requirements = (ROOT / "requirements-lyrics.txt").read_text(encoding="utf-8")
    check_script = CHECK_SCRIPT.read_text(encoding="utf-8")

    assert "pythainlp[onnx]>=5.3.3,<6" in requirements
    assert "tltk" not in requirements
    assert "pandas" not in requirements
    assert "requests" not in requirements
    assert "import onnxruntime" in check_script
    assert "import pythainlp" in check_script
    assert "tltk" not in check_script
    assert "pandas" not in check_script
    assert "requests" not in check_script
