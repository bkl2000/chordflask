"""Recursive/retry workflow using temporary media and mocked generation only."""

import json
from pathlib import Path

import pytest

from chordflask_lyrics import batch, cli
from chordflask_lyrics.lrclib import LRCLIBError

REAL_GENERATE = cli.generate_file


@pytest.fixture
def generate(monkeypatch):
    calls = []
    outcomes = {}

    def fake(media, **options):
        calls.append((media, options))
        outcome = outcomes.get(media.name, "written")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome, "test result"
    monkeypatch.setattr(cli, "generate_file", fake)
    monkeypatch.setattr(cli, "LRCLIBClient", lambda: object())
    monkeypatch.setattr("chordflask_lyrics.lrclib.urlopen", lambda *a, **k: pytest.fail("network forbidden"))
    return calls, outcomes


def media(root, relative):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"synthetic media")
    return path


def run(root, *flags):
    return cli.run(cli.build_parser().parse_args([*flags, str(root)]))


def ledger(root):
    return json.loads(batch.state_path(root).read_text())


def test_recursive_discovery_is_nested_deterministic_supported_and_preferred(tmp_path, generate):
    paths = ["z.mp3", "nested/z.MP3", "nested/a.webm", "a.mp3", "a.mp4", "unsupported.wav",
             ".chordflask/extracted.mp3", "nested/.cache/hidden.mp4"]
    for path in paths:
        media(tmp_path, path)
    calls, _ = generate
    assert run(tmp_path, "--recursive") == 0
    assert [p.relative_to(tmp_path).as_posix() for p, _ in calls] == [
        "a.mp4", "nested/a.webm", "nested/z.MP3", "z.mp3",
    ]
    assert ledger(tmp_path)["failed"] == []


def test_plain_directory_remains_nonrecursive_and_single_file_unchanged(tmp_path, generate, capsys):
    root_media = media(tmp_path, "a.mp3")
    media(tmp_path, "nested/b.mp3")
    calls, _ = generate
    assert run(tmp_path) == 0
    assert [path for path, _ in calls] == [root_media]
    assert not batch.state_path(tmp_path).exists()
    calls.clear()
    assert run(root_media, "--force", "--tag", "Artist Song") == 0
    assert calls[0][1]["force"] is True and calls[0][1]["search_hint"] == "Artist Song"
    assert "1 written" in capsys.readouterr().out


def test_mixed_results_and_old_sidecar_failed_force_are_recorded(tmp_path, generate, capsys):
    calls, outcomes = generate
    for name in ("ok.mp3", "failed.mp3", "skipped.mp3"):
        media(tmp_path, name)
    old = tmp_path / "failed.cho"
    old.write_text("old sidecar")
    outcomes.update({"failed.mp3": LRCLIBError("HTTP 503"), "skipped.mp3": "skipped"})
    assert run(tmp_path, "--recursive", "--force") == 1
    captured = capsys.readouterr()
    assert "OK: 1\nFAILED: 1\nSKIPPED: 1" in captured.out
    assert "FAILED" in captured.err and "HTTP 503" in captured.err
    assert old.read_text() == "old sidecar"
    assert ledger(tmp_path)["failed"] == [{"path": str(tmp_path / "failed.mp3"), "reason": "HTTP 503"}]
    assert all(options["force"] for _, options in calls)


def test_retry_only_failures_preserves_generation_options_and_refreshes_errors(tmp_path, generate, capsys):
    calls, outcomes = generate
    for name in ("ok.mp3", "a.mp3", "b.mp3"):
        media(tmp_path, name)
    outcomes.update({"a.mp3": LRCLIBError("HTTP 503"), "b.mp3": ValueError("bad analysis")})
    assert run(tmp_path, "--recursive", "--force", "--lyrics", "lrclib:lrc",
               "--track", "btc", "--romanize", "--romanize-engine", "royin") == 1
    saved = ledger(tmp_path)
    assert saved["root"] == str(tmp_path)
    assert saved["options"] == {"force": True, "lyrics": ["lrclib", "lrc"], "track": "btc",
                                "romanize": True, "romanize_engine": "royin"}
    calls.clear()
    outcomes["a.mp3"] = "written"
    outcomes["b.mp3"] = LRCLIBError("HTTP 503 again")
    assert run(tmp_path, "--retry-failed") == 1
    assert [path.name for path, _ in calls] == ["a.mp3", "b.mp3"]
    for _, options in calls:
        assert options["force"] and options["romanize"]
        assert options["track"] == "btc" and options["romanize_engine"] == "royin"
        assert options["lyrics_sources"] == ("lrclib", "lrc")
        assert options["search_hint"] is None
    assert ledger(tmp_path)["failed"] == [{"path": str(tmp_path / "b.mp3"), "reason": "HTTP 503 again"}]
    calls.clear()
    outcomes["b.mp3"] = "written"
    assert run(tmp_path, "--retry-failed") == 0
    assert [p.name for p, _ in calls] == ["b.mp3"]
    assert ledger(tmp_path)["failed"] == []
    calls.clear()
    assert run(tmp_path, "--retry-failed") == 0
    assert calls == []
    assert "OK: 0\nFAILED: 0\nSKIPPED: 0" in capsys.readouterr().out


def test_missing_state_never_scans_or_generates(tmp_path, generate, monkeypatch, capsys):
    media(tmp_path, "a.mp3")
    monkeypatch.setattr(batch, "recursive_media", lambda root: pytest.fail("no full rescan"))
    assert run(tmp_path, "--retry-failed") == 0
    assert generate[0] == [] and not batch.state_path(tmp_path).exists()
    assert "nothing to retry" in capsys.readouterr().out


def test_deleted_failed_source_is_skipped_and_removed(tmp_path, generate, capsys):
    path = media(tmp_path, "gone.mp3")
    generate[1][path.name] = LRCLIBError("HTTP 503")
    assert run(tmp_path, "--recursive") == 1
    path.unlink()
    generate[0].clear()
    assert run(tmp_path, "--retry-failed") == 0
    assert generate[0] == [] and ledger(tmp_path)["failed"] == []
    assert "source no longer exists" in capsys.readouterr().out


@pytest.mark.parametrize("attack", ["outside", "relative", "traversal", "symlink", "root", "options", "json"])
def test_failure_ledger_injection_rejected_before_generation(tmp_path, generate, attack):
    root = tmp_path / "root"
    root.mkdir()
    local = media(root, "a.mp3")
    external = media(tmp_path, "outside.mp3")
    options = batch.generation_options(cli.build_parser().parse_args([str(root)]))
    batch.save_failures(root, options, [{"path": str(local), "reason": "HTTP 503"}])
    data = ledger(root)
    if attack == "outside":
        data["failed"][0]["path"] = str(external)
    elif attack == "relative":
        data["failed"][0]["path"] = "a.mp3"
    elif attack == "traversal":
        data["failed"][0]["path"] = str(root / ".." / "outside.mp3")
    elif attack == "symlink":
        local.unlink()
        local.symlink_to(external)
    elif attack == "root":
        data["root"] = str(tmp_path)
    elif attack == "options":
        data["options"]["force"] = "yes"
    batch.state_path(root).write_text("invalid JSON" if attack == "json" else json.dumps(data))
    assert run(root, "--retry-failed") == 2
    assert generate[0] == []
    assert external.read_bytes() == b"synthetic media"


@pytest.mark.parametrize("redirect", ["directory", "file"])
def test_redirected_state_storage_rejected(tmp_path, generate, redirect):
    root = tmp_path / "root"
    root.mkdir()
    media(root, "a.mp3")
    outside = tmp_path / "outside"
    outside.mkdir()
    if redirect == "directory":
        (root / ".chordflask").symlink_to(outside, target_is_directory=True)
    else:
        directory = root / ".chordflask" / batch.STATE_DIRECTORY
        directory.mkdir(parents=True)
        (directory / batch.STATE_NAME).symlink_to(outside / "state.json")
    assert run(root, "--recursive") == 2
    assert generate[0] == [] and list(outside.iterdir()) == []


def test_recursive_does_not_follow_external_symlinks(tmp_path, generate):
    root = tmp_path / "root"
    root.mkdir()
    external = media(tmp_path, "outside/song.mp3")
    (root / "linked").symlink_to(external.parent, target_is_directory=True)
    (root / "alias.mp3").symlink_to(external)
    assert run(root, "--recursive") == 0 and generate[0] == []


def test_atomic_state_failure_retains_old_ledger_and_cleans_temp(tmp_path, monkeypatch):
    options = batch.generation_options(cli.build_parser().parse_args([str(tmp_path)]))
    batch.save_failures(tmp_path, options, [])
    path = batch.state_path(tmp_path)
    original = path.read_bytes()
    real_replace = batch.os.replace
    observed = []

    def fail(source, target):
        observed.append(json.loads(Path(source).read_text()))
        assert Path(target).read_bytes() == original
        raise OSError("simulated rename failure")
    monkeypatch.setattr(batch.os, "replace", fail)
    with pytest.raises(OSError):
        batch.save_failures(tmp_path, options, [{"path": str(tmp_path / "song.mp3"), "reason": "failed"}])
    assert path.read_bytes() == original and observed[0]["failed"]
    assert not list(path.parent.glob(".lyrics-failures-*.tmp"))
    monkeypatch.setattr(batch.os, "replace", real_replace)
    batch.save_failures(tmp_path, options, [])
    assert json.loads(path.read_text())["failed"] == []


def test_dry_run_does_not_acknowledge_or_replace_saved_failures(tmp_path, generate, capsys):
    path = media(tmp_path, "a.mp3")
    generate[1][path.name] = LRCLIBError("HTTP 503")
    assert run(tmp_path, "--recursive") == 1
    original = batch.state_path(tmp_path).read_bytes()
    generate[1][path.name] = "dry-run"
    assert run(tmp_path, "--retry-failed", "--dry-run") == 0
    assert batch.state_path(tmp_path).read_bytes() == original
    assert "OK: 0\nFAILED: 0\nSKIPPED: 1" in capsys.readouterr().out


def test_batch_arguments_reject_single_file_tag_and_conflicting_modes(tmp_path, generate):
    path = media(tmp_path, "a.mp3")
    assert run(path, "--recursive") == 2
    assert run(tmp_path, "--recursive", "--tag", "Artist Song") == 2
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--recursive", "--retry-failed", str(tmp_path)])
    assert generate[0] == []


def test_recursive_writes_actual_temporary_sidecars_through_existing_generator(tmp_path, generate, monkeypatch):
    from chordflask.chordpro_song import read_chordpro
    from chordflask.filerepr import FileRepr
    from chordflask_base import ChordData
    from chordflask_lyrics.lrclib import SongIdentity

    monkeypatch.setattr(cli, "generate_file", REAL_GENERATE)
    monkeypatch.setattr(cli, "probe_media", lambda path: SongIdentity(title="Song", artist="Artist", duration=4))
    paths = [media(tmp_path, name) for name in ("root.mp3", "nested/child.mp3")]
    for path in paths:
        data = ChordData()
        data.set_chord_track("chordino", [{"timestamp": 0., "chord": "C"}])
        data.set_rhythm_track("qm_barbeattracker", bpm=60, meter_signature=4,
                              beat_times=[0., 1., 2., 3.], beat_numbers=[1, 2, 3, 4])
        data.save_to_file(FileRepr(path, create=True).get("json"))
        path.with_suffix(".lrc").write_text("[00:00.00]hello world\n[00:02.00]second line\n")
    assert run(tmp_path, "--recursive", "--lyrics", "lrc") == 0
    for path in paths:
        parsed = read_chordpro(path.with_suffix(".cho"))
        assert parsed["metadata"]["x_chordflask_generator"] == "ChordFlask Lyrics"
        assert any(block["type"] == "line" for block in parsed["blocks"])
    assert ledger(tmp_path)["failed"] == []


def test_ledger_cannot_overwrite_same_named_analysis(tmp_path, generate):
    path = media(tmp_path, "failures.mp3")
    analysis = tmp_path / ".chordflask" / "failures.json"
    analysis.parent.mkdir()
    analysis.write_bytes(b"preserved analysis sentinel")
    assert run(tmp_path, "--recursive") == 0
    assert analysis.read_bytes() == b"preserved analysis sentinel"
    assert ledger(tmp_path)["failed"] == []
    assert generate[0][0][0] == path


def test_runtime_generator_failure_is_persisted_and_does_not_stop_batch(tmp_path, generate):
    for name in ("failed.mp3", "ok.mp3"):
        media(tmp_path, name)
    generate[1]["failed.mp3"] = RuntimeError("generator runtime failure")
    assert run(tmp_path, "--recursive") == 1
    assert len(generate[0]) == 2
    assert ledger(tmp_path)["failed"] == [{
        "path": str(tmp_path / "failed.mp3"), "reason": "generator runtime failure",
    }]


def test_ledger_write_failure_reports_error_and_result_summary(tmp_path, generate, monkeypatch, capsys):
    media(tmp_path, "ok.mp3")

    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(batch, "save_failures", fail)
    assert run(tmp_path, "--recursive") == 1
    captured = capsys.readouterr()
    assert "OK: 1\nFAILED: 0\nSKIPPED: 0" in captured.out
    assert "could not persist" in captured.err
    assert not batch.state_path(tmp_path).exists()
