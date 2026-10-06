"""Check isolated Lyrics setup without installing packages."""

import os
from pathlib import Path
import json
import subprocess
import sys

import pytest
from chordflask_lyrics.freshness import MARKER_PATH, fingerprint


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "setup-lyrics.sh"
CHECK_SCRIPT = ROOT / "scripts" / "lyrics-check.sh"


@pytest.fixture
def lyrics_setup(tmp_path):
    def run(version, *, existing=False, fail_install=False, fail_help=False, fail_identity=False):
        log = tmp_path / "calls"
        venv = tmp_path / "venv"
        interpreter = tmp_path / "python"
        interpreter.write_text(
            f"#!{sys.executable}\n"
            "import pathlib, sys, runpy, shutil\n"
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
            "elif sys.argv[1] == '-I':\n"
            "    namespace = runpy.run_path(sys.argv[2])\n"
            "    action = sys.argv[3]\n"
            "    if action == 'fingerprint':\n"
            "        print(namespace['fingerprint'](pathlib.Path(sys.argv[5])))\n"
            "    elif action == 'record':\n"
            "        runtime = pathlib.Path(sys.argv[7])\n"
            "        namespace['record_identity'].__globals__['installed_fingerprint'] = lambda: namespace['fingerprint'](runtime / 'snapshot')\n"
            "        namespace['record_identity'](runtime, pathlib.Path(sys.argv[5]), sys.argv[9])\n"
            "elif sys.argv[1:3] == ['-m', 'pip'] and 'install' in sys.argv:\n"
            f"    if '--no-deps' in sys.argv and {fail_install!r}: sys.exit(1)\n"
            "    helper = pathlib.Path(sys.argv[0]).parent / 'chordflask-genlyrics'\n"
            f"    helper.write_text('#!/bin/sh\\nexit {int(fail_help)}\\n')\n"
            "    helper.chmod(0o755)\n"
            "    if '--no-deps' in sys.argv:\n"
            "        snapshot = helper.parent.parent / 'snapshot'\n"
            "        for package in ('chordflask', 'chordflask_base', 'chordflask_lyrics'):\n"
            "            shutil.copytree(pathlib.Path(sys.argv[-1]) / package, snapshot / package, dirs_exist_ok=True)\n"
            f"        if {fail_identity!r}: (snapshot / 'chordflask_lyrics/align.py').write_text('stale installed code')\n"
        )
        interpreter.chmod(0o755)
        if existing:
            (venv / "bin").mkdir(parents=True, exist_ok=True)
            if not (venv / "bin/python").exists():
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
    marker = json.loads((venv / MARKER_PATH).read_text())
    assert marker["sha256"] == fingerprint(ROOT)


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


@pytest.mark.parametrize("failure", ["fail_install", "fail_help", "fail_identity"])
def test_failed_setup_does_not_refresh_identity(lyrics_setup, tmp_path, failure):
    marker = tmp_path / "venv" / MARKER_PATH
    marker.parent.mkdir(parents=True)
    marker.write_text('{"format": 1, "sha256": "old-identity"}\n')
    original = marker.read_bytes()
    result, _, _ = lyrics_setup((3, 12), existing=True, **{failure: True})
    assert result.returncode != 0
    assert marker.read_bytes() == original
    assert list(marker.parent.glob(".source-identity-*")) == []


def test_successful_setup_replaces_old_identity_and_rerun_is_safe(lyrics_setup, tmp_path):
    marker = tmp_path / "venv" / MARKER_PATH
    marker.parent.mkdir(parents=True)
    marker.write_text('{"format": 1, "sha256": "old-identity"}\n')
    result, _, _ = lyrics_setup((3, 12), existing=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(marker.read_text())["sha256"] == fingerprint(ROOT)
    original = marker.read_bytes()
    result, _, _ = lyrics_setup((3, 12), existing=True)
    assert result.returncode == 0, result.stderr
    assert marker.read_bytes() == original


def test_failed_first_install_leaves_no_current_marker(lyrics_setup):
    result, _, venv = lyrics_setup((3, 12), fail_install=True)
    assert result.returncode != 0
    assert not (venv / MARKER_PATH).exists()
