import subprocess

import pytest

from chordflask_demucs import runner
from chordflask_demucs.runtime import RuntimeInfo


def _runtime(tmp_path):
    return RuntimeInfo(tmp_path / "venv", tmp_path / "venv/bin/python", "4.0.1", "2.6.0")


def test_command_uses_htdemucs_and_no_shell(tmp_path):
    command = runner.command_for(
        tmp_path / "source.wav",
        tmp_path / "raw",
        _runtime(tmp_path),
        device="cpu",
    )

    assert command == [
        str(tmp_path / "venv/bin/python"),
        "-m",
        "demucs.separate",
        "--name",
        "htdemucs",
        "--out",
        str(tmp_path / "raw"),
        "--device",
        "cpu",
        str(tmp_path / "source.wav"),
    ]


def test_command_resolves_auto_before_invoking_demucs(tmp_path):
    runtime = RuntimeInfo(
        tmp_path / "venv",
        tmp_path / "venv/bin/python",
        "4.0.1",
        "2.6.0",
        True,
    )

    command = runner.command_for(
        tmp_path / "source.wav",
        tmp_path / "raw",
        runtime,
        device="auto",
    )

    assert command[command.index("--device") + 1] == "cuda"


def test_runner_requires_all_four_stems(tmp_path, monkeypatch):
    output = tmp_path / "raw"
    result_dir = output / "htdemucs" / "source"
    result_dir.mkdir(parents=True)
    for stem in ("bass", "drums", "other"):
        (result_dir / f"{stem}.wav").write_bytes(b"wav")

    def fake_run(command, **kwargs):
        assert kwargs.get("shell") is not True
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner, "environment", lambda: {})

    with pytest.raises(runner.DemucsProcessError, match="vocals"):
        runner.run_demucs(tmp_path / "source.wav", output, _runtime(tmp_path), device="cpu")


def test_runner_reports_nonzero_exit(tmp_path, monkeypatch):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 7, stdout="", stderr="model failed")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner, "environment", lambda: {})

    with pytest.raises(runner.DemucsProcessError, match="model failed"):
        runner.run_demucs(tmp_path / "source.wav", tmp_path / "raw", _runtime(tmp_path))
