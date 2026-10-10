"""Tests for the public ``chordflask-analyze`` CLI dispatcher."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

from chordflask.helpers import analyze_cli


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
    monkeypatch.setattr("chordflask.canonical_analysis.analyze_media",
                        lambda media, force=False: FakeAnalysisWorker()._analyze(media, force=force))
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


def test_cli_runs_through_installed_package_module(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "chordflask.helpers.analyze_cli",
            "--analyzer",
            "chordino",
            "--dry-run",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        env=os.environ,
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
    assert "--analyzer {chordino,btc,chordflask-v3}" in out
    assert "Chordino is the default built-in analyzer." in out
    assert "BTC is an optional analyzer" in out


def test_help_shows_btc_with_backend(monkeypatch, capsys, tmp_path):
    _fake_backend(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as exc:
        analyze_cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--analyzer {chordino,btc,chordflask-v3}" in out
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
    assert parser._option_string_actions["--analyzer"].choices == ("chordino", "btc", "chordflask-v3")
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
    assert "LEGACY" in capsys.readouterr().out
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
    src = (REPO_ROOT / "chordflask" / "helpers" / "analyze_cli.py").read_text(encoding="utf-8")
    assert "chordflask_training" not in src
    assert "import torch" not in src
    assert "from torch" not in src
    # BTC availability comes from the installed runtime wrapper, never a
    # private source-tree script.
    assert "chordflask-analyze-btc" not in src
    assert "chordflask-training" not in src


def test_dispatcher_reuses_shared_executor_and_batch_core():
    src = (REPO_ROOT / "chordflask" / "helpers" / "analyze_cli.py").read_text(encoding="utf-8")
    assert "from ..canonical_analysis import analyze_media" in src
    assert "from .batch_core import find_media_files" in src
    assert "worker._analyze" not in src
    assert "from chordflask_btc.analyze import analyze_btc" in src
    # No re-implementation of the chordino analysis itself.
    assert "def analyze_chords" not in src
    assert "def _extract_chords" not in src
    assert "def ensure_analyzed" not in src


@pytest.fixture
def v3_runtime(monkeypatch):
    """Fake only the optional connector, including in public source exports."""
    from types import ModuleType
    from chordflask_base import chord_input_sha256
    from chordflask_btc.schema import load_analysis

    calls = []
    metadata = {
        "model_family": "chordino-correction", "run_id": "frozen-run",
        "dataset_id": "frozen-dataset", "seed": 42, "model_version": "v3",
        "model_sha256": "model-hash", "input_track": "chordino",
        "input_sha256": "input-hash", "media_sha256": "media-hash",
    }
    package = ModuleType("chordflask_v3")
    package.__path__ = []
    runtime = ModuleType("chordflask_v3.runtime")
    runtime.require_runtime = lambda: {}
    predictor = ModuleType("chordflask_v3.predictor")

    def predict(media):
        calls.append(media)
        data, _ = load_analysis(media, discard_invalid_metadata_for="chordflask_v3")
        metadata["input_sha256"] = chord_input_sha256(data["chord_tracks"]["chordino"]["chords"])
        return {
            "chords": [{"timestamp": 0.0, "chord": "N"},
                       {"timestamp": 0.18575963718820862, "chord": "G#min"}],
            "metadata": metadata,
        }

    predictor.predict_media = predict
    package.runtime = runtime
    package.predictor = predictor
    for name, module in (("chordflask_v3", package), (runtime.__name__, runtime),
                         (predictor.__name__, predictor)):
        monkeypatch.setitem(sys.modules, name, module)
    return calls, metadata, runtime, predictor


def _v3_media(tmp_path, *, chordino=True):
    from chordflask_base import ChordData, analysis_json_path

    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    if chordino:
        track = ChordData()
        track.set_chord_track("chordino", _CHORD, metadata={"source": "original"})
        track.set_chord_track("btc", [{"timestamp": 0.0, "chord": "F"}])
        track.set_rhythm_track("qm_barbeattracker", bpm=120, beat_times=[0.0])
        track.user_data = {"title": "Keep me"}
        path = analysis_json_path(media)
        path.parent.mkdir(exist_ok=True)
        track.save_to_file(path)
    return media


def _invoke_v3(target, *flags):
    with pytest.raises(SystemExit) as exc:
        analyze_cli.main(["--analyzer", "chordflask-v3", *flags, str(target)])
    return exc.value.code


def test_v3_choice_accepted():
    args = analyze_cli.build_parser().parse_args(["--analyzer", "chordflask-v3", "song.mp4"])
    assert args.analyzer == "chordflask-v3"


def test_v3_reuses_chordino_persists_provenance_and_generic_player(
    tmp_path, monkeypatch, v3_runtime
):
    from chordflask_base import analysis_json_path
    from chordflask.filerepr import FileRepr
    from chordflask.mp4playerflask import MP4PlayerFlask

    media = _v3_media(tmp_path)
    path = analysis_json_path(media)
    original = json.loads(path.read_text())
    monkeypatch.setattr(analyze_cli, "_run_chordino", lambda *a, **kw: pytest.fail("reanalyzed Chordino"))
    player = MP4PlayerFlask(FileRepr(str(media), datapath=str(path.parent)))
    assert "chordflask_v3" not in player.chord_data.available_chord_track_ids
    assert _invoke_v3(media) == 0
    updated = json.loads(path.read_text())
    v3 = updated["chord_tracks"].pop("chordflask_v3")
    assert updated == original
    assert v3["metadata"] == {**v3_runtime[1], "display_name": "ChordFlask V3"}
    assert v3["chords"] == [
        {"timestamp": 0.0, "chord": "N"},
        {"timestamp": 0.18575963718820862, "chord": "G#min"},
    ]
    assert v3_runtime[0] == [media]
    # Stored-track consumption needs no private runtime, even in a frozen player.
    monkeypatch.setitem(sys.modules, "chordflask_v3", None)
    monkeypatch.setitem(sys.modules, "chordflask_v3.predictor", None)
    monkeypatch.setitem(sys.modules, "chordflask_v3.runtime", None)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    player = MP4PlayerFlask(FileRepr(str(media), datapath=str(path.parent)))
    names = {t["id"]: t["display_name"] for t in player.analysis_track_state()["available_chord_tracks"]}
    assert names["chordino"] == "Chordino"
    assert names["chordflask_v3"] == "ChordFlask V3"
    player.select_analysis_tracks(chord_track_id="chordflask_v3")
    assert player.analysis_track_state()["active_chord_track_id"] == "chordflask_v3"
    assert player.chord_data.chord_track_chords("chordflask_v3") == v3["chords"]


@pytest.mark.parametrize("existing", [False, True])
def test_v3_generates_missing_chordino_with_normal_worker(tmp_path, monkeypatch, v3_runtime, existing):
    from chordflask_base import ChordData, analysis_json_path

    media = _v3_media(tmp_path, chordino=False)
    path = analysis_json_path(media)
    if existing:
        path.parent.mkdir()
        track = ChordData()
        track.set_chord_track("btc", _CHORD)
        track.save_to_file(path)
    calls = []

    def analyze(target, force=False):
        calls.append((target, force))
        assert not v3_runtime[0]
        _v3_media(tmp_path)

    monkeypatch.setattr("chordflask.canonical_analysis.analyze_media", analyze)
    assert _invoke_v3(media) == 0
    assert calls == [(media, existing)]
    assert v3_runtime[0] == [media]
    assert set(json.loads(path.read_text())["chord_tracks"]) == {"chordino", "btc", "chordflask_v3"}


def test_v3_replace_only_selected_track(tmp_path, v3_runtime):
    from chordflask_base import analysis_json_path

    media = _v3_media(tmp_path)
    assert _invoke_v3(media) == 0
    path = analysis_json_path(media)
    before = path.read_bytes()
    assert _invoke_v3(media) == 0
    assert v3_runtime[0] == [media]
    assert path.read_bytes() == before
    assert _invoke_v3(media, "--replace") == 0
    assert v3_runtime[0] == [media, media]
    assert path.read_bytes() == before


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("replace", [False, True])
def test_v3_dry_run_no_runtime_inference_or_write(tmp_path, monkeypatch, v3_runtime, existing, replace):
    from chordflask_base import analysis_json_path

    media = _v3_media(tmp_path, chordino=existing)
    path = analysis_json_path(media)
    before = path.read_bytes() if existing else None
    v3_runtime[2].require_runtime = lambda: pytest.fail("runtime checked")
    v3_runtime[3].predict_media = lambda media: pytest.fail("inference ran")
    monkeypatch.setattr(analyze_cli, "_run_chordino", lambda *a, **kw: pytest.fail("analysis ran"))
    assert _invoke_v3(media, "--dry-run", *(["--replace"] if replace else [])) == 0
    assert (path.read_bytes() if path.exists() else None) == before


@pytest.mark.parametrize("failure", [ImportError("private V3 module absent"), RuntimeError("runtime unavailable"),
                                     ValueError("checkpoint hash differs")])
def test_v3_runtime_failure_preserves_analysis(tmp_path, v3_runtime, failure, capsys):
    from chordflask_base import analysis_json_path

    media = _v3_media(tmp_path)
    before = analysis_json_path(media).read_bytes()

    def fail():
        raise failure

    v3_runtime[2].require_runtime = fail
    assert _invoke_v3(media, "--replace") == 2
    assert analysis_json_path(media).read_bytes() == before
    assert v3_runtime[0] == []
    assert str(failure) in capsys.readouterr().err


@pytest.mark.parametrize("failure", [RuntimeError("V3 inference failed"), OSError("atomic save failed")])
def test_v3_prediction_or_save_failure_preserves_analysis(tmp_path, monkeypatch, v3_runtime, failure):
    from chordflask_base import analysis_json_path

    media = _v3_media(tmp_path)
    assert _invoke_v3(media) == 0
    before = analysis_json_path(media).read_bytes()

    def fail(*args):
        raise failure

    if isinstance(failure, OSError):
        monkeypatch.setattr("chordflask_base.write_atomic", fail)
    else:
        v3_runtime[3].predict_media = fail
    assert _invoke_v3(media, "--replace") == 1
    assert analysis_json_path(media).read_bytes() == before


def test_v3_directory_uses_normal_discovery(tmp_path, v3_runtime):
    from chordflask_base import ChordData, analysis_json_path

    for name in ("a.mp3", "a.mp4", "b.webm", "notes.txt"):
        media = tmp_path / name
        media.write_bytes(b"media")
        if media.suffix != ".txt":
            path = analysis_json_path(media)
            path.parent.mkdir(exist_ok=True)
            track = ChordData()
            track.set_chord_track("chordino", _CHORD)
            track.save_to_file(path)
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "ignored.mp4").write_bytes(b"media")
    assert _invoke_v3(tmp_path) == 0
    assert v3_runtime[0] == [tmp_path / "a.mp4", tmp_path / "b.webm"]


def test_v3_invalid_analysis_preserved(tmp_path, v3_runtime):
    from chordflask_base import analysis_json_path

    media = _v3_media(tmp_path)
    path = analysis_json_path(media)
    path.write_text("{broken")
    assert _invoke_v3(media) == 1
    assert path.read_text() == "{broken"
    assert not v3_runtime[0]


def test_v3_dry_run_existing_track_classification(tmp_path, v3_runtime, capsys):
    from chordflask_base import analysis_json_path

    media = _v3_media(tmp_path)
    assert _invoke_v3(media) == 0
    before = analysis_json_path(media).read_bytes()
    capsys.readouterr()
    assert _invoke_v3(media, "--dry-run") == 0
    assert "CURRENT" in capsys.readouterr().out
    assert _invoke_v3(media, "--dry-run", "--replace") == 0
    assert "REANALYZE" in capsys.readouterr().out
    assert v3_runtime[0] == [media]
    assert analysis_json_path(media).read_bytes() == before


@pytest.mark.parametrize("metadata", [{"input_sha256": "wrong"}, {},
                                      {"input_sha256": None}, {"input_sha256": []},
                                      None, [], "broken", 42])
def test_v3_stale_metadata_regenerates_without_touching_other_data(
    tmp_path, v3_runtime, capsys, metadata
):
    from chordflask_base import analysis_json_path, chord_input_sha256

    media = _v3_media(tmp_path)
    assert _invoke_v3(media) == 0
    path = analysis_json_path(media)
    data = json.loads(path.read_text())
    data["chord_tracks"]["chordflask_v3"]["metadata"] = metadata
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    capsys.readouterr()
    assert _invoke_v3(media, "--dry-run") == 0
    assert "STALE" in capsys.readouterr().out
    assert path.read_bytes() == before
    assert v3_runtime[0] == [media]
    assert _invoke_v3(media) == 0
    updated = json.loads(path.read_text())
    v3 = updated["chord_tracks"].pop("chordflask_v3")
    data["chord_tracks"].pop("chordflask_v3")
    assert updated == data
    assert v3["metadata"]["input_sha256"] == chord_input_sha256(data["chord_tracks"]["chordino"]["chords"])
    assert v3_runtime[0] == [media, media]
    capsys.readouterr()
    assert _invoke_v3(media, "--dry-run") == 0
    assert "CURRENT" in capsys.readouterr().out
    assert _invoke_v3(media) == 0
    assert v3_runtime[0] == [media, media]


def test_v3_missing_metadata_is_stale(tmp_path, v3_runtime, capsys):
    from chordflask_base import analysis_json_path

    media = _v3_media(tmp_path)
    assert _invoke_v3(media) == 0
    path = analysis_json_path(media)
    data = json.loads(path.read_text())
    del data["chord_tracks"]["chordflask_v3"]["metadata"]
    path.write_text(json.dumps(data))
    capsys.readouterr()
    assert _invoke_v3(media, "--dry-run") == 0
    assert "STALE" in capsys.readouterr().out
    assert _invoke_v3(media) == 0
    assert v3_runtime[0] == [media, media]


def test_v3_missing_canonical_input_is_stale(tmp_path, v3_runtime, capsys):
    from chordflask_base import analysis_json_path

    media = _v3_media(tmp_path)
    assert _invoke_v3(media) == 0
    path = analysis_json_path(media)
    data = json.loads(path.read_text())
    del data["chord_tracks"]["chordino"]
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    capsys.readouterr()
    assert _invoke_v3(media, "--dry-run") == 0
    assert "STALE" in capsys.readouterr().out
    assert path.read_bytes() == before


def test_v3_chordino_reanalysis_preserves_then_refreshes_stale_track(tmp_path, v3_runtime, capsys):
    from chordflask_base import ChordData, analysis_json_path
    media = _v3_media(tmp_path)
    assert _invoke_v3(media) == 0
    path = analysis_json_path(media)
    before = json.loads(path.read_text())
    replacement = tmp_path / "replacement.json"
    track = ChordData()
    track.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "D"}])
    track.set_rhythm_track("qm_barbeattracker", bpm=100, beat_times=[0.0, 0.6])
    track.save_to_file(replacement)
    from chordflask_base import ChordTrackRepository, preserve_analysis_user_data
    repository = ChordTrackRepository()
    refreshed = repository.load(replacement)
    preserve_analysis_user_data(repository.load(path), refreshed)
    repository.save(refreshed, replacement)
    path.write_bytes(replacement.read_bytes())
    stale = json.loads(path.read_text())
    assert stale["chord_tracks"]["chordflask_v3"] == before["chord_tracks"]["chordflask_v3"]
    capsys.readouterr()
    assert _invoke_v3(media, "--dry-run") == 0
    assert "STALE" in capsys.readouterr().out
    assert _invoke_v3(media) == 0
    updated = json.loads(path.read_text())
    assert updated["chord_tracks"]["chordflask_v3"]["metadata"]["input_sha256"] != before["chord_tracks"]["chordflask_v3"]["metadata"]["input_sha256"]
    updated["chord_tracks"].pop("chordflask_v3")
    stale["chord_tracks"].pop("chordflask_v3")
    assert updated == stale
    assert v3_runtime[0] == [media, media]


def test_v3_invalid_other_metadata_is_not_repaired(tmp_path, v3_runtime):
    from chordflask_base import analysis_json_path

    media = _v3_media(tmp_path)
    path = analysis_json_path(media)
    data = json.loads(path.read_text())
    data["chord_tracks"]["btc"]["metadata"] = None
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    assert _invoke_v3(media, "--dry-run") == 1
    assert _invoke_v3(media) == 1
    assert path.read_bytes() == before
    assert not v3_runtime[0]


def test_v3_missing_private_package_fails_without_generating_chordino(tmp_path, monkeypatch, capsys):
    from chordflask_base import analysis_json_path

    media = _v3_media(tmp_path, chordino=False)
    monkeypatch.setitem(sys.modules, "chordflask_v3", None)
    monkeypatch.delitem(sys.modules, "chordflask_v3.runtime", raising=False)
    monkeypatch.setattr(analyze_cli, "_run_chordino", lambda *a, **kw: pytest.fail("analysis ran"))
    assert _invoke_v3(media) == 2
    assert "runtime unavailable or invalid" in capsys.readouterr().err
    assert not analysis_json_path(media).exists()


def test_v3_chordino_failure_prevents_prediction(tmp_path, monkeypatch, v3_runtime):
    media = _v3_media(tmp_path, chordino=False)
    monkeypatch.setattr(analyze_cli, "_run_chordino", lambda *a, **kw: 1)
    assert _invoke_v3(media) == 1
    assert not v3_runtime[0]


def test_v3_canonical_change_during_prediction_is_not_overwritten(tmp_path, v3_runtime):
    from chordflask_base import analysis_json_path

    media = _v3_media(tmp_path)
    path = analysis_json_path(media)
    updated = json.loads(path.read_text())
    updated["chord_tracks"]["chordino"]["chords"] = [{"timestamp": 0.0, "chord": "D"}]
    changed = json.dumps(updated)
    predict = v3_runtime[3].predict_media

    def change(media):
        path.write_text(changed)
        return predict(media)

    v3_runtime[3].predict_media = change
    assert _invoke_v3(media) == 1
    assert path.read_text() == changed


# ── --source: Chordino on one Demucs stem ─────────────────────────────

from tests.test_stem_chord_analysis import REL_DIR, _song as _stem_song  # noqa: E402


def test_source_defaults_to_original_and_keeps_chordino_path(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(analyze_cli, "_run_chordino", lambda *a, **k: calls.append("chordino") or 0)
    monkeypatch.setattr(analyze_cli, "_run_stem_chordino", lambda *a, **k: calls.append("stem") or 0)
    with pytest.raises(SystemExit) as exc:
        analyze_cli.main([str(tmp_path)])
    assert exc.value.code == 0
    assert calls == ["chordino"]
    assert analyze_cli.build_parser().parse_args(["song.mp4"]).source == "original"


def test_source_rejected_with_non_chordino_analyzer(capsys):
    with pytest.raises(SystemExit) as exc:
        analyze_cli.main(["--analyzer", "btc", "--source", "other", "song.mp4"])
    assert exc.value.code == 2
    assert "--source" in capsys.readouterr().err


def test_source_rejects_unknown_stem():
    with pytest.raises(SystemExit) as exc:
        analyze_cli.build_parser().parse_args(["--source", "guitar", "song.mp4"])
    assert exc.value.code == 2


def _stem_status_dirs(tmp_path):
    from chordflask.stem_chord_analysis import analyze_stem_chords
    from tests.test_stem_chord_analysis import FakeAnalyzer

    dirs = {}
    for label in ("todo", "current", "stale", "nostems"):
        directory = tmp_path / label
        directory.mkdir()
        media, _ = _stem_song(directory, with_audio=label != "nostems")
        if label in ("current", "stale"):
            analyze_stem_chords(media, "other", analyzer=FakeAnalyzer())
        if label == "stale":
            from chordflask_base import ChordTrackRepository

            json_path = directory / ".chordflask" / "song.json"
            data = ChordTrackRepository().load(json_path)
            audio = data.audio_track_data("demucs:htdemucs")
            audio["tracks"]["other"]["sha256"] = "f" * 64
            data.set_audio_track("demucs:htdemucs", audio)
            data.save_to_file(json_path)
        dirs[label] = media
    return dirs


def test_stem_dry_run_labels(tmp_path, capsys):
    dirs = _stem_status_dirs(tmp_path)
    before = {label: (m.parent / ".chordflask" / "song.json").read_bytes() for label, m in dirs.items()}
    expected = {"todo": "TODO", "current": "CURRENT", "stale": "STALE", "nostems": "NO STEMS"}
    for label, media in dirs.items():
        assert analyze_cli._run_stem_chordino(media, "other", replace=False, dry_run=True) == 0
        assert expected[label] in capsys.readouterr().out
    after = {label: (m.parent / ".chordflask" / "song.json").read_bytes() for label, m in dirs.items()}
    assert after == before


def test_stem_run_skips_current_unless_replace(monkeypatch, tmp_path):
    dirs = _stem_status_dirs(tmp_path)
    calls = []
    monkeypatch.setattr(
        "chordflask.stem_chord_analysis.analyze_stem_chords",
        lambda media, stem: calls.append((Path(media).parent.name, stem)) or {"track_id": "x", "chords": 0},
    )
    assert analyze_cli._run_stem_chordino(dirs["current"], "other", replace=False, dry_run=False) == 0
    assert calls == []
    assert analyze_cli._run_stem_chordino(dirs["current"], "other", replace=True, dry_run=False) == 0
    assert analyze_cli._run_stem_chordino(dirs["stale"], "other", replace=False, dry_run=False) == 0
    assert analyze_cli._run_stem_chordino(dirs["todo"], "other", replace=False, dry_run=False) == 0
    assert calls == [("current", "other"), ("stale", "other"), ("todo", "other")]


def test_stem_run_counts_failures_and_returns_1(tmp_path, capsys):
    dirs = _stem_status_dirs(tmp_path)
    (dirs["todo"].parent / REL_DIR / "other.flac").unlink()
    assert analyze_cli._run_stem_chordino(dirs["todo"], "other", replace=False, dry_run=False) == 1
    captured = capsys.readouterr()
    assert "ERROR:" in captured.err
    assert "failed:     1" in captured.out


def test_stem_run_skips_songs_without_stems_or_analysis(tmp_path, capsys):
    dirs = _stem_status_dirs(tmp_path)
    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / "song.mp3").write_bytes(b"media")

    assert analyze_cli._run_stem_chordino(dirs["nostems"], "other", replace=False, dry_run=False) == 0
    out = capsys.readouterr().out
    assert "SKIP: no stems" in out and "skipped:    1" in out
    assert analyze_cli._run_stem_chordino(bare / "song.mp3", "other", replace=False, dry_run=True) == 0
    assert "NO ANALYSIS" in capsys.readouterr().out
    assert analyze_cli._run_stem_chordino(bare / "song.mp3", "other", replace=False, dry_run=False) == 0
    assert "SKIP: no analysis" in capsys.readouterr().out
