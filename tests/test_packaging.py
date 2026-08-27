"""Focused contracts for the editable ChordFlask installation."""

import importlib.metadata
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRY_POINTS = {
    "chordflask": "chordflask.app:main",
    "chordflask-analyze": "chordflask.helpers.analyze_cli:main",
    "chordflask-export": "chordflask.helpers.export_cli:main",
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
