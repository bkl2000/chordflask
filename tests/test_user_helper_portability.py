"""Portability contract for the user-facing helper scripts.

``scripts/chordflask``, ``scripts/chordflask-analyze``,
``scripts/chordflask-demucs``, ``scripts/chordflask-export``, and
``scripts/chordflask-maintain`` must work when copied or symlinked to an
arbitrary location and invoked from any current working directory. They resolve
the repository root through the ``${VENV_DIR}/.chordflask-root`` marker written
by setup, never through their own filesystem location.
"""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]

HELPERS = {
    "chordflask": "ChordFlask chord analyzer web app",
    "chordflask-analyze": "chordflask-analyze",
    "chordflask-export": "chordflask-export",
    "chordflask-maintain": "chordflask-maintain",
    "chordflask-demucs": "chordflask-demucs",
}


@pytest.fixture()
def portable_home(tmp_path):
    """Temp HOME with a fake venv whose python is the test interpreter."""
    home = tmp_path / "home"
    venv_dir = home / ".venvs" / "chordflask"
    (venv_dir / "bin").mkdir(parents=True)
    (venv_dir / "bin" / "python").symlink_to(sys.executable)
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
    return home, env


def _write_marker(home, root):
    marker = home / ".venvs" / "chordflask" / ".chordflask-root"
    marker.write_text(f"{root}\n", encoding="utf-8")


def _run_args(target, args, cwd, env):
    return subprocess.run(
        [str(target), *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
    )


def _run(target, cwd, env):
    return _run_args(target, ["--help"], cwd, env)


def test_setup_writes_absolute_repo_root_marker():
    text = (REPO_ROOT / "scripts" / "setup_venv.sh").read_text(encoding="utf-8")
    assert ".chordflask-root" in text
    assert "${ROOT_DIR}" in text


@pytest.mark.parametrize("name,prog", sorted(HELPERS.items()))
def test_copied_helper_runs_from_unrelated_cwd(tmp_path, portable_home, name, prog):
    home, env = portable_home
    _write_marker(home, REPO_ROOT)
    bin_dir = home / "bin"
    bin_dir.mkdir()
    target = bin_dir / name
    shutil.copy(REPO_ROOT / "scripts" / name, target)
    os.chmod(target, target.stat().st_mode | stat.S_IXUSR)
    assert target.stat().st_mode & stat.S_IXUSR
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    result = _run(target, cwd, env)
    assert result.returncode == 0, result.stderr
    assert prog in result.stdout


@pytest.mark.parametrize("name,prog", sorted(HELPERS.items()))
def test_symlinked_helper_runs_from_unrelated_cwd(tmp_path, portable_home, name, prog):
    home, env = portable_home
    _write_marker(home, REPO_ROOT)
    bin_dir = home / "bin"
    bin_dir.mkdir()
    target = bin_dir / name
    target.symlink_to(REPO_ROOT / "scripts" / name)
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    result = _run(target, cwd, env)
    assert result.returncode == 0, result.stderr
    assert prog in result.stdout


def test_missing_marker_fails_clearly(tmp_path, portable_home):
    home, env = portable_home
    bin_dir = home / "bin"
    bin_dir.mkdir()
    target = bin_dir / "chordflask-analyze"
    shutil.copy(REPO_ROOT / "scripts" / "chordflask-analyze", target)
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    result = _run(target, cwd, env)
    assert result.returncode == 1
    assert ".chordflask-root" in result.stderr
    assert "make setup" in result.stderr


def test_stale_marker_fails_clearly(tmp_path, portable_home):
    home, env = portable_home
    _write_marker(home, tmp_path / "moved-checkout")
    bin_dir = home / "bin"
    bin_dir.mkdir()
    target = bin_dir / "chordflask-analyze"
    shutil.copy(REPO_ROOT / "scripts" / "chordflask-analyze", target)
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    result = _run(target, cwd, env)
    assert result.returncode == 1
    assert "rerun 'make setup'" in result.stderr


def test_invalid_marker_without_command_target_fails_clearly(tmp_path, portable_home):
    home, env = portable_home
    wrong_root = tmp_path / "wrong-root"
    wrong_root.mkdir()
    _write_marker(home, wrong_root)
    bin_dir = home / "bin"
    bin_dir.mkdir()
    target = bin_dir / "chordflask-analyze"
    shutil.copy(REPO_ROOT / "scripts" / "chordflask-analyze", target)
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    result = _run(target, cwd, env)
    assert result.returncode == 1
    assert "rerun 'make setup'" in result.stderr


def test_helpers_do_not_infer_root_from_own_location():
    for name in HELPERS:
        text = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "BASH_SOURCE" not in text, name
        assert "SCRIPT_DIR" not in text, name


def test_helpers_preserve_caller_cwd():
    for name in HELPERS:
        text = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert 'cd "${ROOT_DIR}"' not in text, name


RELATIVE_ARG_CASES = {
    "chordflask-analyze": (
        ["--dry-run", "music"],
        ["song.mp3", "TODO"],
    ),
    "chordflask-export": (
        ["empty"],
        ["Done: 0 files"],
    ),
    "chordflask-maintain": (
        ["stems", "report", "music"],
        ["no Demucs stem storage"],
    ),
    "chordflask-demucs": (
        ["empty"],
        ["files:     0"],
    ),
}


@pytest.mark.parametrize("name,case", sorted(RELATIVE_ARG_CASES.items()))
def test_relative_argument_resolves_against_caller_cwd(
    tmp_path, portable_home, name, case
):
    """A relative argument must resolve against the caller cwd, not the repo.

    Each copied helper is invoked from an unrelated cwd with a relative path
    that exists only there. The old ``cd "${ROOT_DIR}"`` wrappers resolved the
    argument against the checkout and failed with a missing-path error.
    """
    args, expected = case
    home, env = portable_home
    _write_marker(home, REPO_ROOT)
    bin_dir = home / "bin"
    bin_dir.mkdir()
    target = bin_dir / name
    shutil.copy(REPO_ROOT / "scripts" / name, target)
    os.chmod(target, target.stat().st_mode | stat.S_IXUSR)

    cwd = tmp_path / "elsewhere"
    (cwd / "music").mkdir(parents=True)
    (cwd / "music" / "song.mp3").write_bytes(b"")
    (cwd / "empty").mkdir()

    result = _run_args(target, args, cwd, env)
    assert result.returncode == 0, result.stderr
    for fragment in expected:
        assert fragment in result.stdout, result.stdout


def test_no_hardcoded_user_home_paths_in_helper_sources():
    files = [REPO_ROOT / "scripts" / name for name in HELPERS]
    files.append(REPO_ROOT / "scripts" / "setup_venv.sh")
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "/home/" not in text, path
        assert "bkl" not in text.lower(), path