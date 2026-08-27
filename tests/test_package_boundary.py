"""Focused contracts for the ChordFlask application package boundary."""

import importlib
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "chordflask"


def test_core_modules_import_through_chordflask_package():
    import chordflask

    assert chordflask.__name__ == "chordflask"
    for module_name in (
        "analysis_queue",
        "analysis_worker",
        "chordanalyzer",
        "filerepr",
    ):
        module = importlib.import_module(f"chordflask.{module_name}")
        assert module.__package__ == "chordflask"


def test_application_package_does_not_mutate_sys_path():
    offenders = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if "sys.path" in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(PACKAGE_ROOT).as_posix())
    assert offenders == []


def test_runtime_resources_are_owned_by_application_package():
    from chordflask.app import FlaskMP4App

    app = FlaskMP4App.__new__(FlaskMP4App)
    assert Path(app.resource_path("templates")) == PACKAGE_ROOT / "templates"
    assert (PACKAGE_ROOT / "templates" / "home.html").is_file()
    assert Path(app.resource_path("assets")) == PACKAGE_ROOT / "assets"
    assert (PACKAGE_ROOT / "assets" / "fonts" / "LiberationSans-Regular.ttf").is_file()
