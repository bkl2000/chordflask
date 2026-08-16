"""Tests for the ``chordflask-export`` CLI."""

import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPO_ROOT / "flask", REPO_ROOT / "flask" / "helpers"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import export_cli  # noqa: E402


def test_export_help_is_user_facing(capsys):
    with pytest.raises(SystemExit) as exc:
        export_cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--format {markdown,pdf,both}" in out
    assert "chordflask-export" in out


def test_export_no_args_shows_help_and_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        export_cli.main([])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "chordflask-export" in out
    assert "--format" in out


def test_export_missing_target_is_error(capsys):
    with pytest.raises(SystemExit) as exc:
        export_cli.main(["--format", "pdf"])
    assert exc.value.code == 2


def test_export_parser_default_format_is_both():
    args = export_cli.build_parser().parse_args(["song.mp4"])
    assert args.format == "both"


def test_export_file_dispatches(monkeypatch, capsys, tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"x")
    calls = []

    def fake_export(media_path, args):
        calls.append((str(media_path), args.format))

    monkeypatch.setattr(export_cli, "export_file", fake_export)

    with pytest.raises(SystemExit) as exc:
        export_cli.main([str(media)])

    assert exc.value.code == 0
    assert calls == [(str(media), "both")]
    assert "Exported:" in capsys.readouterr().out


def test_export_format_selection(monkeypatch, capsys, tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"x")
    calls = []

    monkeypatch.setattr(
        export_cli, "export_file", lambda p, args: calls.append(args.format)
    )

    with pytest.raises(SystemExit) as exc:
        export_cli.main(["--format", "markdown", str(media)])

    assert exc.value.code == 0
    assert calls == ["markdown"]


def test_export_invalid_target_exits_two(capsys, tmp_path):
    with pytest.raises(SystemExit) as exc:
        export_cli.main([str(tmp_path / "missing.mp4")])
    assert exc.value.code == 2
    assert "not a file or directory" in capsys.readouterr().err


def test_export_directory_dispatches(monkeypatch, capsys, tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"a")
    (tmp_path / "b.mp3").write_bytes(b"b")
    calls = []

    monkeypatch.setattr(
        export_cli, "export_file", lambda p, args: calls.append(p.name)
    )

    with pytest.raises(SystemExit) as exc:
        export_cli.main([str(tmp_path)])

    assert exc.value.code == 0
    assert sorted(calls) == ["a.mp4", "b.mp3"]


def test_export_has_no_torch_or_training_import():
    src = (REPO_ROOT / "flask" / "helpers" / "export_cli.py").read_text(encoding="utf-8")
    assert "chordflask_training" not in src
    assert "import torch" not in src
    assert "from torch" not in src


def test_export_launcher_bash_syntax():
    result = subprocess.run(
        ["bash", "-n", str(REPO_ROOT / "scripts" / "chordflask-export")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
