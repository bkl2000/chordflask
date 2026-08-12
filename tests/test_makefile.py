import os
import shutil
import stat
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_make(*args):
    return subprocess.run(
        ["make", "-C", str(REPO_ROOT), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def requirement_lines(name):
    return {
        line.strip()
        for line in (REPO_ROOT / name).read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }


def test_dependency_groups_and_python312_constraints_are_complete():
    assert requirement_lines("requirements.txt") == {"-r requirements-core.txt"}
    core = requirement_lines("requirements-core.txt")
    dev = requirement_lines("requirements-dev.txt")
    build = requirement_lines("requirements-build.txt")
    optional = requirement_lines("requirements-optional.txt")
    constraints = requirement_lines("constraints-python312.txt")

    for package in ("Flask", "librosa", "moviepy", "music21", "numpy", "Pillow", "vamp"):
        assert any(line.lower().startswith(package.lower()) for line in core)
        assert any(line.lower().startswith(f"{package.lower()}==") for line in constraints)
    assert not any(line.lower().startswith("cython") for line in core)
    assert any(line.lower().startswith("cython") for line in build)
    assert any(line.lower().startswith("pyinstaller") for line in build)
    assert any(line.lower().startswith("pytest") for line in dev)
    assert any(line.lower().startswith("mido") for line in dev)
    assert any(line.lower().startswith("simpleaudio") for line in optional)
    assert any(line.lower().startswith("pydub") for line in optional)
    assert not any(line.lower().startswith("madmom") for line in optional)
    for package in ("Cython", "mido", "pydub", "pyinstaller", "pytest", "simpleaudio"):
        assert any(line.lower().startswith(f"{package.lower()}==") for line in constraints)


def test_default_make_target_only_shows_documented_commands():
    output = run_make("--no-print-directory")

    known = (
        "all",
        "setup",
        "install",
        "setup-runtime",
        "setup-dev",
        "setup-recreate",
        "fix-permissions",
        "test",
        "check",
        "run",
        "worker",
        "standalone",
        "standalone-run",
        "plugins",
        "status",
        "clean",
        "clean-report",
    )
    for target in known:
        assert f"make {target}" in output
    assert "Show this help (no changes)" in output


def test_make_setup_is_full_setup():
    setup = run_make("--no-print-directory", "-n", "setup")
    assert "--dev" in setup
    assert "setup_venv.sh" in setup


def test_make_install_is_alias_for_setup():
    setup = run_make("--no-print-directory", "-n", "setup")
    install = run_make("--no-print-directory", "-n", "install")
    assert install == setup
    assert "--dev" in install


def test_make_setup_runtime_has_no_dev_flag():
    runtime = run_make("--no-print-directory", "-n", "setup-runtime")
    assert "--dev" not in runtime
    assert "setup_venv.sh" in runtime


def test_make_setup_dev_is_alias_for_setup():
    setup = run_make("--no-print-directory", "-n", "setup")
    setup_dev = run_make("--no-print-directory", "-n", "setup-dev")
    assert setup_dev == setup
    assert "--dev" in setup_dev


def test_make_dry_runs_preserve_target_order_and_variables():
    setup = run_make(
        "--no-print-directory",
        "-n",
        "setup",
        "VENV_DIR=/tmp/chordflask-test-venv",
        "PYTHON_BIN=python3.12",
    )
    standalone = run_make(
        "--no-print-directory",
        "-n",
        "standalone",
        "VENV_DIR=/tmp/chordflask-test-venv",
        "TEST_ARGS=-q",
    )
    cleanup = run_make("--no-print-directory", "-n", "clean")

    assert 'CHORDIFIER_VENV="/tmp/chordflask-test-venv"' in setup
    assert 'CHORDIFIER_PYTHON="python3.12"' in setup
    assert "--dev" in setup
    assert standalone.index("scripts/run_tests.sh") < standalone.index("compileall")
    assert standalone.index("compileall") < standalone.index("build_standalone.sh")
    assert " -q" in standalone
    assert "flask/build" in cleanup
    assert "flask/dist" in cleanup
    assert "videos" not in cleanup
    assert "backups" not in cleanup
    assert ".chordflask" not in cleanup


def test_clean_report_target_is_read_only_by_interface():
    output = run_make("--no-print-directory", "-n", "clean-report")

    assert "clean_report.sh" in output
    assert "rm " not in output
    assert "rm -rf" not in output


def test_clean_report_finds_all_cache_types_without_touching_protected_data(tmp_path):
    project = tmp_path / "project"
    for rel in (
        "flask/build",
        "flask/pkg/__pycache__",
        "scripts",
        "tests",
        "videos/.chordflask",
        "backups",
        "vendor",
        ".git",
    ):
        (project / rel).mkdir(parents=True, exist_ok=True)

    cleanable = {
        "flask/build/artifact.bin": b"build",
        "flask/pkg/__pycache__/module.pyc": b"cache",
        "scripts/loose.pyc": b"bytecode",
        "tests/old.pyo": b"optimized",
        ".coverage": b"coverage",
    }
    protected = {
        "videos/song.mp4": b"media",
        "videos/.chordflask/song.json": b"sidecar",
        "backups/archive.bin": b"backup",
        "vendor/plugin.so": b"vendor",
        ".git/index": b"git",
    }
    for rel, content in cleanable.items() | protected.items():
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    before = {rel: (project / rel).read_bytes() for rel in cleanable | protected}
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "clean_report.sh")],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "CLEAN_REPORT_ROOT": str(project)},
    )

    assert "flask/build" in result.stdout
    assert "flask/pkg/__pycache__" in result.stdout
    assert "scripts/loose.pyc" in result.stdout
    assert "tests/old.pyo" in result.stdout
    assert ".coverage" in result.stdout
    for sentinel in ("song.mp4", "song.json", "archive.bin", "plugin.so", ".git/index"):
        assert sentinel not in result.stdout
    after = {rel: (project / rel).read_bytes() for rel in cleanable | protected}
    assert after == before


def test_clean_report_handles_an_empty_temporary_project(tmp_path):
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "clean_report.sh")],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "CLEAN_REPORT_ROOT": str(tmp_path)},
    )
    assert "Cleanable: 0 entries, 0 KB" in result.stdout


def test_clean_excludes_videos_and_backups():
    output = run_make("--no-print-directory", "-n", "clean")

    assert "flask/build" in output
    assert "flask/dist" in output
    assert "videos" not in output
    assert "backups" not in output
    assert "vendor" not in output
    assert ".chordflask" not in output


def test_standalone_run_does_not_implicitly_build():
    output = run_make("--no-print-directory", "-n", "standalone-run")

    assert "build_standalone.sh" not in output
    assert "make standalone" in output


def test_make_all_runs_fix_permissions_before_setup_before_check():
    output = run_make("--no-print-directory", "-n", "all")

    fix_idx = output.index("fix_permissions.sh")
    setup_idx = output.index("setup_venv.sh")
    check_idx = output.index("scripts/run_tests.sh")
    compile_idx = output.index("compileall")
    diff_idx = output.index("diff --check")
    assert fix_idx < setup_idx < check_idx < compile_idx < diff_idx


def test_permission_contract_matches_repair_targets():
    executable_targets = (
        "scripts/chordflask.sh",
        "scripts/fix_permissions.sh",
        "scripts/install_vamp_plugins.sh",
        "scripts/run_tests.sh",
        "scripts/setup_venv.sh",
        "scripts/metric_chords_diff.py",
        "scripts/compare_chord_json.py",
        "flask/build_standalone.sh",
        "flask/install_standalone.sh",
        "flask/helpers/webm2mp4",
        "flask/helpers/youtube_donwload",
    )
    for rel in executable_targets:
        assert (REPO_ROOT / rel).stat().st_mode & stat.S_IXUSR, rel
    assert not (
        (REPO_ROOT / "flask/install_dependencies.sh").stat().st_mode
        & stat.S_IXUSR
    )
    assert not (REPO_ROOT / "flask/chordanalyzer.py").stat().st_mode & stat.S_IXUSR


def test_public_ci_installs_vamp_plugins_outside_repository():
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text()

    assert '--dest "${RUNNER_TEMP}/vamp"' in workflow
    assert "--dest vendor/vamp/linux-x86_64" not in workflow
    assert 'CHORDIFIER_REQUIRE_VAMP: "1"' in workflow
    assert "CHORDIFIER_TEST_VAMP_PATH: ${{ runner.temp }}/vamp" in workflow
    assert "VAMP_PATH: ${{ runner.temp }}/vamp" in workflow


def test_launchers_delegate_worker_ownership_to_chordflask():
    source_launcher = (REPO_ROOT / "scripts/chordflask.sh").read_text()
    standalone_builder = (REPO_ROOT / "flask/build_standalone.sh").read_text()

    assert 'exec "${PYTHON_BIN}" flask/chordflask.py "$@"' in source_launcher
    assert 'exec "${CHORDFLASK_BIN}" "$@"' in standalone_builder
    for launcher in (source_launcher, standalone_builder):
        assert "--worker &" not in launcher
        assert "WORKER_PID" not in launcher


def test_fix_permissions_repairs_once_and_is_then_idempotent(tmp_path):
    project = tmp_path / "project"
    script_dir = project / "scripts"
    script_dir.mkdir(parents=True)
    repair_script = script_dir / "fix_permissions.sh"
    shutil.copy2(REPO_ROOT / "scripts" / "fix_permissions.sh", repair_script)
    repair_script.chmod(0o755)
    target = script_dir / "chordflask.sh"
    target.write_text("#!/usr/bin/env bash\n")
    target.chmod(0o644)

    first = subprocess.run(
        ["bash", str(repair_script)], check=True, capture_output=True, text=True
    )
    second = subprocess.run(
        ["bash", str(repair_script)], check=True, capture_output=True, text=True
    )

    assert target.stat().st_mode & stat.S_IXUSR
    assert "1 fixed" in first.stdout
    assert "0 fixed" in second.stdout


def test_fix_permissions_leaves_non_executable_python_module_unchanged(tmp_path):
    project = tmp_path / "project"
    script_dir = project / "scripts"
    script_dir.mkdir(parents=True)
    repair_script = script_dir / "fix_permissions.sh"
    shutil.copy2(REPO_ROOT / "scripts" / "fix_permissions.sh", repair_script)
    repair_script.chmod(0o755)
    py_module = script_dir / "chorddata.py"
    py_module.write_text("class ChordData:\n    pass\n")
    py_module.chmod(0o644)

    subprocess.run(
        ["bash", str(repair_script)], check=True, capture_output=True, text=True
    )

    assert not py_module.stat().st_mode & stat.S_IXUSR


def test_fix_permissions_can_restore_executability_with_only_shebang_fallback(tmp_path):
    project = tmp_path / "project"
    script_dir = project / "scripts"
    script_dir.mkdir(parents=True)
    repair_script = script_dir / "fix_permissions.sh"
    shutil.copy2(REPO_ROOT / "scripts" / "fix_permissions.sh", repair_script)
    repair_script.chmod(0o755)
    target = script_dir / "helper.sh"
    target.write_text("#!/usr/bin/env bash\necho ok\n")
    target.chmod(0o644)

    result = subprocess.run(
        ["bash", str(repair_script)], check=True, capture_output=True, text=True
    )

    assert target.stat().st_mode & stat.S_IXUSR
    assert "+x" in result.stdout


def test_fix_permissions_uses_git_modes_without_shebang_override(tmp_path):
    project = tmp_path / "project"
    script_dir = project / "scripts"
    flask_dir = project / "flask"
    script_dir.mkdir(parents=True)
    flask_dir.mkdir()
    repair_script = script_dir / "fix_permissions.sh"
    shutil.copy2(REPO_ROOT / "scripts" / "fix_permissions.sh", repair_script)
    repair_script.chmod(0o755)
    module = flask_dir / "module.py"
    module.write_text("#!/usr/bin/env python3\n")
    module.chmod(0o644)
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(
        [
            "git", "-C", str(project), "-c", "user.name=Test",
            "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture",
        ],
        check=True,
    )
    repair_script.chmod(0o644)
    module.chmod(0o755)

    first = subprocess.run(
        ["bash", str(repair_script)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    second = subprocess.run(
        ["bash", str(repair_script)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    assert repair_script.stat().st_mode & stat.S_IXUSR
    assert not module.stat().st_mode & stat.S_IXUSR
    assert "2 fixed" in first.stdout
    assert "0 fixed" in second.stdout
