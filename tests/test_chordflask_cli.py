import subprocess
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _install_fake_build_info(monkeypatch, build_version):
    module = types.ModuleType("chordflask_build_info")
    module.BUILD_VERSION = build_version
    monkeypatch.setitem(sys.modules, "chordflask_build_info", module)


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


def test_frozen_version_returns_embedded_build_identity(tmp_path, monkeypatch):
    import chordflask.app as chordflask

    executable = tmp_path / "chordflask"
    executable.touch()
    _install_fake_build_info(monkeypatch, "0.9.12 2026-09-12 05:38 fdfc619")
    monkeypatch.setattr(chordflask.sys, "frozen", True, raising=False)
    monkeypatch.setattr(chordflask.sys, "executable", str(executable))

    assert chordflask._load_version() == "0.9.12 2026-09-12 05:38 fdfc619"


def test_frozen_version_ignores_sibling_version_file(tmp_path, monkeypatch):
    import chordflask.app as chordflask

    executable = tmp_path / "chordflask"
    executable.touch()
    (tmp_path / "VERSION").write_text("9.9.9 forged companion\n")
    _install_fake_build_info(monkeypatch, "0.9.12 2026-09-12 05:38 fdfc619")
    monkeypatch.setattr(chordflask.sys, "frozen", True, raising=False)
    monkeypatch.setattr(chordflask.sys, "executable", str(executable))

    assert chordflask._load_version() == "0.9.12 2026-09-12 05:38 fdfc619"


def test_frozen_version_is_stable_when_sibling_version_changes(tmp_path, monkeypatch):
    import chordflask.app as chordflask

    executable = tmp_path / "chordflask"
    executable.touch()
    companion = tmp_path / "VERSION"
    companion.write_text("9.9.9 forged companion\n")
    _install_fake_build_info(monkeypatch, "0.9.12 2026-09-12 05:38 fdfc619")
    monkeypatch.setattr(chordflask.sys, "frozen", True, raising=False)
    monkeypatch.setattr(chordflask.sys, "executable", str(executable))

    before = chordflask._load_version()
    companion.write_text("0.0.1 tampered\n")
    after_change = chordflask._load_version()
    companion.unlink()
    after_removal = chordflask._load_version()

    assert before == after_change == after_removal == "0.9.12 2026-09-12 05:38 fdfc619"


def test_frozen_version_uses_package_metadata_without_embedded_identity(tmp_path, monkeypatch):
    import chordflask.app as chordflask

    executable = tmp_path / "chordflask"
    executable.touch()
    (tmp_path / "VERSION").write_text("9.9.9 forged companion\n")
    monkeypatch.setattr(chordflask.sys, "frozen", True, raising=False)
    monkeypatch.setattr(chordflask.sys, "executable", str(executable))
    monkeypatch.setattr(chordflask.metadata, "version", lambda package: "1.0.0")

    assert chordflask._load_version() == "1.0.0"


def test_source_checkout_version_includes_file_and_git_identity(monkeypatch):
    import chordflask.app as chordflask

    version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").splitlines()[0]
    captured = {}

    class _Result:
        stdout = "2026-09-12 05:38 fdfc619\n"

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        return _Result()

    monkeypatch.setattr(subprocess, "run", _fake_run)
    monkeypatch.setattr(chordflask.sys, "frozen", False, raising=False)

    assert chordflask._load_version() == f"{version} 2026-09-12 05:38 fdfc619"
    assert captured["cmd"][0] == "git"
    assert Path(captured["cwd"]).resolve() == REPO_ROOT


def test_frozen_build_script_embeds_generated_build_info():
    builder = (REPO_ROOT / "flask" / "build_standalone.sh").read_text(encoding="utf-8")

    assert "chordflask_build_info" in builder
    assert "--hidden-import=chordflask_build_info" in builder
    assert 'BUILD_VERSION = "${BUILD_VERSION}"' in builder
    # The runtime must not be handed the sibling VERSION file path.
    app_source = (REPO_ROOT / "chordflask" / "app.py").read_text(encoding="utf-8")
    assert "chordflask_build_info" in app_source


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
