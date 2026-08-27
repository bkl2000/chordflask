"""Portability contract for the user-facing helper scripts.

``scripts/chordflask``, ``scripts/chordflask-analyze``,
``scripts/chordflask-demucs``, ``scripts/chordflask-export``, and
``scripts/chordflask-maintain`` must work when copied or symlinked to an
arbitrary location and invoked from any current working directory. They resolve
the configured/default project venv and execute the command installed there,
never inferring the repository root from their own filesystem location.
"""

import os
import shlex
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

COMMAND_MODULES = {
    "chordflask": "chordflask",
    "chordflask-analyze": "chordflask.helpers.analyze_cli",
    "chordflask-export": "chordflask.helpers.export_cli",
    "chordflask-maintain": "chordflask_maintain.cli",
    "chordflask-demucs": "chordflask_demucs.cli",
}


def _write_forwarding_venv(venv_dir):
    """Create command stubs that preserve installed-module behavior."""
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True)
    python = bin_dir / "python"
    python.write_text(
        f"#!/bin/sh\nexec {shlex.quote(sys.executable)} \"$@\"\n",
        encoding="utf-8",
    )
    python.chmod(python.stat().st_mode | stat.S_IXUSR)
    for command, module in COMMAND_MODULES.items():
        target = bin_dir / command
        target.write_text(
            f"#!/bin/sh\nexec {shlex.quote(sys.executable)} -m {module} \"$@\"\n",
            encoding="utf-8",
        )
        target.chmod(target.stat().st_mode | stat.S_IXUSR)


@pytest.fixture()
def portable_home(tmp_path):
    """Temp HOME with installed commands forwarded to the test interpreter."""
    home = tmp_path / "home"
    venv_dir = home / ".venvs" / "chordflask"
    _write_forwarding_venv(venv_dir)
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
    bin_dir = home / "bin"
    bin_dir.mkdir()
    target = bin_dir / name
    target.symlink_to(REPO_ROOT / "scripts" / name)
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    result = _run(target, cwd, env)
    assert result.returncode == 0, result.stderr
    assert prog in result.stdout


def test_missing_marker_is_not_required(tmp_path, portable_home):
    home, env = portable_home
    bin_dir = home / "bin"
    bin_dir.mkdir()
    target = bin_dir / "chordflask-analyze"
    shutil.copy(REPO_ROOT / "scripts" / "chordflask-analyze", target)
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    result = _run(target, cwd, env)
    assert result.returncode == 0, result.stderr
    assert "chordflask-analyze" in result.stdout


def test_stale_marker_is_ignored(tmp_path, portable_home):
    home, env = portable_home
    _write_marker(home, tmp_path / "moved-checkout")
    bin_dir = home / "bin"
    bin_dir.mkdir()
    target = bin_dir / "chordflask-analyze"
    shutil.copy(REPO_ROOT / "scripts" / "chordflask-analyze", target)
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    result = _run(target, cwd, env)
    assert result.returncode == 0, result.stderr
    assert "chordflask-analyze" in result.stdout


def test_missing_installed_command_fails_clearly(tmp_path, portable_home):
    home, env = portable_home
    (home / ".venvs" / "chordflask" / "bin" / "chordflask-analyze").unlink()
    bin_dir = home / "bin"
    bin_dir.mkdir()
    target = bin_dir / "chordflask-analyze"
    shutil.copy(REPO_ROOT / "scripts" / "chordflask-analyze", target)
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    result = _run(target, cwd, env)
    assert result.returncode == 1
    assert "Installed ChordFlask command not found" in result.stderr
    assert "make setup" in result.stderr


def test_helpers_do_not_infer_root_from_own_location():
    for name in HELPERS:
        text = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "BASH_SOURCE" not in text, name
        assert "SCRIPT_DIR" not in text, name


def test_helpers_preserve_caller_cwd():
    for name in HELPERS:
        text = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert 'cd "${ROOT_DIR}"' not in text, name


def test_helpers_do_not_construct_pythonpath_or_read_root_marker():
    for name in HELPERS:
        text = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "PYTHONPATH" not in text, name
        assert ".chordflask-root" not in text, name


def test_chordflask_venv_override_selects_installed_command(tmp_path, portable_home):
    _, env = portable_home
    alternate_venv = tmp_path / "alternate-venv"
    _write_forwarding_venv(alternate_venv)
    env["CHORDFLASK_VENV"] = str(alternate_venv)
    result = _run(REPO_ROOT / "scripts" / "chordflask-analyze", tmp_path, env)
    assert result.returncode == 0, result.stderr
    assert "chordflask-analyze" in result.stdout


def test_legacy_venv_override_selects_installed_command(tmp_path, portable_home):
    _, env = portable_home
    alternate_venv = tmp_path / "legacy-override-venv"
    _write_forwarding_venv(alternate_venv)
    env["CHORDIFIER_VENV"] = str(alternate_venv)
    result = _run(REPO_ROOT / "scripts" / "chordflask-analyze", tmp_path, env)
    assert result.returncode == 0, result.stderr
    assert "chordflask-analyze" in result.stdout


def test_legacy_default_venv_fallback_selects_installed_command(tmp_path):
    home = tmp_path / "home"
    _write_forwarding_venv(home / ".venvs" / "chordifier")
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
    result = _run(REPO_ROOT / "scripts" / "chordflask-analyze", tmp_path, env)
    assert result.returncode == 0, result.stderr
    assert "chordflask-analyze" in result.stdout


def test_chordflask_python_override_uses_package_module(tmp_path, portable_home):
    _, env = portable_home
    env["CHORDFLASK_PYTHON"] = sys.executable
    result = _run(REPO_ROOT / "scripts" / "chordflask-analyze", tmp_path, env)
    assert result.returncode == 0, result.stderr
    assert "chordflask-analyze" in result.stdout


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
