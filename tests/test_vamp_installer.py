import importlib.util
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = REPO_ROOT / "flask" / "install_vamp.sh"
VENDOR_DIR = REPO_ROOT / "vendor" / "vamp" / "linux-x86_64"
REQUIRED_VENDOR_LIBS = ("nnls-chroma.so", "qm-vamp-plugins.so")

VAMP_AVAILABLE = importlib.util.find_spec("vamp") is not None


def _require_vendored_plugins():
    missing = [name for name in REQUIRED_VENDOR_LIBS if not (VENDOR_DIR / name).is_file()]
    if missing:
        pytest.skip("Private vendored Vamp plugin binaries are not present")


def _run_installer(extra_args=(), extra_env=None, dest=None):
    env = {**os.environ, "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    if extra_env:
        env.update(extra_env)
    args = ["bash", str(INSTALL_SCRIPT)]
    args.extend(extra_args)
    if dest:
        args.extend(["--dest", str(dest)])
    return subprocess.run(args, capture_output=True, text=True, env=env)


def test_installer_local_install_succeeds(tmp_path):
    _require_vendored_plugins()

    dest = tmp_path / "vamp"
    result = _run_installer(
        extra_args=["--from", str(VENDOR_DIR)],
        dest=dest,
    )

    assert result.returncode == 0, result.stderr
    assert (dest / "nnls-chroma.so").exists()
    assert (dest / "qm-vamp-plugins.so").exists()

    if VAMP_AVAILABLE:
        import vamp

        vamp_path = os.environ.get("VAMP_PATH")
        os.environ["VAMP_PATH"] = str(dest)
        try:
            plugins = set(vamp.list_plugins())
            assert "nnls-chroma:chordino" in plugins
            assert "qm-vamp-plugins:qm-barbeattracker" in plugins
        finally:
            if vamp_path is not None:
                os.environ["VAMP_PATH"] = vamp_path
            else:
                os.environ.pop("VAMP_PATH", None)


def test_installer_reportedly_idempotent(tmp_path):
    _require_vendored_plugins()

    dest = tmp_path / "vamp"
    first = _run_installer(
        extra_args=["--from", str(VENDOR_DIR)],
        dest=dest,
    )
    assert first.returncode == 0, first.stderr

    second = _run_installer(
        extra_args=["--from", str(VENDOR_DIR)],
        dest=dest,
    )
    assert second.returncode == 0, second.stderr
    assert "already installed" in second.stdout


def test_installer_rejects_missing_source_dir(tmp_path):
    result = _run_installer(
        extra_args=["--from", str(tmp_path / "missing")],
        dest=tmp_path / "vamp",
    )

    assert result.returncode == 1
    assert "does not exist" in result.stderr


def test_installer_rejects_missing_files(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()

    result = _run_installer(
        extra_args=["--from", str(empty)],
        dest=tmp_path / "vamp",
    )

    assert result.returncode != 0


def test_installer_help_shows_usage():
    result = _run_installer(extra_args=["--help"])

    assert result.returncode == 0
    assert "--dest" in result.stdout
    assert "--from" in result.stdout


def test_installer_reports_missing_network_when_unreachable(tmp_path, monkeypatch):
    monkeypatch.setenv("NNLS_URL", "http://127.0.0.1:1/nonexistent")
    monkeypatch.setenv("QM_URL", "http://127.0.0.1:1/nonexistent")

    result = subprocess.run(
        ["bash", str(INSTALL_SCRIPT), "--dest", str(tmp_path / "vamp")],
        capture_output=True, text=True,
        env={**os.environ, "NNLS_URL": "http://127.0.0.1:1/nonexistent",
             "QM_URL": "http://127.0.0.1:1/nonexistent"},
        timeout=30,
    )

    assert result.returncode != 0


def test_build_script_excludes_so_files_from_standalone():
    build_script = REPO_ROOT / "flask" / "build_standalone.sh"
    content = build_script.read_text()

    assert "grep -Eiq" in content
    assert "ffmpeg" in content
    assert ".so" in content


def test_build_script_bundles_installer():
    build_script = REPO_ROOT / "flask" / "build_standalone.sh"
    content = build_script.read_text()

    assert "install_vamp.sh" in content
    assert 'docs/STANDALONE.md" "${RELEASE_DIR}/README.md' in content
    assert "THIRD_PARTY_NOTICES.md" in content


def test_installer_enforces_pinned_sha256_checksums():
    content = INSTALL_SCRIPT.read_text()

    assert "NNLS_SHA256=\"877964bce86027d1c73c9210fcb3446b1da10dc40bba36b1bf04a61a60ad1d7f\"" in content
    assert "QM_SHA256=\"53f9e0e24d938507c01cb368e098cb321346b91594695aa877e7f67f17841ffa\"" in content
    assert "sha256sum" in content
    assert "skipping checksum verification" not in content


def test_installer_verification_does_not_interpolate_destination_into_python():
    content = INSTALL_SCRIPT.read_text()

    assert 'VAMP_PATH="$dest" "$python_cmd"' in content
    assert "os.environ['VAMP_PATH'] = '$dest'" not in content


def test_build_script_documents_bundled_runtime_plugin_check():
    chordflask_source = (REPO_ROOT / "flask" / "chordflask.py").read_text()

    assert '"--check-vamp"' in chordflask_source and 'check-vamp' in chordflask_source
    assert "require_vamp_plugins()" in chordflask_source


def test_chordflask_startup_checks_plugins_without_failing(tmp_path):
    import sys

    sys.path.insert(0, str(REPO_ROOT / "flask"))
    from chordflask import FlaskMP4App

    app = FlaskMP4App()
    app.setup_vamp_plugins()

    assert hasattr(app, "plugins_available")
