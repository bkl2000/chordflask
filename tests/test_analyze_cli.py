"""Tests for the public ``chordflask-analyze`` CLI dispatcher."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPO_ROOT / "flask", REPO_ROOT / "flask" / "helpers"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import analyze_cli  # noqa: E402


class FakeAnalysisWorker:
    """Records analyze calls without running any real analysis."""

    analyzed = []

    def __init__(self, analyzer_cls=None):
        self.analyzer_cls = analyzer_cls

    def _analyze(self, media, force=False):
        type(self).analyzed.append((str(media), force))


@pytest.fixture(autouse=True)
def reset_fake_worker():
    FakeAnalysisWorker.analyzed = []
    yield


def _patch_worker(monkeypatch):
    monkeypatch.setattr("analysis_worker.AnalysisWorker", FakeAnalysisWorker)
    monkeypatch.setattr(
        "chordflask_base.analysis_json_path", lambda media: media.parent / ".chordflask" / "x.json"
    )


_CHORD = [{"timestamp": 0.0, "chord": "C"}]
_RHYTHM = {"bpm": 120.0, "meter_signature": 4, "beat_times": [0.0], "beat_numbers": [1]}


def _analysis_path(media):
    return media.parent / ".chordflask" / "x.json"


def _write_analysis(media, *, chord_tracks=None, rhythm_tracks=None, invalid=False):
    path = _analysis_path(media)
    path.parent.mkdir(parents=True, exist_ok=True)
    if invalid:
        path.write_text("{ this is not valid json")
        return
    data = {
        "schema_version": 3,
        "chord_tracks": chord_tracks or {},
        "rhythm_tracks": rhythm_tracks or {},
    }
    path.write_text(json.dumps(data))


def _btc_only(media):
    _write_analysis(media, chord_tracks={"btc": {"chords": _CHORD}})


def _chordino_qm(media):
    _write_analysis(
        media,
        chord_tracks={"chordino": {"chords": _CHORD}},
        rhythm_tracks={"qm_barbeattracker": _RHYTHM},
    )


def _chordino_qm_btc(media):
    _write_analysis(
        media,
        chord_tracks={"chordino": {"chords": _CHORD}, "btc": {"chords": _CHORD}},
        rhythm_tracks={"qm_barbeattracker": _RHYTHM},
    )


# ── entry point / launcher ───────────────────────────────────────────


def test_launcher_is_executable_shell_script():
    launcher = REPO_ROOT / "scripts" / "chordflask-analyze"
    assert launcher.is_file()
    assert launcher.stat().st_mode & stat.S_IXUSR
    assert launcher.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash")


def test_cli_module_has_main_entry():
    assert callable(analyze_cli.main)
    assert callable(analyze_cli.build_parser)


def test_launcher_bash_syntax():
    result = subprocess.run(
        ["bash", "-n", str(REPO_ROOT / "scripts" / "chordflask-analyze")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_cli_runs_with_launcher_path_setup(tmp_path):
    # The launcher only puts the repository root on PYTHONPATH; the CLI module
    # must make its sibling flask/ modules importable on its own.
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "flask" / "helpers" / "analyze_cli.py"),
            "--analyzer",
            "chordino",
            "--dry-run",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "ModuleNotFoundError" not in result.stderr
    assert "Chordino dry-run complete" in result.stdout


# ── parser ───────────────────────────────────────────────────────────


def test_default_analyzer_is_chordino():
    args = analyze_cli.build_parser().parse_args(["song.mp4"])
    assert args.analyzer == "chordino"


def test_no_args_shows_help_and_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        analyze_cli.main([])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "chordflask-analyze" in out
    assert "--analyzer" in out


def test_missing_target_with_analyzer_is_error(capsys):
    with pytest.raises(SystemExit) as exc:
        analyze_cli.main(["--analyzer", "chordino"])
    assert exc.value.code == 2


def test_explicit_chordino_analyzer():
    args = analyze_cli.build_parser().parse_args(["--analyzer", "chordino", "song.mp4"])
    assert args.analyzer == "chordino"


def test_explicit_btc_analyzer_when_backend_available(monkeypatch, tmp_path):
    _fake_backend(monkeypatch, tmp_path)
    args = analyze_cli.build_parser().parse_args(["--analyzer", "btc", "song.mp4"])
    assert args.analyzer == "btc"


def test_unknown_analyzer_exits_two():
    with pytest.raises(SystemExit) as exc:
        analyze_cli.build_parser().parse_args(["--analyzer", "xyz", "song.mp4"])
    assert exc.value.code == 2


def test_help_identifies_btc_as_optional_without_backend(monkeypatch, capsys, tmp_path):
    _no_backend(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as exc:
        analyze_cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--analyzer {chordino,btc}" in out
    assert "Chordino is the default built-in analyzer." in out
    assert "BTC is an optional analyzer" in out


def test_help_shows_btc_with_backend(monkeypatch, capsys, tmp_path):
    _fake_backend(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as exc:
        analyze_cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--analyzer {chordino,btc}" in out
    assert "BTC is an optional analyzer" in out
    assert "chordflask-analyze --analyzer btc song.mp4" in out


def test_btc_unavailable_has_setup_check_and_chordino_guidance(
    monkeypatch, capsys, tmp_path
):
    _no_backend(monkeypatch, tmp_path)
    media = tmp_path / "song.mp4"
    media.write_bytes(b"x")
    monkeypatch.setattr(
        "chordflask_btc.analyze.detect_btc_runtime",
        lambda: {
            "venv": "",
            "checkpoint": "",
            "wrapper": "",
            "complete": False,
            "missing": ["executable wrapper (/missing)"],
        },
    )
    with pytest.raises(SystemExit) as exc:
        analyze_cli.main(["--analyzer", "btc", str(media)])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "optional BTC runtime" in err
    assert "make btc-check" in err
    assert "make setup-btc BTC_ACKNOWLEDGE_WEIGHTS=1" in err
    assert "--analyzer chordino" in err


def test_btc_choice_remains_available_for_actionable_runtime_error(monkeypatch, tmp_path):
    script = tmp_path / "btc-predict-raw"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o644)  # present but not executable
    monkeypatch.setattr("chordflask_btc.runtime.wrapper_path", lambda: script)
    parser = analyze_cli.build_parser()
    assert parser._option_string_actions["--analyzer"].choices == ("chordino", "btc")
    assert parser.parse_args(["--analyzer", "btc", "song.mp4"]).analyzer == "btc"


# ── chordino dispatch ────────────────────────────────────────────────


def test_chordino_file_analyzes_via_worker(monkeypatch, capsys, tmp_path):
    _patch_worker(monkeypatch)
    media = tmp_path / "song.mp4"
    media.write_bytes(b"x")  # no analysis yet

    with pytest.raises(SystemExit) as exc:
        analyze_cli.main([str(media)])

    assert exc.value.code == 0
    assert FakeAnalysisWorker.analyzed == [(str(media), False)]
    assert "OK" in capsys.readouterr().out


def test_chordino_replace_with_existing_chordino_forces_reanalysis(monkeypatch, capsys, tmp_path):
    _patch_worker(monkeypatch)
    media = tmp_path / "song.mp4"
    media.write_bytes(b"x")
    _chordino_qm(media)

    with pytest.raises(SystemExit) as exc:
        analyze_cli.main(["--replace", str(media)])

    assert exc.value.code == 0
    assert FakeAnalysisWorker.analyzed == [(str(media), True)]


def test_chordino_replace_without_analysis_is_first_run(monkeypatch, capsys, tmp_path):
    _patch_worker(monkeypatch)
    media = tmp_path / "song.mp4"
    media.write_bytes(b"x")

    with pytest.raises(SystemExit) as exc:
        analyze_cli.main(["--replace", str(media)])

    assert exc.value.code == 0
    assert FakeAnalysisWorker.analyzed == [(str(media), False)]
    assert "OK" in capsys.readouterr().out


def test_chordino_skips_existing_chordino(monkeypatch, capsys, tmp_path):
    _patch_worker(monkeypatch)
    media = tmp_path / "song.mp4"
    media.write_bytes(b"x")
    _chordino_qm(media)

    with pytest.raises(SystemExit) as exc:
        analyze_cli.main([str(media)])

    assert exc.value.code == 0
    assert FakeAnalysisWorker.analyzed == []
    assert "SKIP: analysis already exists" in capsys.readouterr().out


def test_chordino_directory_dispatches(monkeypatch, capsys, tmp_path):
    _patch_worker(monkeypatch)
    (tmp_path / "a.mp4").write_bytes(b"a")
    (tmp_path / "b.mp3").write_bytes(b"b")

    with pytest.raises(SystemExit) as exc:
        analyze_cli.main([str(tmp_path)])

    assert exc.value.code == 0
    assert {m for m, _ in FakeAnalysisWorker.analyzed} == {
        str(tmp_path / "a.mp4"),
        str(tmp_path / "b.mp3"),
    }


def test_chordino_dry_run_classifies_without_side_effects(monkeypatch, capsys, tmp_path):
    _patch_worker(monkeypatch)
    media = tmp_path / "song.mp4"
    media.write_bytes(b"x")

    with pytest.raises(SystemExit) as exc:
        analyze_cli.main(["--dry-run", str(media)])
    assert exc.value.code == 0
    assert "TODO" in capsys.readouterr().out
    assert FakeAnalysisWorker.analyzed == []

    _chordino_qm(media)
    with pytest.raises(SystemExit) as exc:
        analyze_cli.main(["--dry-run", str(media)])
    assert exc.value.code == 0
    assert "CURRENT" in capsys.readouterr().out
    assert FakeAnalysisWorker.analyzed == []

    with pytest.raises(SystemExit) as exc:
        analyze_cli.main(["--dry-run", "--replace", str(media)])
    assert exc.value.code == 0
    assert "REANALYZE" in capsys.readouterr().out
    assert FakeAnalysisWorker.analyzed == []


def test_chordino_btc_only_dry_run_reports_todo(monkeypatch, capsys, tmp_path):
    _patch_worker(monkeypatch)
    media = tmp_path / "song.mp4"
    media.write_bytes(b"x")
    _btc_only(media)

    with pytest.raises(SystemExit) as exc:
        analyze_cli.main(["--dry-run", str(media)])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "TODO" in out
    assert "CURRENT" not in out
    assert FakeAnalysisWorker.analyzed == []


def test_chordino_btc_only_runs_chordino_instead_of_skipping(monkeypatch, capsys, tmp_path):
    _patch_worker(monkeypatch)
    media = tmp_path / "song.mp4"
    media.write_bytes(b"x")
    _btc_only(media)

    with pytest.raises(SystemExit) as exc:
        analyze_cli.main([str(media)])

    assert exc.value.code == 0
    assert FakeAnalysisWorker.analyzed == [(str(media), True)]
    assert "OK" in capsys.readouterr().out


def test_chordino_chordino_qm_skips_as_current(monkeypatch, capsys, tmp_path):
    _patch_worker(monkeypatch)
    media = tmp_path / "song.mp4"
    media.write_bytes(b"x")
    _chordino_qm(media)

    with pytest.raises(SystemExit) as exc:
        analyze_cli.main([str(media)])

    assert exc.value.code == 0
    assert FakeAnalysisWorker.analyzed == []
    assert "SKIP: analysis already exists" in capsys.readouterr().out


def test_chordino_replace_preserves_foreign_tracks(monkeypatch, capsys, tmp_path):
    _patch_worker(monkeypatch)
    media = tmp_path / "song.mp4"
    media.write_bytes(b"x")
    _chordino_qm_btc(media)

    with pytest.raises(SystemExit) as exc:
        analyze_cli.main(["--replace", str(media)])

    assert exc.value.code == 0
    # --replace routes through the reanalysis path (force=True), which merges
    # and preserves unrelated tracks such as BTC via __preserve_user_data.
    assert FakeAnalysisWorker.analyzed == [(str(media), True)]


def test_chordino_invalid_analysis_is_distinct_and_safe(monkeypatch, capsys, tmp_path):
    _patch_worker(monkeypatch)
    media = tmp_path / "song.mp4"
    media.write_bytes(b"x")
    _write_analysis(media, invalid=True)

    with pytest.raises(SystemExit) as exc:
        analyze_cli.main(["--dry-run", str(media)])

    assert exc.value.code == 0
    assert "INVALID" in capsys.readouterr().out
    assert FakeAnalysisWorker.analyzed == []

    # A normal run reanalyzes from scratch (force=False); the worker preserves
    # the corrupt file and performs safe recovery.
    with pytest.raises(SystemExit) as exc:
        analyze_cli.main([str(media)])
    assert exc.value.code == 0
    assert FakeAnalysisWorker.analyzed == [(str(media), False)]


def test_chordino_invalid_analysis_dry_run_suggests_validation(
    monkeypatch, capsys, tmp_path
):
    _patch_worker(monkeypatch)
    media = tmp_path / "song.mp4"
    media.write_bytes(b"x")
    _write_analysis(media, invalid=True)

    with pytest.raises(SystemExit) as exc:
        analyze_cli.main(["--dry-run", str(media)])

    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "INVALID" in captured.out
    assert f"chordflask-maintain validate {tmp_path}" in captured.err


def test_chordino_vamp_failure_has_one_canonical_hint_for_batch(
    monkeypatch, capsys, tmp_path
):
    _patch_worker(monkeypatch)
    for name in ("a.mp3", "b.mp3"):
        (tmp_path / name).write_bytes(b"x")

    def fail_vamp(self, media, force=False):
        raise RuntimeError("Required Vamp plugins not found: nnls-chroma:chordino")

    monkeypatch.setattr(FakeAnalysisWorker, "_analyze", fail_vamp)

    with pytest.raises(SystemExit) as exc:
        analyze_cli.main([str(tmp_path)])

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.count("make plugins") == 1
    assert err.count("chordflask-maintain doctor") == 1


def test_chordino_invalid_target_exits_two(monkeypatch, capsys, tmp_path):
    _patch_worker(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        analyze_cli.main([str(tmp_path / "missing.mp4")])
    assert exc.value.code == 2
    assert "not a file or directory" in capsys.readouterr().err


def test_chordino_unsupported_suffix_exits_two(monkeypatch, capsys, tmp_path):
    _patch_worker(monkeypatch)
    not_media = tmp_path / "notes.txt"
    not_media.write_bytes(b"x")
    with pytest.raises(SystemExit) as exc:
        analyze_cli.main([str(not_media)])
    assert exc.value.code == 2
    assert "not a supported media file" in capsys.readouterr().err


# ── btc delegation ───────────────────────────────────────────────────


def _fake_backend(monkeypatch, tmp_path):
    script = tmp_path / "btc-predict-raw"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o755)
    monkeypatch.setattr("chordflask_btc.runtime.wrapper_path", lambda: script)
    return script


def _no_backend(monkeypatch, tmp_path):
    monkeypatch.setattr("chordflask_btc.runtime.wrapper_path", lambda: tmp_path / "nope")


def test_btc_delegates_to_backend_with_flags(monkeypatch, tmp_path):
    _fake_backend(monkeypatch, tmp_path)
    calls = {}

    def fake_analyze(target, *, replace, dry_run):
        calls["target"] = target
        calls["replace"] = replace
        calls["dry_run"] = dry_run
        return 0

    monkeypatch.setattr("chordflask_btc.analyze.analyze_btc", fake_analyze)

    with pytest.raises(SystemExit) as exc:
        analyze_cli.main(["--analyzer", "btc", "--replace", "--dry-run", "song.mp4"])

    assert exc.value.code == 0
    assert calls == {
        "target": Path("song.mp4"),
        "replace": True,
        "dry_run": True,
    }


def test_btc_forwards_backend_exit_code(monkeypatch, tmp_path):
    _fake_backend(monkeypatch, tmp_path)
    monkeypatch.setattr("chordflask_btc.analyze.analyze_btc", lambda target, *, replace, dry_run: 7)

    with pytest.raises(SystemExit) as exc:
        analyze_cli.main(["--analyzer", "btc", "song.mp4"])

    assert exc.value.code == 7


# ── architecture boundaries ──────────────────────────────────────────


def test_dispatcher_has_no_torch_or_training_import():
    src = (REPO_ROOT / "flask" / "helpers" / "analyze_cli.py").read_text(encoding="utf-8")
    assert "chordflask_training" not in src
    assert "import torch" not in src
    assert "from torch" not in src
    # BTC availability comes from the installed runtime wrapper, never a
    # private source-tree script.
    assert "chordflask-analyze-btc" not in src
    assert "chordflask-training" not in src


def test_dispatcher_reuses_worker_and_batch_core():
    src = (REPO_ROOT / "flask" / "helpers" / "analyze_cli.py").read_text(encoding="utf-8")
    assert "from analysis_worker import AnalysisWorker" in src
    assert "from batch_core import find_media_files" in src
    assert "from chordanalyzer import ChordAnalyzer" in src
    assert "from chordflask_btc.analyze import analyze_btc" in src
    # No re-implementation of the chordino analysis itself.
    assert "def analyze_chords" not in src
    assert "def _extract_chords" not in src
    assert "def ensure_analyzed" not in src
