from chordflask_demucs import cli
from chordflask_demucs.audio import AudioFacts
from chordflask_demucs.discovery import DiscoveryError
from chordflask_demucs.runtime import DemucsRuntimeError, RuntimeInfo
from chordflask_demucs.runner import DemucsProcessError
from chordflask_demucs.storage import DemucsBusyError, DemucsStatus


def _runtime(tmp_path):
    return RuntimeInfo(tmp_path / "venv", tmp_path / "venv/bin/python", "4.0.1", "2.6.0")


def test_dry_run_reports_statuses_and_probes_runtime_for_current(monkeypatch, tmp_path, capsys):
    files = [tmp_path / "todo.mp3", tmp_path / "current.mp3", tmp_path / "stale.mp3"]
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(cli, "discover_target", lambda target: files)
    monkeypatch.setattr(cli, "require_runtime", lambda: runtime)
    monkeypatch.setattr(cli, "resolve_device", lambda d, r: "cpu")

    def fake_classify(path, runtime=None, device="auto"):
        if path.name == "todo.mp3":
            return DemucsStatus("TODO", "missing")
        if path.name == "current.mp3":
            return DemucsStatus("CURRENT", "provisional" if runtime is None else "complete")
        return DemucsStatus("STALE", "changed")

    monkeypatch.setattr(cli, "classify", fake_classify)

    code = cli.run(tmp_path, replace=False, dry_run=True, device="auto")

    output = capsys.readouterr().out
    assert code == 0
    assert "TODO" in output
    assert "CURRENT" in output
    assert "STALE" in output


def test_batch_processes_todo_continues_and_reports_stale(monkeypatch, tmp_path, capsys):
    files = [tmp_path / "todo.mp3", tmp_path / "current.mp3", tmp_path / "stale.mp3"]
    statuses = iter(
        [
            DemucsStatus("TODO", "missing"),
            DemucsStatus("CURRENT", "complete"),
            DemucsStatus("STALE", "changed"),
        ]
    )
    processed = []
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(cli, "discover_target", lambda target: files)
    monkeypatch.setattr(cli, "classify", lambda path, **kwargs: next(statuses))
    monkeypatch.setattr(cli, "require_runtime", lambda: runtime)
    monkeypatch.setattr(
        cli,
        "_process_one",
        lambda path, runtime, device, replace: processed.append(path),
    )

    code = cli.run(tmp_path, replace=False, dry_run=False, device="cpu")

    output = capsys.readouterr()
    assert code == 1
    assert processed == [files[0]]
    assert "Use --replace" in output.out


def test_replace_processes_current_and_stale(monkeypatch, tmp_path):
    files = [tmp_path / "current.mp3", tmp_path / "stale.mp3"]
    processed = []
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(cli, "discover_target", lambda target: files)
    monkeypatch.setattr(cli, "require_runtime", lambda: runtime)
    monkeypatch.setattr(cli, "resolve_device", lambda d, r: "cpu")

    def fake_classify(path, runtime=None, device="auto"):
        if path.name == "current.mp3":
            return DemucsStatus("CURRENT", "provisional" if runtime is None else "complete")
        return DemucsStatus("STALE", "changed")

    monkeypatch.setattr(cli, "classify", fake_classify)
    monkeypatch.setattr(
        cli,
        "_process_one",
        lambda path, runtime, device, replace: processed.append(path),
    )

    assert cli.run(tmp_path, replace=True, dry_run=False, device="cpu") == 0
    assert processed == files


def test_invalid_target_returns_two(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        cli,
        "discover_target",
        lambda target: (_ for _ in ()).throw(DiscoveryError("missing")),
    )

    assert cli.run(tmp_path / "missing", replace=False, dry_run=True, device="auto") == 2
    assert "missing" in capsys.readouterr().err


def test_process_one_validates_and_passes_one_complete_stage_to_publisher(monkeypatch, tmp_path):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"source")
    runtime = _runtime(tmp_path)
    facts = AudioFacts("wav", "pcm_s16le", 44100, 2, 44100, 1.0)
    flac_facts = AudioFacts("flac", "flac", 44100, 2, 44100, 1.0)
    published = {}

    monkeypatch.setattr(cli, "classify", lambda path, **kwargs: DemucsStatus("TODO"))
    monkeypatch.setattr(cli, "probe_source_timeline", lambda path: {"available": False})
    monkeypatch.setattr(cli, "extract_canonical_audio", lambda source, output: output.write_bytes(b"wav"))
    monkeypatch.setattr(cli, "probe_canonical_wav", lambda path: facts)

    def fake_demucs(source, raw_dir, runtime, device):
        result_dir = raw_dir / "htdemucs" / "source"
        result_dir.mkdir(parents=True)
        paths = {}
        for stem in ("bass", "drums", "other", "vocals"):
            path = result_dir / f"{stem}.wav"
            path.write_bytes(b"wav")
            paths[stem] = path
        return paths

    monkeypatch.setattr(cli, "run_demucs", fake_demucs)
    monkeypatch.setattr(cli, "probe_audio", lambda path: flac_facts if path.suffix == ".flac" else facts)
    monkeypatch.setattr(cli, "validate_raw_stems", lambda source, stems: {stem: 0 for stem in stems})
    monkeypatch.setattr(cli, "validate_normalized_stems", lambda source, stems: None)
    monkeypatch.setattr(
        cli, "convert_wav_to_flac", lambda source, output, target_sample_count: output.write_bytes(b"flac")
    )

    def fake_publish(path, **kwargs):
        published.update(kwargs)
        published["stems"] = {item.name for item in kwargs["staged_dir"].iterdir()}
        return path.parent / "song.json"

    monkeypatch.setattr(cli, "publish_set", fake_publish)

    result = cli._process_one(media, runtime, device="cpu")

    assert result.name == "song.json"
    assert set(published["stem_facts"]) == {"bass", "drums", "other", "vocals"}
    assert published["stems"] == {
        "bass.flac",
        "drums.flac",
        "other.flac",
        "vocals.flac",
    }


def test_provisional_current_is_reclassified_with_runtime_and_device(monkeypatch, tmp_path, capsys):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"source")
    runtime = _runtime(tmp_path)
    calls = []

    def fake_classify(path, runtime=None, device="auto"):
        calls.append((runtime, device))
        if runtime is None:
            return DemucsStatus("CURRENT", "provisional")
        return DemucsStatus("CURRENT", "validated")

    monkeypatch.setattr(cli, "discover_target", lambda target: [media])
    monkeypatch.setattr(cli, "classify", fake_classify)
    monkeypatch.setattr(cli, "require_runtime", lambda: runtime)
    monkeypatch.setattr(cli, "resolve_device", lambda d, r: "cpu")

    code = cli.run(tmp_path, replace=False, dry_run=True, device="auto")

    assert code == 0
    assert calls == [(None, "auto"), (runtime, "cpu")]
    assert "CURRENT" in capsys.readouterr().out


def test_todo_dry_run_is_lazy(monkeypatch, tmp_path):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"source")
    monkeypatch.setattr(cli, "discover_target", lambda target: [media])
    monkeypatch.setattr(cli, "classify", lambda path, **kwargs: DemucsStatus("TODO"))
    monkeypatch.setattr(cli, "require_runtime", lambda: (_ for _ in ()).throw(AssertionError("runtime must not load")))

    assert cli.run(tmp_path, replace=False, dry_run=True, device="auto") == 0


def test_error_classification_is_lazy(monkeypatch, tmp_path):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"source")
    monkeypatch.setattr(cli, "discover_target", lambda target: [media])
    monkeypatch.setattr(cli, "classify", lambda path, **kwargs: DemucsStatus("ERROR", "bad"))
    monkeypatch.setattr(cli, "require_runtime", lambda: (_ for _ in ()).throw(AssertionError("runtime must not load")))

    assert cli.run(tmp_path, replace=False, dry_run=True, device="auto") == 0


def test_resolved_device_passed_to_process_one(monkeypatch, tmp_path):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"source")
    runtime = _runtime(tmp_path)
    captured = {}
    monkeypatch.setattr(cli, "discover_target", lambda target: [media])
    monkeypatch.setattr(cli, "classify", lambda path, **kwargs: DemucsStatus("TODO"))
    monkeypatch.setattr(cli, "require_runtime", lambda: runtime)
    monkeypatch.setattr(cli, "resolve_device", lambda d, r: "cuda")

    def fake_process_one(path, runtime, device, replace):
        captured["device"] = device
        return media.parent / "song.json"

    monkeypatch.setattr(cli, "_process_one", fake_process_one)

    assert cli.run(tmp_path, replace=False, dry_run=False, device="auto") == 0
    assert captured["device"] == "cuda"


def test_device_difference_remains_current_without_replace_prompt(monkeypatch, tmp_path, capsys):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"source")
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(cli, "discover_target", lambda target: [media])

    def fake_classify(path, runtime=None, device="auto"):
        if runtime is None:
            return DemucsStatus("CURRENT", "provisional")
        return DemucsStatus(
            "CURRENT", "valid stem set; generated on cuda, current device cpu"
        )

    monkeypatch.setattr(cli, "classify", fake_classify)
    monkeypatch.setattr(cli, "require_runtime", lambda: runtime)
    monkeypatch.setattr(cli, "resolve_device", lambda d, r: "cpu")

    code = cli.run(tmp_path, replace=False, dry_run=False, device="auto")

    assert code == 0
    output = capsys.readouterr().out
    assert "CURRENT: valid stem set; generated on cuda, current device cpu" in output
    assert "Use --replace" not in output


def test_provisional_current_with_broken_runtime_becomes_error(monkeypatch, tmp_path, capsys):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"source")
    monkeypatch.setattr(cli, "discover_target", lambda target: [media])
    monkeypatch.setattr(cli, "classify", lambda path, **kwargs: DemucsStatus("CURRENT", "provisional"))
    monkeypatch.setattr(
        cli,
        "require_runtime",
        lambda: (_ for _ in ()).throw(DemucsRuntimeError("Demucs runtime not installed")),
    )

    code = cli.run(tmp_path, replace=False, dry_run=True, device="auto")

    assert code == 0
    captured = capsys.readouterr()
    assert "ERROR" in captured.out
    assert "make demucs-check" in captured.err
    assert "make setup-demucs" in captured.err


def test_missing_runtime_has_setup_and_check_guidance(monkeypatch, tmp_path, capsys):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"source")
    monkeypatch.setattr(cli, "discover_target", lambda target: [media])
    monkeypatch.setattr(cli, "classify", lambda path, **kwargs: DemucsStatus("TODO"))
    monkeypatch.setattr(
        cli,
        "require_runtime",
        lambda: (_ for _ in ()).throw(DemucsRuntimeError("runtime missing")),
    )

    code = cli.run(tmp_path, replace=False, dry_run=False, device="auto")

    assert code == 1
    err = capsys.readouterr().err
    assert "runtime missing" in err
    assert "make demucs-check" in err
    assert "make setup-demucs" in err


def test_lock_conflict_has_retry_guidance(monkeypatch, tmp_path, capsys):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"source")
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(cli, "discover_target", lambda target: [media])
    monkeypatch.setattr(cli, "classify", lambda path, **kwargs: DemucsStatus("TODO"))
    monkeypatch.setattr(cli, "require_runtime", lambda: runtime)
    monkeypatch.setattr(cli, "resolve_device", lambda device, info: "cpu")
    monkeypatch.setattr(
        cli,
        "_process_one",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            DemucsBusyError("Demucs processing is already running")
        ),
    )

    code = cli.run(media, replace=False, dry_run=False, device="auto")

    assert code == 1
    err = capsys.readouterr().err
    assert "already running" in err
    assert "Retry after the other Demucs process" in err
    assert "delete" not in err.lower()


def test_invalid_analysis_has_safe_inspection_guidance(monkeypatch, tmp_path, capsys):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"source")
    monkeypatch.setattr(cli, "discover_target", lambda target: [media])
    monkeypatch.setattr(
        cli,
        "classify",
        lambda path, **kwargs: DemucsStatus("ERROR", "analysis JSON is invalid: bad data"),
    )

    code = cli.run(media, replace=False, dry_run=False, device="auto")

    assert code == 1
    captured = capsys.readouterr()
    assert "analysis JSON is invalid" in captured.out
    assert f"chordflask-maintain validate {tmp_path}" in captured.err
    assert f"chordflask-maintain stems report {tmp_path}" in captured.err


def test_stale_stems_have_inspection_and_regeneration_guidance(
    monkeypatch, tmp_path, capsys
):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"source")
    monkeypatch.setattr(cli, "discover_target", lambda target: [media])
    monkeypatch.setattr(
        cli,
        "classify",
        lambda path, **kwargs: DemucsStatus("STALE", "vocals stem is missing"),
    )

    code = cli.run(media, replace=False, dry_run=False, device="auto")

    assert code == 1
    err = capsys.readouterr().err
    assert f"chordflask-maintain stems report {tmp_path}" in err
    assert f"chordflask-demucs --replace {media}" in err


def test_cuda_process_error_suggests_supported_cpu_command(
    monkeypatch, tmp_path, capsys
):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"source")
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(cli, "discover_target", lambda target: [media])
    monkeypatch.setattr(cli, "classify", lambda path, **kwargs: DemucsStatus("TODO"))
    monkeypatch.setattr(cli, "require_runtime", lambda: runtime)
    monkeypatch.setattr(cli, "resolve_device", lambda device, info: "cuda")
    monkeypatch.setattr(
        cli,
        "_process_one",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            DemucsProcessError("CUDA device is unavailable")
        ),
    )

    code = cli.run(media, replace=False, dry_run=False, device="cuda")

    assert code == 1
    err = capsys.readouterr().err
    assert "CUDA device is unavailable" in err
    assert f"chordflask-demucs --device cpu {media}" in err
