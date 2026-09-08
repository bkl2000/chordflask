"""Exercise BTC setup with fake interpreters/installers and no downloads."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/setup-btc.sh"


@pytest.fixture
def btc_setup(tmp_path):
    def run(version, *, existing=False, torch_version="2.6.0+cu124"):
        log = tmp_path / "calls"
        venv = tmp_path / "venv"
        interpreter = tmp_path / "python"
        interpreter.write_text(
            f"#!{sys.executable}\n"
            "import os, pathlib, sys\n"
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
            f"    (target / 'pip').symlink_to({str(tmp_path / 'pip')!r})\n"
            "elif '__version__' in sys.argv[-1]:\n"
            f"    print({torch_version!r})\n"
        )
        interpreter.chmod(0o755)
        pip = tmp_path / "pip"
        pip.write_text(
            f"#!{sys.executable}\n"
            "import sys\n"
            f"with open({str(log)!r}, 'a') as stream:\n"
            "    stream.write('pip ' + repr(sys.argv[1:]) + '\\n')\n"
        )
        pip.chmod(0o755)
        if existing:
            (venv / "bin").mkdir(parents=True)
            (venv / "bin/python").symlink_to(interpreter)
            (venv / "bin/pip").symlink_to(pip)
        env = dict(os.environ, CHORDFLASK_BTC_VENV=str(venv),
                   CHORDFLASK_BTC_DIR=str(tmp_path / "missing-model"),
                   CHORDFLASK_BTC_PYTHON=str(interpreter) if not existing else "/unused-python")
        env.pop("BTC_ACKNOWLEDGE_WEIGHTS", None)
        result = subprocess.run(["bash", str(SCRIPT)], env=env, text=True,
                                capture_output=True, timeout=10)
        return result, log.read_text(), venv
    return run


@pytest.mark.parametrize("version", [(3, 12), (3, 13), (3, 14)])
@pytest.mark.parametrize("existing", [False, True])
def test_supported_python_installs_new_torch(btc_setup, version, existing):
    result, calls, venv = btc_setup(version, existing=existing)
    # Stop at the unchanged provenance gate, before any checkpoint download.
    assert result.returncode == 1
    assert "without an explicit opt-in" in result.stderr
    assert "'torch==2.10.0', '--index-url', 'https://download.pytorch.org/whl/cu128'" in calls
    assert ("'-m', 'venv'" in calls) == (not existing)
    assert (venv / "bin/python").exists()
    assert "'numpy', 'librosa'" not in calls


@pytest.mark.parametrize("version", [(2, 7), (3, 11), (3, 15), (4, 0)])
@pytest.mark.parametrize("existing", [False, True])
def test_unsupported_python_fails_before_mutation(btc_setup, version, existing):
    result, calls, venv = btc_setup(version, existing=existing)
    assert result.returncode != 0
    assert "BTC requires Python 3.12, 3.13, or 3.14" in result.stderr
    assert f"found {version[0]}.{version[1]}" in result.stderr
    assert "CHORDFLASK_BTC_PYTHON" in result.stderr
    assert "CHORDFLASK_BTC_VENV" in result.stderr
    assert calls == "['-']\n"
    assert venv.exists() == existing


def test_current_torch_is_reused(btc_setup):
    result, calls, _ = btc_setup((3, 14), existing=True, torch_version="2.10.0+cu128")
    assert "PyTorch 2.10.0 already installed" in result.stdout
    assert "pip " not in calls
    assert "without an explicit opt-in" in result.stderr
