"""Check isolated Demucs setup without installing packages or models."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/setup-demucs.sh"


@pytest.fixture
def demucs_setup(tmp_path):
    def run(version, *, existing=False):
        log = tmp_path / "calls"
        venv = tmp_path / "venv"
        interpreter = tmp_path / "python"
        interpreter.write_text(
            f"#!{sys.executable}\n"
            "import pathlib, sys\n"
            f"with open({str(log)!r}, 'a') as stream:\n"
            "    stream.write(repr(sys.argv[1:]) + '\\n')\n"
            "if sys.argv[1:] == ['-']:\n"
            f"    sys.version_info = {version!r}\n"
            "    exec(sys.stdin.read())\n"
            "elif sys.argv[1:3] == ['-m', 'venv']:\n"
            "    target = pathlib.Path(sys.argv[3]) / 'bin'\n"
            "    target.mkdir(parents=True)\n"
            "    (target / 'python').symlink_to(sys.argv[0])\n"
            f"    (target / 'pip').symlink_to({str(tmp_path / 'pip')!r})\n"
            "else:\n"
            "    assert sys.argv[1:] in (['-m', 'pip', 'install', '--quiet', '--upgrade', 'pip'],\n"
            "                             ['-m', 'demucs.separate', '--help'])\n"
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
        env = dict(os.environ, CHORDFLASK_DEMUCS_VENV=str(venv),
                   CHORDFLASK_DEMUCS_PYTHON=str(interpreter) if not existing else "/unused-python")
        env.pop("CHORDFLASK_DEMUCS_TORCH_INDEX_URL", None)
        result = subprocess.run(["bash", str(SCRIPT)], env=env, text=True,
                                capture_output=True, timeout=10)
        return result, log.read_text(), venv
    return run


@pytest.mark.parametrize("version", [(3, 12), (3, 13), (3, 14)])
@pytest.mark.parametrize("existing", [False, True])
def test_setup_installs_pins_even_in_existing_venv(demucs_setup, version, existing):
    result, calls, venv = demucs_setup(version, existing=existing)
    assert result.returncode == 0, result.stderr
    assert calls.startswith("['-']\n")
    assert ("'-m', 'venv'" in calls) == (not existing)
    torch_install = "'torch==2.10.0', 'torchaudio==2.10.0', '--index-url', 'https://download.pytorch.org/whl/cu128'"
    requirements_install = f"'--requirement', {str(ROOT / 'chordflask_demucs/requirements.txt')!r}"
    assert torch_install in calls
    assert requirements_install in calls
    assert calls.index(torch_install) < calls.index(requirements_install)
    assert calls.endswith("['-m', 'demucs.separate', '--help']\n")
    assert (venv / "bin/python").exists()


@pytest.mark.parametrize("version", [(2, 7), (3, 11), (3, 15), (4, 0)])
@pytest.mark.parametrize("existing", [False, True])
def test_unsupported_python_fails_before_install(demucs_setup, version, existing):
    result, calls, venv = demucs_setup(version, existing=existing)
    assert result.returncode != 0
    assert "Demucs requires Python 3.12, 3.13, or 3.14" in result.stderr
    assert f"found {version[0]}.{version[1]}" in result.stderr
    assert "CHORDFLASK_DEMUCS_PYTHON" in result.stderr
    assert "CHORDFLASK_DEMUCS_VENV" in result.stderr
    assert calls == "['-']\n"
    assert venv.exists() == existing


def test_runtime_requirements_include_audio_save_backend():
    requirements = (ROOT / "chordflask_demucs/requirements.txt").read_text()
    assert {line for line in requirements.splitlines() if line and not line.startswith('#')} == {
        "demucs==4.0.1", "torch==2.10.0", "torchaudio==2.10.0", "torchcodec==0.10.0",
    }
