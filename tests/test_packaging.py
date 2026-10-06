"""Focused contracts for the editable ChordFlask installation."""

import importlib.metadata
import shutil
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRY_POINTS = {
    "chordflask": "chordflask.app:main",
    "chordflask-analyze": "chordflask.helpers.analyze_cli:main",
    "chordflask-export": "chordflask.helpers.export_cli:main",
    "chordflask-genlyrics": "chordflask_lyrics.cli:main",
    "chordflask-maintain": "chordflask_maintain.cli:main",
    "chordflask-demucs": "chordflask_demucs.cli:main",
}


def test_pyproject_keeps_version_file_canonical():
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version", "dependencies"]' in text
    assert 'version = {file = ["VERSION"]}' in text
    assert '[tool.setuptools.package-data]' in text
    assert '"templates/*.html"' in text
    assert '"assets/fonts/*.ttf"' in text
    assert '"assets/fonts/LICENSE.txt"' in text


def test_btc_license_is_explicit_package_data():
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = config["tool"]["setuptools"]["package-data"]["chordflask_btc"]
    assert "model/BTC-LICENSE.txt" in package_data
    assert (REPO_ROOT / "chordflask_btc/model/BTC-LICENSE.txt").is_file()


def test_btc_license_survives_setuptools_source_archive(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    license_path = "chordflask_btc/model/BTC-LICENSE.txt"
    for name in (
        "pyproject.toml", "VERSION", "README.md", "requirements-core.txt", "LICENSE",
        "chordflask_btc/__init__.py", license_path,
    ):
        destination = source / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / name, destination)
    dist = tmp_path / "dist"
    dist.mkdir()
    result = subprocess.run(
        [sys.executable, "-c",
         "from setuptools.build_meta import build_sdist; build_sdist(" + repr(str(dist)) + ")"],
        cwd=source, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    archives = list(dist.glob("*.tar.gz"))
    assert len(archives) == 1
    with tarfile.open(archives[0]) as archive:
        name = next(name for name in archive.getnames() if name.endswith("/" + license_path))
        assert archive.extractfile(name).read() == (REPO_ROOT / license_path).read_bytes()


def test_installed_distribution_uses_version_and_entry_points():
    distribution = importlib.metadata.distribution("chordflask")
    assert distribution.version == (REPO_ROOT / "VERSION").read_text().strip()

    scripts = {
        entry_point.name: entry_point
        for entry_point in distribution.entry_points
        if entry_point.group == "console_scripts"
    }
    assert {name: scripts[name].value for name in ENTRY_POINTS} == ENTRY_POINTS
    for name in ENTRY_POINTS:
        assert (Path(sys.executable).parent / name).is_file()
        assert callable(scripts[name].load())
