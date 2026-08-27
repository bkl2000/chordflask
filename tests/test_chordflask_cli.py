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


def test_frozen_version_uses_package_metadata_without_companion_file(tmp_path, monkeypatch):
    import chordflask.app as chordflask

    executable = tmp_path / "chordflask"
    executable.touch()
    monkeypatch.setattr(chordflask.sys, "frozen", True, raising=False)
    monkeypatch.setattr(chordflask.sys, "executable", str(executable))
    monkeypatch.setattr(chordflask.metadata, "version", lambda package: "1.0.0")

    assert chordflask._load_version() == "1.0.0"


def test_installed_version_uses_package_metadata_without_repository_version(tmp_path, monkeypatch):
    import chordflask.app as chordflask

    installed_module = tmp_path / "site-packages" / "chordflask" / "app.py"
    installed_module.parent.mkdir(parents=True)
    installed_module.touch()
    monkeypatch.setattr(chordflask, "__file__", str(installed_module))
    monkeypatch.setattr(chordflask.sys, "frozen", False, raising=False)
    monkeypatch.setattr(chordflask.metadata, "version", lambda package: "1.0.0")

    assert chordflask._load_version() == "1.0.0"


def test_installed_version_is_unknown_without_package_metadata(tmp_path, monkeypatch):
    import chordflask.app as chordflask

    installed_module = tmp_path / "site-packages" / "chordflask" / "app.py"
    installed_module.parent.mkdir(parents=True)
    installed_module.touch()
    monkeypatch.setattr(chordflask, "__file__", str(installed_module))
    monkeypatch.setattr(chordflask.sys, "frozen", False, raising=False)

    def missing_metadata(package):
        raise chordflask.metadata.PackageNotFoundError(package)

    monkeypatch.setattr(chordflask.metadata, "version", missing_metadata)

    assert chordflask._load_version() == "unknown"
