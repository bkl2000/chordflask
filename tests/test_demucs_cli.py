from chordflask_demucs import cli
from chordflask_demucs.audio import AudioFacts
from chordflask_demucs.discovery import DiscoveryError
from chordflask_demucs.runtime import RuntimeInfo
from chordflask_demucs.storage import DemucsStatus


def _runtime(tmp_path):
    return RuntimeInfo(tmp_path / "venv", tmp_path / "venv/bin/python", "4.0.1", "2.6.0")


def test_dry_run_reports_statuses_without_runtime_or_writes(monkeypatch, tmp_path, capsys):
    files = [tmp_path / "todo.mp3", tmp_path / "current.mp3", tmp_path / "stale.mp3"]
    statuses = iter(
        [
            DemucsStatus("TODO", "missing"),
            DemucsStatus("CURRENT", "complete"),
            DemucsStatus("STALE", "changed"),
        ]
    )
    monkeypatch.setattr(cli, "discover_target", lambda target: files)
    monkeypatch.setattr(cli, "classify", lambda path, **kwargs: next(statuses))
    monkeypatch.setattr(cli, "require_runtime", lambda: (_ for _ in ()).throw(AssertionError()))

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
    statuses = iter([DemucsStatus("CURRENT"), DemucsStatus("STALE")])
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
