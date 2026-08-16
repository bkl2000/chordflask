"""Tests for the ``chordflask-maintain`` CLI and its framework-free boundary."""

import json
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(capsys, *args):
    from chordflask_maintain import cli

    with pytest.raises(SystemExit) as exc:
        cli.main(list(args))
    return exc.value.code, capsys.readouterr()


def test_maintain_help_lists_subcommands(capsys):
    code, captured = _run_cli(capsys, "--help")
    assert code == 0
    out = captured.out
    for sub in ("storage", "migrate-schema", "validate", "doctor"):
        assert sub in out


def test_maintain_no_args_shows_help_and_exits_zero(capsys):
    code, captured = _run_cli(capsys)
    assert code == 0
    out = captured.out
    for sub in ("storage", "migrate-schema", "validate", "doctor"):
        assert sub in out
    assert "chordflask-maintain doctor" in out
    assert "chordflask-maintain storage report /music/videos" in out


def test_maintain_subcommand_without_target_is_error(capsys):
    code, _ = _run_cli(capsys, "validate")
    assert code == 2
    code, _ = _run_cli(capsys, "migrate-schema")
    assert code == 2


def test_storage_report_dispatches(capsys, tmp_path):
    code, captured = _run_cli(capsys, "storage", "report", str(tmp_path))
    assert code == 0
    assert "no analysis storage" in captured.out


def test_migrate_schema_dispatches(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        "chordflask_maintain.migrate.migrate_directory",
        lambda d: {"files": 1, "migrated": 1, "skipped": 0, "failed": 0},
    )
    code, captured = _run_cli(capsys, "migrate-schema", str(tmp_path))
    assert code == 0
    assert "migrated:   1" in captured.out


def test_validate_directory(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        "chordflask_maintain.validate.validate_directory",
        lambda d: {"valid": 2, "invalid": 0},
    )
    code, captured = _run_cli(capsys, "validate", str(tmp_path))
    assert code == 0
    assert "valid:      2" in captured.out


# ── real validate classification ─────────────────────────────────────


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _validate_file(tmp_path, name, data):
    from chordflask_maintain.validate import validate_file

    path = _write_json(tmp_path / name, data)
    return validate_file(path)


def _v3():
    return {
        "schema_version": 3,
        "prefer_flats": True,
        "transpose": 0,
        "user_data": {},
        "chord_tracks": {
            "chordino": {"chords": [{"timestamp": 0.0, "chord": "C"}], "metadata": {}}
        },
        "rhythm_tracks": {
            "qm_barbeattracker": {
                "bpm": 120,
                "meter_signature": 4,
                "beat_times": [0.0, 0.5],
                "beat_numbers": [1, 2],
                "metadata": {},
            }
        },
    }


def test_validate_file_accepts_schema_v3(tmp_path):
    assert _validate_file(tmp_path, "v3.json", _v3()) == ("valid", None)


def test_validate_file_accepts_schema_1_and_2(tmp_path):
    for version in (1, 2):
        data = {"schema_version": version, "base_chords": [{"timestamp": 0.0, "chord": "C"}]}
        assert _validate_file(tmp_path, f"v{version}.json", data) == ("valid", None)


def test_validate_file_accepts_unversioned_legacy(tmp_path):
    data = {"base_chords": [{"timestamp": 0.0, "chord": "C"}]}
    assert _validate_file(tmp_path, "legacy.json", data) == ("valid", None)


def test_validate_file_ignores_foreign_json(tmp_path):
    assert _validate_file(tmp_path, "foreign.json", {"source": "x"}) == ("ignore", None)


def test_validate_file_ignores_training_json(tmp_path):
    data = {"source_id": "abc", "media_path": "/tmp/x.mp4"}
    assert _validate_file(tmp_path, "song.training.json", data) == ("ignore", None)


def test_validate_file_rejects_corrupt_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not valid json", encoding="utf-8")
    from chordflask_maintain.validate import validate_file

    kind, message = validate_file(path)
    assert kind == "invalid"
    assert "could not read JSON" in message


def test_validate_directory_ignores_foreign_json(tmp_path):
    from chordflask_maintain.validate import validate_directory

    store = tmp_path / ".chordflask"
    _write_json(store / "song.json", _v3())
    _write_json(store / "song.training.json", {"source_id": "abc"})
    _write_json(store / "foreign.json", {"source": "x"})

    counts = validate_directory(tmp_path)
    assert counts == {"valid": 1, "invalid": 0}


def test_validate_cli_file_skips_foreign_json(capsys, tmp_path):
    path = _write_json(tmp_path / "foreign.json", {"source": "x"})
    code, captured = _run_cli(capsys, "validate", str(path))
    assert code == 0
    assert "SKIP: not a ChordFlask analysis" in captured.out


def test_doctor_reports_and_exits(monkeypatch, capsys):
    monkeypatch.setattr(
        "chordflask_maintain.doctor.run_doctor",
        lambda: {
            "python_version": "3.12.3",
            "python_interpreter": "/x/bin/python",
            "python_ok": True,
            "ffmpeg": "/usr/bin/ffmpeg",
            "vamp_found": ["nnls-chroma.so", "qm-vamp-plugins.so"],
            "vamp_missing": [],
            "queue_dir": "/home/user/.chordflask",
            "queue_writable": True,
        },
    )
    code, captured = _run_cli(capsys, "doctor")
    assert code == 0
    assert "ChordFlask doctor" in captured.out
    assert "Vamp plugins" in captured.out


def test_doctor_exit_one_when_incomplete(monkeypatch, capsys):
    monkeypatch.setattr(
        "chordflask_maintain.doctor.run_doctor",
        lambda: {
            "python_version": "3.12.3",
            "python_interpreter": "/x/bin/python",
            "python_ok": True,
            "ffmpeg": None,
            "vamp_found": [],
            "vamp_missing": ["nnls-chroma.so", "qm-vamp-plugins.so"],
            "queue_dir": "/home/user/.chordflask",
            "queue_writable": True,
        },
    )
    code, _ = _run_cli(capsys, "doctor")
    assert code == 1


def test_chordflask_maintain_is_framework_free():
    package = REPO_ROOT / "chordflask_maintain"
    sources = [p.read_text(encoding="utf-8") for p in package.glob("*.py")]
    combined = "\n".join(sources)
    for forbidden in (
        "from flask",
        "import flask",
        "import torch",
        "from torch",
        "import librosa",
        "from librosa",
        "import music21",
        "from music21",
        "chordflask_training",
        "from training",
    ):
        assert forbidden not in combined, forbidden
    assert "from chordflask_base import" in combined


def test_maintain_launcher_bash_syntax():
    result = subprocess.run(
        ["bash", "-n", str(REPO_ROOT / "scripts" / "chordflask-maintain")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
