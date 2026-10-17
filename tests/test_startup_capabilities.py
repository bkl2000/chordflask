"""Startup information must not turn into a blocking runtime diagnostic."""

import sys
import time
from pathlib import Path

import pytest

from chordflask import app, media_preparation, stem_preparation, startup_capabilities
from chordflask.analysis_worker import AnalysisWorker

LYRICS_COMMAND = media_preparation.lyrics_command
SCORE_COMMAND = media_preparation.score_command


def report(available=True, cuda=False, reason=""):
    return {"available": available, "cuda": cuda, "reason": reason}


@pytest.fixture
def server(monkeypatch, tmp_path):
    monkeypatch.setenv("CHORDFLASK_QUEUE_DIR", str(tmp_path / "queue"))
    monkeypatch.setenv("CHORDFLASK_BTC_VENV", str(tmp_path / "missing-btc"))
    monkeypatch.setenv("CHORDFLASK_DEMUCS_VENV", str(tmp_path / "demucs"))
    monkeypatch.setenv("CHORDFLASK_QWEN3_VENV", str(tmp_path / "qwen"))
    monkeypatch.setattr(media_preparation, "_capability_cache", {})
    monkeypatch.setattr(stem_preparation, "_capability_cache", {"at": 0, "value": None})
    monkeypatch.setattr(media_preparation, "lyrics_command", lambda: None)
    monkeypatch.setattr(media_preparation, "score_command", lambda: None)
    return app.FlaskMP4App()


def output_rows(server, capsys):
    server.print_startup_message("127.0.0.1", 5057)
    output = capsys.readouterr().out
    rows = {}
    for line in output.split("Capabilities:\n", 1)[1].splitlines():
        if line.startswith("  "):
            label, status = line.strip().split("  ", 1)
            rows[label] = status.strip()
    return output, rows


@pytest.mark.parametrize("frozen", [False, True])
@pytest.mark.parametrize("cuda", [False, True])
def test_available_runtimes_and_cached_device(server, monkeypatch, capsys, frozen, cuda):
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    for name in ("lyrics", "btc"):
        media_preparation._capability_cache[name] = {"at": time.monotonic(), "value": report()}
    monkeypatch.setattr(media_preparation, "score_command", lambda: Path("/score/bin/helper"))
    media_preparation._capability_cache["score"] = {"at": time.monotonic(), "value": report()}
    stem_preparation._capability_cache.update(at=time.monotonic(), value=report(cuda=cuda))
    monkeypatch.setattr(AnalysisWorker, "is_running", lambda queue: True)

    output, rows = output_rows(server, capsys)

    assert output.index("ChordFlask ") < output.index("Open:") < output.index("Capabilities:")
    assert rows["Chordino / QM analysis"] == "available"
    assert rows["Analysis worker"] == "running"
    assert rows["Lyrics V1 generation"] == "available"
    assert rows["BTC chords"] == "available"
    assert rows["Demucs stem generation"] == f"available ({'CUDA' if cuda else 'CPU'})"
    assert rows["Piano Score generation"] == "available (Transkun; experimental)"
    assert rows["Chord exports"] == "available (Markdown, PDF, ChordPro, MIDI)"
    assert "MP3, MP4, WebM" in rows["Playback"]
    assert "CLI only; experimental" in rows["Lyrics V2 / Qwen generation"]
    assert ">=1024 px" in output


def test_missing_producers_do_not_disable_existing_data(server, monkeypatch, capsys):
    stem_preparation._capability_cache.update(
        at=time.monotonic(), value=report(False, reason="Demucs not installed")
    )
    _, rows = output_rows(server, capsys)

    for label in ("Lyrics V1 generation", "BTC chords", "Demucs stem generation", "Piano Score generation"):
        assert rows[label].startswith("not installed")
    assert "last check failed: Demucs not installed" in rows["Demucs stem generation"]
    assert rows["Lyrics display"] == "supported (.cho, .v2.cho)"
    assert rows["Existing stem playback"] == "supported"
    assert rows["Piano Score display"] == "supported (experimental)"


@pytest.mark.parametrize("frozen", [False, True])
@pytest.mark.parametrize("helpers_present", [False, True])
def test_startup_never_launches_runtime_subprocesses(
    server, monkeypatch, capsys, frozen, helpers_present
):
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    helper = Path("/external/bin/helper") if helpers_present else None
    monkeypatch.setattr(media_preparation, "lyrics_command", lambda: helper)
    monkeypatch.setattr(media_preparation, "score_command", lambda: helper)

    def unexpected(*args, **kwargs):
        pytest.fail("startup must not run an expensive probe or subprocess")

    monkeypatch.setattr(media_preparation.subprocess, "run", unexpected)
    monkeypatch.setattr(stem_preparation, "_probe_capability_uncached", unexpected)
    monkeypatch.setattr(server, "setup_vamp_plugins", unexpected)
    _, rows = output_rows(server, capsys)

    assert rows["Lyrics V1 generation"] == "not installed"
    assert rows["Piano Score generation"].startswith("not installed")
    assert rows["Demucs stem generation"] == "not installed"
    if helpers_present:
        assert "score" not in media_preparation._capability_cache
    assert stem_preparation._capability_cache["value"] is None


def test_stale_results_are_not_reported_and_gui_still_probes(server, monkeypatch, capsys):
    monkeypatch.setattr(media_preparation, "score_command", lambda: Path("/score/bin/helper"))
    media_preparation._capability_cache["score"] = {"at": 0, "value": report()}
    stem_preparation._capability_cache.update(at=0, value=report(cuda=True))
    _, rows = output_rows(server, capsys)
    assert rows["Piano Score generation"].startswith("not installed")
    assert rows["Demucs stem generation"] == "not installed"

    calls = []

    def check(*args, **kwargs):
        calls.append(args)
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(media_preparation.subprocess, "run", check)
    monkeypatch.setattr(stem_preparation, "_probe_capability_uncached", lambda: report(cuda=True))
    assert media_preparation.score_capability()["available"] is True
    assert len(calls) == 1
    assert stem_preparation.gui_capability() == report(cuda=True)


def test_cheap_lyrics_detection_does_not_replace_gui_freshness_check(server, monkeypatch):
    from chordflask_lyrics import freshness

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(media_preparation, "lyrics_command", lambda: Path("/lyrics/bin/helper"))
    calls = []

    def check(runtime, source):
        calls.append(runtime)
        return report(False, reason="Lyrics runtime needs update")

    monkeypatch.setattr(freshness, "check_runtime", check)
    assert media_preparation.lyrics_capability(check_runtime=False)["available"] is None
    assert calls == []
    assert media_preparation.lyrics_capability()["available"] is False
    assert calls == [Path("/lyrics")]


def test_missing_ffmpeg_preserves_warning(server, monkeypatch, capsys):
    def missing():
        raise RuntimeError("missing ffmpeg")

    monkeypatch.setattr(app, "require_system_ffmpeg", missing)
    output, rows = output_rows(server, capsys)
    assert "WARNING: ffmpeg not found" in output
    assert rows["Chordino / QM analysis"] == "unavailable (FFmpeg missing)"


def test_quiet_startup_skips_capabilities(server, monkeypatch, capsys):
    quiet = app.FlaskMP4App(quiet=True)

    def unexpected(**kwargs):
        pytest.fail("quiet startup must not check capabilities")

    monkeypatch.setattr(quiet, "_print_startup_capabilities", unexpected)
    quiet.print_startup_message("127.0.0.1", 5057)
    assert "Capabilities:" not in capsys.readouterr().out


@pytest.mark.parametrize("executable", [None, "/tmp/standalone/chordflask", "/opt/chordflask/chordflask"])
def test_missing_vamp_preserves_installation_hints(server, monkeypatch, capsys, executable):
    from chordflask import vamp_runtime

    monkeypatch.setattr(sys, "frozen", executable is not None, raising=False)
    if executable:
        monkeypatch.setattr(sys, "executable", executable)
    monkeypatch.setattr(vamp_runtime.vamp, "list_plugins", lambda: [])
    server.setup_vamp_plugins()
    output, rows = output_rows(server, capsys)
    assert rows["Chordino / QM analysis"] == "unavailable (required Vamp plugins missing)"
    assert "WARNING:" in output
    assert "install_vamp.sh" in output if executable else "make plugins" in output
    assert "--check-vamp" in output
    assert rows["Chord exports"].startswith("available")


@pytest.mark.parametrize("running", [False, True])
def test_no_worker_main_reports_opt_out(server, monkeypatch, capsys, running):
    monkeypatch.setattr(app, "FlaskMP4App", lambda **kwargs: server)
    monkeypatch.setattr(server, "setup_vamp_plugins", lambda: None)
    monkeypatch.setattr(AnalysisWorker, "is_running", lambda queue: running)
    monkeypatch.setattr(server, "run", lambda **kwargs: server.print_startup_message("127.0.0.1", 5057))
    app.main(["--no-worker"])
    output = capsys.readouterr().out
    expected = "running (external; automatic start disabled)" if running else "disabled (--no-worker)"
    assert expected in output
    assert server.worker_supervisor is None


def test_worker_starting_is_not_reported_as_running(server, monkeypatch, capsys):
    monkeypatch.setattr(AnalysisWorker, "is_running", lambda queue: False)
    server.worker_supervisor = type("Supervisor", (), {"child_running": lambda self: True})()
    _, rows = output_rows(server, capsys)
    assert rows["Analysis worker"] == "starting"


@pytest.mark.parametrize("arguments", [["--worker"], ["--check-vamp"], ["--version"], ["--help"], ["--analyze", "--help"]])
def test_noninteractive_modes_skip_overview(server, monkeypatch, capsys, arguments):
    from chordflask import vamp_runtime

    monkeypatch.setattr(app, "FlaskMP4App", lambda **kwargs: server)
    monkeypatch.setattr(server, "setup_vamp_plugins", lambda: None)
    monkeypatch.setattr(AnalysisWorker, "run_forever", lambda self: 0)
    monkeypatch.setattr(vamp_runtime, "require_vamp_plugins", lambda: vamp_runtime.REQUIRED_PLUGINS)

    def unexpected(*args, **kwargs):
        pytest.fail("noninteractive invocation must not build a capability overview")

    monkeypatch.setattr(server, "_print_startup_capabilities", unexpected)
    with pytest.raises(SystemExit) as caught:
        app.main(arguments)
    assert caught.value.code == 0
    assert "Capabilities:" not in capsys.readouterr().out


def installation_file(path, *, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    if executable:
        path.chmod(0o755)
    return path


@pytest.fixture
def installed_runtimes(server, monkeypatch, tmp_path):
    from chordflask_btc import runtime as btc

    lyrics = tmp_path / "lyrics"
    score = tmp_path / "score"
    for runtime in (lyrics, score, tmp_path / "demucs", tmp_path / "qwen"):
        installation_file(runtime / "bin/python", executable=True)
    lyrics_helper = installation_file(lyrics / "bin/chordflask-genlyrics", executable=True)
    score_helper = installation_file(score / "bin/chordflask-score", executable=True)
    monkeypatch.setattr(media_preparation, "lyrics_command", lambda: lyrics_helper)
    monkeypatch.setattr(media_preparation, "score_command", lambda: score_helper)
    files = [
        lyrics / "lib/python3.12/site-packages/chordflask_lyrics/qwen3_worker.py",
        tmp_path / "demucs/lib/python3.14/site-packages/demucs/separate.py",
        tmp_path / "demucs/lib/python3.14/site-packages/torch/__init__.py",
        tmp_path / "qwen/lib/python3.12/site-packages/qwen_asr/__init__.py",
        tmp_path / "qwen/lib/python3.12/site-packages/torch/__init__.py",
    ]
    for model in ("Qwen3-ASR-1.7B", "Qwen3-ForcedAligner-0.6B"):
        files.extend(tmp_path / "qwen/models" / model / name
                     for name in ("config.json", "model.safetensors"))
    files.extend(btc.btc_dir() / name for name in (*btc.PREDICTOR_FILES, btc.CHECKPOINT_NAME))
    for path in files:
        installation_file(path)
    installation_file(btc.venv_python(), executable=True)
    installation_file(btc.wrapper_path(), executable=True)
    return tmp_path


@pytest.mark.parametrize("frozen", [False, True])
def test_installed_files_without_probes(installed_runtimes, server, monkeypatch, capsys, frozen):
    import builtins
    import subprocess
    import threading

    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] in {"torch", "demucs", "transkun", "qwen_asr"}:
            pytest.fail(f"startup imported heavy runtime: {name}")
        return original_import(name, *args, **kwargs)

    def unexpected(*args, **kwargs):
        pytest.fail("startup must not launch processes, threads or runtime probes")

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(subprocess, "Popen", unexpected)
    monkeypatch.setattr(subprocess, "run", unexpected)
    monkeypatch.setattr(threading.Thread, "start", unexpected)
    monkeypatch.setattr(stem_preparation, "_probe_capability_uncached", unexpected)
    for name in ("lyrics_capability", "btc_capability", "score_capability"):
        monkeypatch.setattr(media_preparation, name, unexpected)
    _, rows = output_rows(server, capsys)
    assert rows["Lyrics V1 generation"] == "installed (not verified)"
    assert rows["Lyrics V2 / Qwen generation"] == "installed (CLI only; experimental; not verified)"
    assert rows["BTC chords"] == "installed (not verified)"
    assert rows["Demucs stem generation"] == "installed (not verified)"
    assert rows["Piano Score generation"] == "installed (Transkun; experimental; not verified)"
    assert "CUDA" not in " ".join(rows.values())
    assert media_preparation._capability_cache == {}
    assert stem_preparation._capability_cache == {"at": 0, "value": None}


@pytest.mark.parametrize("name,relative", [
    ("lyrics", "lyrics/bin/chordflask-genlyrics"),
    ("score", "score/bin/python"),
    ("score", "score/bin/chordflask-score"),
    ("demucs", "demucs/bin/python"),
    ("demucs", "demucs/lib/python3.14/site-packages/demucs/separate.py"),
    ("demucs", "demucs/lib/python3.14/site-packages/torch/__init__.py"),
    ("qwen", "qwen/bin/python"),
    ("qwen", "lyrics/bin/python"),
    ("qwen", "lyrics/lib/python3.12/site-packages/chordflask_lyrics/qwen3_worker.py"),
    ("qwen", "qwen/lib/python3.12/site-packages/qwen_asr/__init__.py"),
    ("qwen", "qwen/models/Qwen3-ASR-1.7B/config.json"),
    ("qwen", "qwen/models/Qwen3-ForcedAligner-0.6B/model.safetensors"),
    ("btc", "missing-btc/share/chordflask-btc/btc_model_large_voca.pt"),
])
def test_incomplete_installations(installed_runtimes, name, relative):
    (installed_runtimes / relative).unlink()
    assert startup_capabilities.runtime_status(name).startswith("not installed")


@pytest.mark.parametrize("name", ["lyrics", "score", "btc", "demucs", "qwen"])
def test_unexecutable_interpreters_or_helpers(installed_runtimes, name):
    relative = {"lyrics": "lyrics/bin/chordflask-genlyrics", "score": "score/bin/python",
                "btc": "missing-btc/bin/python", "demucs": "demucs/bin/python",
                "qwen": "qwen/bin/python"}[name]
    (installed_runtimes / relative).chmod(0o644)
    assert startup_capabilities.runtime_status(name).startswith("not installed")


def test_file_inspection_failure_is_not_checked(server, monkeypatch):
    def denied():
        raise PermissionError("cannot inspect runtime")

    monkeypatch.setattr(startup_capabilities, "_qwen_installed", denied)
    assert startup_capabilities.runtime_status("qwen").startswith("not checked")


def test_failed_probe_is_preserved_without_claiming_availability(installed_runtimes):
    media_preparation._capability_cache["score"] = {
        "at": time.monotonic(), "value": report(False, reason="Score runtime is incomplete")
    }
    assert startup_capabilities.runtime_status("score") == (
        "installed (Transkun; experimental; not verified; last check failed: Score runtime is incomplete)"
    )


@pytest.mark.parametrize("frozen", [False, True])
def test_existing_helper_path_conventions(server, monkeypatch, tmp_path, frozen):
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(media_preparation, "lyrics_command", LYRICS_COMMAND)
    monkeypatch.setattr(media_preparation, "score_command", SCORE_COMMAND)
    for kind, helper in (("LYRICS", "chordflask-genlyrics"), ("SCORE", "chordflask-score")):
        runtime = tmp_path / kind
        monkeypatch.setenv(f"CHORDFLASK_{kind}_VENV", str(runtime))
        installation_file(runtime / "bin/python", executable=True)
        installation_file(runtime / "bin" / helper, executable=True)
        assert startup_capabilities.runtime_status(kind.lower()).startswith("installed (")


@pytest.mark.parametrize("name", ["lyrics", "btc", "demucs", "score"])
def test_fresh_success_skips_file_detection(server, monkeypatch, name):
    def unexpected():
        pytest.fail("fresh successful capability cache must take precedence")

    monkeypatch.setattr(startup_capabilities, f"_{name}_installed", unexpected)
    cache = {"at": time.monotonic(), "value": report(cuda=True)}
    if name == "demucs":
        stem_preparation._capability_cache.update(cache)
    else:
        media_preparation._capability_cache[name] = cache
    assert startup_capabilities.runtime_status(name).startswith("available")


def test_installed_snapshot_does_not_enable_gui(installed_runtimes, monkeypatch):
    from chordflask_lyrics import freshness

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    for name in ("lyrics", "score", "demucs"):
        assert startup_capabilities.runtime_status(name).startswith("installed (")
    calls = []

    def fail_probe(*args, **kwargs):
        calls.append(args)
        return type("Result", (), {"returncode": 1})()

    monkeypatch.setattr(media_preparation.subprocess, "run", fail_probe)
    monkeypatch.setattr(freshness, "check_runtime", lambda *args: report(False, reason="stale Lyrics"))
    monkeypatch.setattr(stem_preparation, "_probe_capability_uncached", lambda: report(False))
    assert media_preparation.lyrics_capability()["available"] is False
    assert media_preparation.score_capability()["available"] is False
    assert stem_preparation.gui_capability()["available"] is False
    assert len(calls) == 1
