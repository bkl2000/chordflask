import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
from types import SimpleNamespace

import pytest

from chordflask_score import runtime

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("version", [(3, 10), (3, 11), (3, 13), (3, 14), (4, 0)])
def test_unverified_python_versions_rejected(version):
    with pytest.raises(ValueError, match="Python 3.12"):
        runtime.check_python(version)


def test_verified_python_version():
    runtime.check_python((3, 12, 3))


def test_setup_rejects_wrong_existing_interpreter_before_install(tmp_path):
    binary = tmp_path / "venv/bin/python"
    binary.parent.mkdir(parents=True)
    binary.write_text(f"#!{sys.executable}\nimport sys\nsys.version_info=(3,13,0)\n"
                      "assert sys.argv[1] == '-c'\nexec(sys.argv[2])\n")
    binary.chmod(0o755)
    env = dict(os.environ, CHORDFLASK_SCORE_VENV=str(binary.parent.parent),
               CHORDFLASK_SCORE_PYTHON="/does-not-exist")
    result = subprocess.run(["bash", str(ROOT / "scripts/setup-score.sh")], env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "Python 3.12" in result.stderr


def test_portable_launcher_preserves_cwd_and_relative_arguments(tmp_path):
    helper = tmp_path / "anywhere/helper"
    helper.parent.mkdir()
    shutil.copyfile(ROOT / "scripts/chordflask-score", helper)
    binary = tmp_path / "runtime/bin/chordflask-score"
    binary.parent.mkdir(parents=True)
    binary.write_text(f"#!{sys.executable}\nimport os,sys,json\nprint(json.dumps([os.getcwd(),sys.argv[1:]]))\n")
    binary.chmod(0o755)
    caller = tmp_path / "caller"
    caller.mkdir()
    result = subprocess.run(["bash", str(helper), "relative.mp3", "--dry-run"], cwd=caller,
                            env=dict(os.environ, CHORDFLASK_SCORE_VENV=str(binary.parent.parent)),
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert json.loads(result.stdout) == [str(caller), ["relative.mp3", "--dry-run"]]


def test_score_imports_stay_lightweight():
    code = (
        f"import sys; sys.path.insert(0, {str(ROOT)!r}); "
        "import chordflask_score.cli, chordflask_score.worker; "
        "assert not {'torch','torchaudio','transkun','verovio','music21','demucs','flask'} & set(sys.modules)"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_optional_metadata_and_standalone_exclusion():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert config["project"]["scripts"]["chordflask-score"] == "chordflask_score.cli:main"
    dependencies = (ROOT / "requirements-core.txt").read_text().lower()
    assert "transkun" not in dependencies and "verovio" not in dependencies
    content = (ROOT / "flask/build_standalone.sh").read_text()
    assert all(f"--exclude-module={name}" in content for name in ("chordflask_score.cli", "chordflask_score.worker", "pretty_midi", "transkun", "verovio"))


def test_missing_runtime_and_timeouts_have_actionable_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDFLASK_SCORE_VENV", str(tmp_path))
    with pytest.raises(RuntimeError, match="setup-score"):
        runtime.execute(["--check"])
    monkeypatch.setattr(runtime, "runtime_python", lambda: Path(sys.executable))
    def timeout(*args, **kwargs):
        assert args[0][1:4] == ["-I", "-m", "chordflask_score.worker"]
        raise subprocess.TimeoutExpired("worker", 60)
    monkeypatch.setattr(runtime.subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="Score runtime failed"):
        runtime.require_runtime()


def test_changed_worker_code_requires_setup(monkeypatch):
    monkeypatch.setattr(runtime, "execute", lambda *args, **kwargs: json.dumps({"code": "old"}))
    with pytest.raises(RuntimeError, match="Rerun make setup-score"):
        runtime.require_runtime()


def test_original_event_seconds_are_not_rounded_to_midi_ticks():
    from chordflask_score.worker import original_events
    start, end = .123456789, .987654321
    events = [SimpleNamespace(pitch=60, velocity=80, start=start, end=end),
              SimpleNamespace(pitch=-64, velocity=127, start=start, end=end)]
    payload = original_events(events)
    assert payload["notes"][0]["start"] == start
    assert payload["notes"][0]["end"] == end
    assert payload["controllers"] == [{"number": 64, "value": 127, "time": start},
                                       {"number": 64, "value": 0, "time": end}]


def test_midi_parser_normalizes_library_numeric_types(monkeypatch):
    import numpy as np
    from chordflask_score.worker import read_midi

    one_tick_at_120_bpm = .5 / 960
    note = SimpleNamespace(pitch=np.int64(60), velocity=np.int64(80),
                           start=np.float64(0), end=np.float64(one_tick_at_120_bpm))
    controller = SimpleNamespace(number=np.int64(64), value=np.int64(127), time=np.float64(.25))
    performance = SimpleNamespace(instruments=[SimpleNamespace(
        notes=[note], control_changes=[controller])])
    monkeypatch.setitem(sys.modules, "pretty_midi", SimpleNamespace(PrettyMIDI=lambda _: performance))

    payload = read_midi(Path("ignored.mid"))

    assert payload == {"notes": [{"pitch": 60, "velocity": 80, "start": 0.0,
                                   "end": one_tick_at_120_bpm}],
                       "controllers": [{"number": 64, "value": 127, "time": .25}]}
    assert all(type(payload["notes"][0][key]) is float for key in ("start", "end"))


def test_worker_reports_note_time_error_without_traceback(tmp_path, monkeypatch, capsys):
    from chordflask_score import worker
    from chordflask_score.notation import NoteTimeError

    rhythm = tmp_path / "rhythm.json"
    rhythm.write_text(json.dumps({"beat_times": [0, .5, 1], "beat_numbers": [1, 2, 3],
                                  "meter_signature": 4}))
    monkeypatch.setattr(worker, "check_runtime", lambda: {"cuda": False})
    monkeypatch.setattr(worker, "transcribe", lambda *args: (_ for _ in ()).throw(
        NoteTimeError("note[7] pitch=61 has invalid interval start=1.0, end=1.0")))

    result = worker.main(["--audio", str(tmp_path / "input.wav"), "--rhythm", str(rhythm),
                          "--output", str(tmp_path / "output")])

    assert result == 1
    error = capsys.readouterr().err
    assert error == ("Invalid transcription data: note[7] pitch=61 has invalid interval "
                     "start=1.0, end=1.0\n")
    assert "Traceback" not in error
