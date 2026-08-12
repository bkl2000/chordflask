import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = REPO_ROOT / "scripts" / "setup_venv.sh"
VENDOR_DIR = REPO_ROOT / "vendor" / "vamp" / "linux-x86_64"
VENDORED_PLUGINS_AVAILABLE = all(
    (VENDOR_DIR / name).is_file()
    for name in ("nnls-chroma.so", "qm-vamp-plugins.so")
)


def _mock_dpkg(tmp_path, status="install ok installed", missing=()):
    """Create a mock dpkg-query with optional selectively missing packages."""
    mock_dir = tmp_path / "mock-bin"
    mock_dir.mkdir(exist_ok=True)
    mock_bin = Path(mock_dir) / "dpkg-query"
    missing_words = " ".join(missing)
    mock_bin.write_text(f"""#!/bin/bash
package="${{@: -1}}"
if [[ " {missing_words} " == *" $package "* ]]; then
    echo 'deinstall ok config-files'
else
    echo '{status}'
fi
""")
    mock_bin.chmod(0o755)
    return str(mock_dir)


def _run_setup(extra_env=None, extra_args=()):
    env = {"HOME": str(Path.home()), "PATH": "/usr/bin:/bin"}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(SETUP_SCRIPT), *extra_args],
        capture_output=True,
        text=True,
        env=env,
    )


# ── prerequisite check ────────────────────────────────────────────


def test_missing_prerequisites_exit_status_2(tmp_path):
    mock_dir = _mock_dpkg(tmp_path, "deinstall ok config-files")
    env = {
        "PATH": f"{mock_dir}:/usr/bin:/bin",
        "CHORDIFIER_VENV": "/tmp/chordflask-test-venv-NEVER",
    }
    cp = _run_setup(extra_env=env)
    assert cp.returncode == 2
    assert "Setup paused: required system packages are missing." in cp.stderr
    assert "sudo apt update" in cp.stderr
    assert "sudo apt install --no-install-recommends" in cp.stderr
    assert "python3 " in cp.stderr or "python3\n" in cp.stderr
    assert "ffmpeg" in cp.stderr
    assert "No virtual environment was created or modified." in cp.stderr


def test_missing_prerequisites_lists_only_requested_packages(tmp_path):
    mock_dir = _mock_dpkg(tmp_path, missing=("python3-dev", "ffmpeg"))
    env = {
        "PATH": f"{mock_dir}:/usr/bin:/bin",
        "CHORDIFIER_VENV": "/tmp/chordflask-test-venv-NEVER",
    }
    cp = _run_setup(extra_env=env)
    assert cp.returncode == 2
    assert (
        "sudo apt install --no-install-recommends python3-dev ffmpeg"
        in cp.stderr
    )
    assert "python3-venv" not in cp.stderr
    assert "vamp-plugin-sdk" not in cp.stderr
    assert "libavcodec-dev" not in cp.stderr
    assert "libavdevice-dev" not in cp.stderr


def test_missing_prerequisites_continuation_preserves_venv_dir_override(tmp_path):
    mock_dir = _mock_dpkg(tmp_path, "deinstall ok config-files")
    env = {
        "PATH": f"{mock_dir}:/usr/bin:/bin",
        "CHORDIFIER_VENV": "/tmp/my-custom-venv",
    }
    cp = _run_setup(extra_env=env)
    assert cp.returncode == 2
    assert "VENV_DIR=/tmp/my-custom-venv" in cp.stderr


def test_missing_prerequisites_continuation_preserves_python_bin_override(tmp_path):
    mock_dir = _mock_dpkg(tmp_path, "deinstall ok config-files")
    env = {
        "PATH": f"{mock_dir}:/usr/bin:/bin",
        "CHORDIFIER_PYTHON": sys.executable,
        "CHORDIFIER_VENV": "/tmp/chordflask-test-venv-NEVER",
    }
    cp = _run_setup(extra_env=env)
    assert cp.returncode == 2
    assert "PYTHON_BIN=" in cp.stderr


def test_missing_prerequisites_continuation_preserves_optional_flag(tmp_path):
    mock_dir = _mock_dpkg(tmp_path, "deinstall ok config-files")
    cp = _run_setup(
        extra_env={
            "PATH": f"{mock_dir}:/usr/bin:/bin",
            "CHORDIFIER_OPTIONAL": "1",
            "CHORDIFIER_VENV": str(tmp_path / "venv"),
        }
    )
    assert cp.returncode == 2
    assert "CHORDIFIER_OPTIONAL=1 make setup" in cp.stderr


def test_missing_prerequisites_default_venv_prints_clean_continuation(tmp_path):
    mock_dir = _mock_dpkg(tmp_path, "deinstall ok config-files")
    env = {
        "PATH": f"{mock_dir}:/usr/bin:/bin",
        "CHORDIFIER_VENV": str(Path.home() / ".venvs/chordifier"),
    }
    cp = _run_setup(extra_env=env)
    assert cp.returncode == 2
    assert "VENV_DIR=" not in cp.stderr


# ── preflight before venv operations ──────────────────────────────


def test_prereq_check_runs_before_recreate(tmp_path):
    mock_dir = _mock_dpkg(tmp_path, "deinstall ok config-files")
    venv_dir = tmp_path / "recreate-venv"
    venv_dir.mkdir()
    marker = venv_dir / "preserve-me"
    marker.write_text("unchanged")
    env = {
        "PATH": f"{mock_dir}:/usr/bin:/bin",
        "CHORDIFIER_VENV": str(venv_dir),
    }
    cp = _run_setup(extra_env=env, extra_args=("--recreate",))
    assert cp.returncode == 2
    assert marker.read_text() == "unchanged"


def test_prereq_check_runs_before_create(tmp_path):
    mock_dir = _mock_dpkg(tmp_path, "deinstall ok config-files")
    venv_dir = tmp_path / "new-venv"
    env = {
        "PATH": f"{mock_dir}:/usr/bin:/bin",
        "CHORDIFIER_VENV": str(venv_dir),
    }
    cp = _run_setup(extra_env=env)
    assert cp.returncode == 2
    assert not venv_dir.exists()


def test_setup_never_executes_package_manager_commands(tmp_path):
    mock_dir = Path(_mock_dpkg(tmp_path, "deinstall ok config-files"))
    command_log = tmp_path / "package-manager.log"
    for name in ("sudo", "apt", "apt-get"):
        command = mock_dir / name
        command.write_text(
            f"#!/bin/bash\necho {name} >> {command_log}\nexit 99\n"
        )
        command.chmod(0o755)
    cp = _run_setup(
        extra_env={
            "PATH": f"{mock_dir}:/usr/bin:/bin",
            "CHORDIFIER_VENV": str(tmp_path / "venv"),
        }
    )
    assert cp.returncode == 2
    assert not command_log.exists()


def _healthy_mock_venv(tmp_path):
    venv_dir = tmp_path / "venv"
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True)
    call_log = tmp_path / "python-calls.log"
    mock_python = bin_dir / "python3"
    mock_python.write_text(f"""#!/bin/bash
echo "$*" >> "{call_log}"
if [[ "$*" == *"version_info.major"* ]]; then
    echo 3.12
fi
if [[ -n "${{MOCK_FAIL_MATCH:-}}" && "$*" == *"$MOCK_FAIL_MATCH"* ]]; then
    exit "${{MOCK_FAIL_STATUS:-17}}"
fi
exit 0
""")
    mock_python.chmod(0o755)
    (bin_dir / "activate").write_text(f'export PATH="{bin_dir}:$PATH"\n')
    return venv_dir, call_log


def test_damaged_existing_venv_stops_with_recreate_instruction(tmp_path):
    mock_dir = _mock_dpkg(tmp_path)
    venv_dir = tmp_path / "broken-venv"
    venv_dir.mkdir()
    cp = _run_setup(
        extra_env={
            "PATH": f"{mock_dir}:/usr/bin:/bin",
            "CHORDIFIER_VENV": str(venv_dir),
        }
    )
    assert cp.returncode == 1
    assert "Existing virtual environment is incomplete" in cp.stderr
    assert "make setup-recreate" in cp.stderr


def test_healthy_venv_is_reused_and_verifies_available_runtime(tmp_path):
    mock_dir = _mock_dpkg(tmp_path)
    venv_dir, call_log = _healthy_mock_venv(tmp_path)
    marker = venv_dir / "preserved"
    marker.write_text("yes")
    cp = _run_setup(
        extra_env={
            "PATH": f"{mock_dir}:/usr/bin:/bin",
            "CHORDIFIER_VENV": str(venv_dir),
        }
    )
    assert cp.returncode == 0, cp.stderr
    calls = call_log.read_text()
    assert "-m venv" not in calls
    assert "import analysis_queue" in calls
    assert ("vamp.list_plugins" in calls) is VENDORED_PLUGINS_AVAILABLE
    assert marker.read_text() == "yes"
    assert "make check" in cp.stdout
    assert "make run" in cp.stdout


def test_pip_failure_reports_command_and_retry(tmp_path):
    mock_dir = _mock_dpkg(tmp_path)
    venv_dir, _ = _healthy_mock_venv(tmp_path)
    cp = _run_setup(
        extra_env={
            "PATH": f"{mock_dir}:/usr/bin:/bin",
            "CHORDIFIER_VENV": str(venv_dir),
            "MOCK_FAIL_MATCH": "--no-build-isolation vamp",
            "MOCK_FAIL_STATUS": "23",
        }
    )
    assert cp.returncode == 23
    assert "Setup failed: the Python Vamp host could not be installed." in cp.stderr
    assert "Failed command:" in cp.stderr
    assert "--no-build-isolation vamp" in cp.stderr
    assert "make setup" in cp.stderr


def test_import_verification_failure_is_actionable(tmp_path):
    mock_dir = _mock_dpkg(tmp_path)
    venv_dir, _ = _healthy_mock_venv(tmp_path)
    cp = _run_setup(
        extra_env={
            "PATH": f"{mock_dir}:/usr/bin:/bin",
            "CHORDIFIER_VENV": str(venv_dir),
            "MOCK_FAIL_MATCH": "import analysis_queue",
        }
    )
    assert cp.returncode == 17
    assert "required application imports could not be verified" in cp.stderr
    assert "make setup" in cp.stderr


def test_vamp_discovery_failure_is_actionable(tmp_path):
    if not VENDORED_PLUGINS_AVAILABLE:
        pytest.skip("Private vendored Vamp plugin binaries are not present")
    mock_dir = _mock_dpkg(tmp_path)
    venv_dir, _ = _healthy_mock_venv(tmp_path)
    cp = _run_setup(
        extra_env={
            "PATH": f"{mock_dir}:/usr/bin:/bin",
            "CHORDIFIER_VENV": str(venv_dir),
            "MOCK_FAIL_MATCH": "vamp.list_plugins",
        }
    )
    assert cp.returncode == 17
    assert "vendored Vamp plugins could not be discovered" in cp.stderr
    assert "make setup" in cp.stderr


def test_full_setup_installs_and_verifies_developer_tools(tmp_path):
    mock_dir = _mock_dpkg(tmp_path)
    venv_dir, call_log = _healthy_mock_venv(tmp_path)
    cp = _run_setup(
        extra_env={
            "PATH": f"{mock_dir}:/usr/bin:/bin",
            "CHORDIFIER_VENV": str(venv_dir),
        },
        extra_args=("--dev",),
    )
    assert cp.returncode == 0, cp.stderr
    calls = call_log.read_text()
    assert f"-r {REPO_ROOT / 'requirements-dev.txt'}" in calls
    assert f"-r {REPO_ROOT / 'requirements-build.txt'}" in calls
    assert "import PyInstaller; import mido; import pytest; import ruff" in calls
    assert f"-c {REPO_ROOT / 'constraints-python312.txt'}" in calls


def test_optional_environment_flag_installs_and_verifies_playback_tools(tmp_path):
    mock_dir = _mock_dpkg(tmp_path)
    venv_dir, call_log = _healthy_mock_venv(tmp_path)
    cp = _run_setup(
        extra_env={
            "PATH": f"{mock_dir}:/usr/bin:/bin",
            "CHORDIFIER_VENV": str(venv_dir),
            "CHORDIFIER_OPTIONAL": "1",
        }
    )
    assert cp.returncode == 0, cp.stderr
    calls = call_log.read_text()
    assert f"-r {REPO_ROOT / 'requirements-optional.txt'}" in calls
    assert "import pydub; import simpleaudio" in calls


def test_invalid_optional_environment_flag_fails_before_setup(tmp_path):
    cp = _run_setup(extra_env={"CHORDIFIER_OPTIONAL": "sometimes"})
    assert cp.returncode == 2
    assert "Invalid CHORDIFIER_OPTIONAL value: sometimes" in cp.stderr


# ── supported platform family ──────────────────────────────────────


def test_debian_detection_is_capability_based_not_a_version_allowlist(tmp_path):
    setup_source = SETUP_SCRIPT.read_text()
    assert "VERSION_ID" not in setup_source
    assert "/etc/os-release" not in setup_source
    mock_dir = tmp_path / "mock-bin"
    mock_dir.mkdir(exist_ok=True)
    mock_bin = mock_dir / "dpkg-query"
    mock_bin.write_text("""#!/bin/bash
echo 'install ok installed'
""")
    mock_bin.chmod(0o755)
    venv_dir, _ = _healthy_mock_venv(tmp_path)
    cp = _run_setup(
        extra_env={
            "PATH": f"{mock_dir}:/usr/bin:/bin",
            "CHORDIFIER_VENV": str(venv_dir),
        }
    )
    assert cp.returncode == 0, cp.stderr
    assert "Using existing virtual environment" in cp.stdout or "Creating virtual environment" in cp.stdout


def test_non_debian_system_detects_missing_commands(tmp_path):
    mock_bin = tmp_path / "mock-bin"
    mock_bin.mkdir()
    python3_bin = mock_bin / "python3"
    python3_bin.write_text("""#!/bin/bash
if [[ "$*" == *"INCLUDEPY"* ]]; then
    echo "/nonexistent/python/include"
elif [[ "$*" == *"version_info.major"* ]]; then
    echo 3.12
fi
exit 0
""")
    python3_bin.chmod(0o755)
    (mock_bin / "bash").symlink_to("/usr/bin/bash")
    (mock_bin / "env").symlink_to("/usr/bin/env")
    (mock_bin / "dirname").symlink_to("/usr/bin/dirname")
    (mock_bin / "pwd").symlink_to("/bin/pwd")
    cp = _run_setup(
        extra_env={
            "PATH": str(mock_bin),
            "CHORDIFIER_VENV": str(tmp_path / "venv"),
        }
    )
    assert cp.returncode == 2
    assert "Setup paused" in cp.stderr
    assert "Missing:" in cp.stderr
    assert "No virtual environment was created or modified." in cp.stderr


# ── alias / dry-run behavior at the Make level ────────────────────


def test_make_install_dry_run_matches_make_setup():
    r1 = subprocess.run(
        ["make", "-C", str(REPO_ROOT), "--no-print-directory", "-n", "setup"],
        capture_output=True, text=True, check=True,
    ).stdout
    r2 = subprocess.run(
        ["make", "-C", str(REPO_ROOT), "--no-print-directory", "-n", "install"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert r1 == r2


def test_make_setup_dev_dry_run_matches_make_setup():
    r1 = subprocess.run(
        ["make", "-C", str(REPO_ROOT), "--no-print-directory", "-n", "setup"],
        capture_output=True, text=True, check=True,
    ).stdout
    r2 = subprocess.run(
        ["make", "-C", str(REPO_ROOT), "--no-print-directory", "-n", "setup-dev"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert r1 == r2


# ── future-compatibility detection ─────────────────────────────────


def test_setup_rejects_future_python_version_clearly(tmp_path):
    mock_bin = tmp_path / "mock-bin"
    mock_bin.mkdir()
    python3_bin = mock_bin / "python3"
    python3_bin.write_text("""#!/bin/bash
if [[ "$*" == *"version_info.major"* ]]; then
    echo 3.15
fi
exit 0
""")
    python3_bin.chmod(0o755)
    (mock_bin / "bash").symlink_to("/usr/bin/bash")
    (mock_bin / "env").symlink_to("/usr/bin/env")
    (mock_bin / "dirname").symlink_to("/usr/bin/dirname")
    (mock_bin / "pwd").symlink_to("/bin/pwd")
    cp = _run_setup(
        extra_env={
            "PATH": str(mock_bin),
            "CHORDIFIER_VENV": str(tmp_path / "venv"),
        }
    )
    assert cp.returncode == 1
    assert "Unsupported or untested Python version" in cp.stderr
    assert "3.10-3.14" in cp.stderr


def test_setup_warns_on_python3_14_not_disallowed(tmp_path):
    mock_bin = tmp_path / "mock-bin"
    mock_bin.mkdir()
    python3_bin = mock_bin / "python3"
    python3_bin.write_text("""#!/bin/bash
if [[ "$*" == *"version_info.major"* ]]; then
    echo 3.14
fi
exit 0
""")
    python3_bin.chmod(0o755)
    (mock_bin / "bash").symlink_to("/usr/bin/bash")
    (mock_bin / "env").symlink_to("/usr/bin/env")
    (mock_bin / "dirname").symlink_to("/usr/bin/dirname")
    (mock_bin / "pwd").symlink_to("/bin/pwd")
    cp = _run_setup(
        extra_env={
            "PATH": str(mock_bin),
            "CHORDIFIER_VENV": str(tmp_path / "venv"),
        }
    )
    assert cp.returncode != 1
    assert "Unsupported or untested Python version" not in cp.stderr
    assert "If a scientific package fails to build" in cp.stderr


def test_synthetic_newer_debian_still_detects_packages(tmp_path):
    setup_source = SETUP_SCRIPT.read_text()
    assert "VERSION_ID" not in setup_source
    assert "/etc/os-release" not in setup_source
    assert "/etc/debian_version" in setup_source

    mock_dir = tmp_path / "mock-bin"
    mock_dir.mkdir(exist_ok=True)
    mock_bin = mock_dir / "dpkg-query"
    mock_bin.write_text("""#!/bin/bash
echo 'install ok installed'
""")
    mock_bin.chmod(0o755)
    venv_dir, _ = _healthy_mock_venv(tmp_path)
    cp = _run_setup(
        extra_env={
            "PATH": f"{mock_dir}:/usr/bin:/bin",
            "CHORDIFIER_VENV": str(venv_dir),
        }
    )
    assert cp.returncode == 0, cp.stderr
    assert "Using existing virtual environment" in cp.stdout or "Creating virtual environment" in cp.stdout
