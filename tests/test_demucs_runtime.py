import json
import subprocess

import pytest

from chordflask_demucs import runtime


def test_runtime_uses_configured_venv(monkeypatch, tmp_path):
    monkeypatch.setenv("CHORDFLASK_DEMUCS_VENV", str(tmp_path / "runtime"))
    assert runtime.venv_python() == tmp_path / "runtime" / "bin" / "python"


def test_runtime_probe_isolated_and_returns_versions(monkeypatch, tmp_path):
    python = tmp_path / "runtime" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    python.chmod(0o755)
    monkeypatch.setenv("CHORDFLASK_DEMUCS_VENV", str(python.parents[1]))

    def fake_run(command, **kwargs):
        assert command[0] == str(python)
        assert command[1] == "-c"
        assert kwargs.get("shell") is not True
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"demucs": "4.0.1", "torch": "2.6.0", "cuda": True}),
            stderr="",
        )

    monkeypatch.setattr(runtime.subprocess, "run", fake_run)
    info = runtime.require_runtime()

    assert info.demucs_version == "4.0.1"
    assert info.torch_version == "2.6.0"
    assert info.cuda_available is True


def _runtime(tmp_path, cuda_available):
    return runtime.RuntimeInfo(
        tmp_path / "venv",
        tmp_path / "venv/bin/python",
        "4.0.1",
        "2.6.0",
        cuda_available,
    )


def test_auto_resolves_to_cuda_when_available(tmp_path):
    assert runtime.resolve_device("auto", _runtime(tmp_path, True)) == "cuda"


def test_auto_resolves_to_cpu_when_cuda_is_unavailable(tmp_path):
    assert runtime.resolve_device("auto", _runtime(tmp_path, False)) == "cpu"


def test_explicit_cuda_is_preserved(tmp_path):
    assert runtime.resolve_device("cuda", _runtime(tmp_path, False)) == "cuda"


def test_explicit_cpu_is_preserved(tmp_path):
    assert runtime.resolve_device("cpu", _runtime(tmp_path, True)) == "cpu"


def test_runtime_missing_is_actionable(monkeypatch, tmp_path):
    monkeypatch.setenv("CHORDFLASK_DEMUCS_VENV", str(tmp_path / "missing"))

    with pytest.raises(runtime.DemucsRuntimeError, match="make setup-demucs"):
        runtime.require_runtime()


def test_runtime_environment_keeps_cache_outside_repository(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    monkeypatch.setenv("CHORDFLASK_DEMUCS_CACHE", str(cache))

    env = runtime.environment()

    assert env["TORCH_HOME"] == str(cache)
    assert env["XDG_CACHE_HOME"] == str(cache)
    assert cache.is_dir()
