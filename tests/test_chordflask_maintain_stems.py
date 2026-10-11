"""Tests for the ``chordflask-maintain stems`` report and cleanup."""

import fcntl
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]

from chordflask_base import ChordData, DEMUCS_STEM_NAMES  # noqa: E402

from chordflask_maintain import stems as stems_mod  # noqa: E402
from chordflask_maintain.stems import (  # noqa: E402
    DEMUCS_AUDIO_SET_ID,
    cleanup_orphan_stems,
    inspect_stems,
    remove_stems,
)

STEMS_REL = Path(".chordflask") / "stems" / "demucs" / "htdemucs" / "key" / "gen"


@pytest.fixture(autouse=True)
def isolate_queue_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("CHORDFLASK_QUEUE_DIR", str(tmp_path / "queue"))


def _audio_set(rel_dir: Path):
    tracks = {}
    for index, stem in enumerate(DEMUCS_STEM_NAMES):
        tracks[stem] = {
            "path": str(rel_dir / f"{stem}.flac"),
            "format": "flac",
            "sample_rate": 44100,
            "channels": 2,
            "sample_count": 44100,
            "duration": 1.0,
            "size": 100 + index,
            "sha256": f"{index + 1:064x}",
        }
    return {
        "provider": "demucs",
        "model": "htdemucs",
        "tracks": tracks,
        "metadata": {
            "source": {
                "sha256": "a" * 64,
                "size": 1000,
                "sample_rate": 44100,
                "channels": 2,
                "sample_count": 44100,
                "duration": 1.0,
            },
            "sync": {
                "reference": "canonical_extracted_audio",
                "start_sample": 0,
                "source_sample_count": 44100,
                "stem_sample_count": 44100,
                "max_tail_delta_samples": 2205,
                "tail_adjustment_samples": {
                    "bass": 0, "drums": 0, "other": 0, "vocals": 0,
                },
            },
            "source_timeline": {"available": False},
        },
    }


def _write_flac(media_root: Path, rel_dir: Path, stem: str, content=b"flac"):
    path = media_root / rel_dir / f"{stem}.flac"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _write_song_with_set(media_root: Path, *, name="song.mp3", rel_dir=None, set_data=None):
    media = media_root / name
    media.write_bytes(b"not decoded by this module")
    analysis_dir = media_root / ".chordflask"
    analysis_dir.mkdir(exist_ok=True)
    data = ChordData()
    data.set_audio_track(DEMUCS_AUDIO_SET_ID, set_data or _audio_set(rel_dir or STEMS_REL))
    data.save_to_file(analysis_dir / f"{media.stem}.json")
    return media


def _write_full_song(media_root: Path, *, name="song.mp3", rel_dir=None):
    rel = rel_dir or STEMS_REL
    _write_song_with_set(media_root, name=name, rel_dir=rel)
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(media_root, rel, stem)
    return media_root / name


def _write_owned_song(media_root: Path, *, name="song.mp3"):
    media = media_root / name
    rel = (
        Path(".chordflask")
        / "stems"
        / "demucs"
        / "htdemucs"
        / stems_mod._media_key(media)
        / "current"
    )
    return _write_full_song(media_root, name=name, rel_dir=rel)


def _run_maintain_cli(capsys, *args):
    from chordflask_maintain import cli

    with pytest.raises(SystemExit) as exc:
        cli.main(list(args))
    return exc.value.code, capsys.readouterr()


# ── report ────────────────────────────────────────────────────────────


def test_report_no_stem_storage(tmp_path):
    report = inspect_stems(tmp_path)
    assert report.exists is False
    text = stems_mod.format_stems_report(report)
    assert "no Demucs stem storage" in text


def test_report_complete_set(tmp_path):
    _write_full_song(tmp_path)

    report = inspect_stems(tmp_path)

    assert report.exists is True
    assert len(report.records) == 1
    assert report.records[0].status == "complete"
    assert report.records[0].media_stem == "song"
    assert report.total_bytes == 4 * 4  # four "flac" bytes
    assert report.orphans == []
    text = stems_mod.format_stems_report(report)
    assert "song: complete" in text
    assert "orphan generations: 0" in text


def test_report_incomplete_set_missing_file(tmp_path):
    _write_full_song(tmp_path)
    (tmp_path / STEMS_REL / "vocals.flac").unlink()

    report = inspect_stems(tmp_path)

    assert report.records[0].status == "incomplete"
    assert report.records[0].missing_files == ["vocals"]
    text = stems_mod.format_stems_report(report)
    assert "missing: vocals" in text


def test_report_orphan_generation(tmp_path):
    _write_full_song(tmp_path)
    orphan = tmp_path / ".chordflask" / "stems" / "demucs" / "htdemucs" / "old-key" / "old-gen"
    (orphan / "orphan.flac").parent.mkdir(parents=True, exist_ok=True)
    (orphan / "orphan.flac").write_bytes(b"xxxxxx")

    report = inspect_stems(tmp_path)

    assert len(report.orphans) == 1
    assert report.orphans[0][1] == 6
    assert report.records[0].status == "complete"
    text = stems_mod.format_stems_report(report)
    assert "orphan generations: 1" in text


def test_report_ignores_non_analysis_json(tmp_path):
    _write_full_song(tmp_path)
    (tmp_path / ".chordflask" / "song.training.json").write_text(
        '{"some": "training data"}', encoding="utf-8"
    )

    report = inspect_stems(tmp_path)

    assert report.invalid == []
    assert len(report.records) == 1


def test_report_invalid_analysis_json(tmp_path):
    _write_full_song(tmp_path)
    (tmp_path / ".chordflask" / "broken.json").write_text("{not json", encoding="utf-8")

    report = inspect_stems(tmp_path)

    assert len(report.invalid) == 1
    text = stems_mod.format_stems_report(report)
    assert "invalid JSON" in text


# ── cleanup ───────────────────────────────────────────────────────────


def test_cleanup_removes_only_orphans(tmp_path):
    _write_full_song(tmp_path)
    orphan = tmp_path / ".chordflask" / "stems" / "demucs" / "htdemucs" / "old-key" / "old-gen"
    (orphan / "orphan.flac").parent.mkdir(parents=True, exist_ok=True)
    (orphan / "orphan.flac").write_bytes(b"xxxxxx")
    json_before = (tmp_path / ".chordflask" / "song.json").read_bytes()

    result = cleanup_orphan_stems(tmp_path)

    assert not result.refused
    assert len(result.removed) == 1
    assert not orphan.exists()
    # referenced generation survives
    assert (tmp_path / STEMS_REL / "vocals.flac").exists()
    # analysis JSON is byte-for-byte unchanged
    assert (tmp_path / ".chordflask" / "song.json").read_bytes() == json_before


def test_cleanup_dry_run_has_no_side_effects(tmp_path):
    _write_full_song(tmp_path)
    orphan = tmp_path / ".chordflask" / "stems" / "demucs" / "htdemucs" / "old-key" / "old-gen"
    (orphan / "orphan.flac").parent.mkdir(parents=True, exist_ok=True)
    (orphan / "orphan.flac").write_bytes(b"xxxxxx")

    result = cleanup_orphan_stems(tmp_path, dry_run=True)

    assert len(result.removed) == 1
    assert orphan.exists()


def test_cleanup_refuses_on_invalid_analysis_json(tmp_path):
    _write_full_song(tmp_path)
    orphan = tmp_path / ".chordflask" / "stems" / "demucs" / "htdemucs" / "old-key" / "old-gen"
    (orphan / "orphan.flac").parent.mkdir(parents=True, exist_ok=True)
    (orphan / "orphan.flac").write_bytes(b"xxxxxx")
    (tmp_path / ".chordflask" / "broken.json").write_text("{not json", encoding="utf-8")

    result = cleanup_orphan_stems(tmp_path)

    assert result.refused is True
    assert orphan.exists()


def test_cleanup_refuses_when_analysis_json_listing_errors(tmp_path, monkeypatch):
    _write_full_song(tmp_path)
    orphan = tmp_path / ".chordflask" / "stems" / "demucs" / "htdemucs" / "old-key" / "old-gen"
    (orphan / "orphan.flac").parent.mkdir(parents=True, exist_ok=True)
    (orphan / "orphan.flac").write_bytes(b"xxxxxx")

    def error_listing(_chordflask, *, fail_closed=False):
        assert fail_closed is True
        raise PermissionError("analysis directory unreadable")

    monkeypatch.setattr(stems_mod, "_iter_json_files", error_listing)

    result = cleanup_orphan_stems(tmp_path)

    assert result.refused is True
    assert "cannot inspect analysis JSON files" in result.reason
    assert orphan.exists()


def test_cleanup_refuses_when_registered_generation_cannot_be_resolved(
    tmp_path, monkeypatch
):
    _write_full_song(tmp_path)
    referenced = tmp_path / STEMS_REL
    monkeypatch.setattr(stems_mod, "_referenced_generation", lambda media, data: None)

    result = cleanup_orphan_stems(tmp_path)

    assert result.refused is True
    assert "cannot resolve registered stem generation" in result.reason
    assert referenced.exists()


def test_cli_invalid_analysis_refusal_suggests_validation(tmp_path, capsys):
    _write_full_song(tmp_path)
    broken = tmp_path / ".chordflask" / "broken.json"
    broken.write_text("{not json", encoding="utf-8")

    code, captured = _run_maintain_cli(
        capsys, "stems", "cleanup", str(tmp_path), "--orphans"
    )

    assert code == 1
    assert "broken.json" in captured.out
    assert "orphan references cannot be determined safely" in captured.out
    assert f"chordflask-maintain validate {tmp_path}" in captured.out
    assert f"chordflask-maintain stems report {tmp_path}" in captured.out
    assert "nothing deleted" in captured.out


def test_cli_unresolved_generation_refusal_is_actionable(
    tmp_path, monkeypatch, capsys
):
    _write_full_song(tmp_path)
    monkeypatch.setattr(stems_mod, "_referenced_generation", lambda media, data: None)

    code, captured = _run_maintain_cli(
        capsys, "stems", "cleanup", str(tmp_path), "--orphans"
    )

    assert code == 1
    assert "song.json" in captured.out
    assert "orphan status cannot be proven safely" in captured.out
    assert f"chordflask-maintain validate {tmp_path}" in captured.out
    assert f"chordflask-maintain stems report {tmp_path}" in captured.out
    assert "nothing deleted" in captured.out


def test_cleanup_skips_symlink_generation(tmp_path):
    _write_full_song(tmp_path)
    outside = tmp_path / "outside.flac"
    outside.write_bytes(b"escape")
    link_parent = tmp_path / ".chordflask" / "stems" / "demucs" / "htdemucs" / "link-key"
    link_parent.mkdir(parents=True, exist_ok=True)
    link = link_parent / "link-gen"
    link.symlink_to(tmp_path)

    cleanup_orphan_stems(tmp_path)

    assert outside.exists()
    assert link.is_symlink()


def test_cleanup_never_deletes_outside_stems_root(tmp_path):
    _write_full_song(tmp_path)
    # A stray directory directly under .chordflask (not under stems/) must be untouched.
    stray = tmp_path / ".chordflask" / "not-stems"
    stray.mkdir()
    (stray / "keep.txt").write_text("keep")

    result = cleanup_orphan_stems(tmp_path)

    assert (stray / "keep.txt").exists()
    assert result.removed == []


def test_cleanup_refuses_uninspectable_demucs_lock(tmp_path):
    _write_full_song(tmp_path)
    chordflask = tmp_path / ".chordflask"
    (chordflask / "song.demucs.lock").mkdir()
    orphan = chordflask / "stems" / "demucs" / "htdemucs" / "old-key" / "old-gen"
    (orphan / "orphan.flac").parent.mkdir(parents=True, exist_ok=True)
    (orphan / "orphan.flac").write_bytes(b"xxxxxx")

    result = cleanup_orphan_stems(tmp_path)

    assert result.refused is True
    assert "cannot inspect Demucs lock" in result.reason
    assert orphan.exists()


def test_cli_uninspectable_demucs_lock_is_actionable(tmp_path, capsys):
    _write_full_song(tmp_path)
    chordflask = tmp_path / ".chordflask"
    (chordflask / "song.demucs.lock").mkdir()

    code, captured = _run_maintain_cli(
        capsys, "stems", "cleanup", str(tmp_path), "--orphans"
    )

    assert code == 1
    assert "cannot inspect Demucs lock" in captured.out
    assert "lock state could not be verified safely" in captured.out
    assert "Check permissions and process state, then retry." in captured.out
    assert f"chordflask-maintain stems report {tmp_path}" in captured.out
    assert "nothing deleted" in captured.out


def test_cleanup_refuses_active_demucs_lock(tmp_path):
    _write_full_song(tmp_path)
    chordflask = tmp_path / ".chordflask"
    lock_path = chordflask / "song.demucs.lock"
    orphan = chordflask / "stems" / "demucs" / "htdemucs" / "old-key" / "old-gen"
    (orphan / "orphan.flac").parent.mkdir(parents=True, exist_ok=True)
    (orphan / "orphan.flac").write_bytes(b"xxxxxx")

    lock_handle = lock_path.open("a+")
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        result = cleanup_orphan_stems(tmp_path)
    finally:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()

    assert result.refused is True
    assert "Demucs process holds a lock" in result.reason
    assert orphan.exists()


def test_cli_active_demucs_lock_has_retry_guidance(tmp_path, capsys):
    _write_full_song(tmp_path)
    lock_path = tmp_path / ".chordflask" / "song.demucs.lock"
    lock_handle = lock_path.open("a+")
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        code, captured = _run_maintain_cli(
            capsys, "stems", "cleanup", str(tmp_path), "--orphans"
        )
    finally:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()

    assert code == 1
    assert "Demucs process holds a lock" in captured.out
    assert "nothing deleted" in captured.out
    assert "Retry after Demucs processing has finished or stopped." in captured.out
    assert f"chordflask-maintain stems report {tmp_path}" in captured.out


def test_cli_active_worker_stem_refusal_has_retry_guidance(tmp_path, capsys):
    _write_full_song(tmp_path)
    queue = tmp_path / "queue"
    queue.mkdir()
    lock_handle = (queue / "analysis_worker.lock").open("a+")
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        code, captured = _run_maintain_cli(
            capsys, "stems", "cleanup", str(tmp_path), "--orphans"
        )
    finally:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()

    assert code == 1
    assert "an analysis worker is active" in captured.out
    assert "nothing deleted" in captured.out
    assert "Retry after analysis has finished or stopped." in captured.out
    assert f"chordflask-maintain stems report {tmp_path}" in captured.out


def test_cleanup_requires_orphans_flag(tmp_path):
    from chordflask_maintain import cli

    with pytest.raises(SystemExit) as exc:
        cli.main(["stems", "cleanup", str(tmp_path)])
    assert exc.value.code == 2


# ── explicit removal ──────────────────────────────────────────────────


def test_remove_song_completes_task_and_preserves_unrelated_data(tmp_path, capsys):
    media = _write_owned_song(tmp_path)
    other_media = _write_owned_song(tmp_path, name="other.mp3")
    other_key = stems_mod.stems_root(tmp_path) / stems_mod._media_key(other_media)
    obsolete = (
        tmp_path
        / ".chordflask"
        / "stems"
        / "demucs"
        / "htdemucs"
        / stems_mod._media_key(media)
        / "obsolete"
    )
    _write_flac(tmp_path, obsolete.relative_to(tmp_path), "vocals", b"old")
    json_path = tmp_path / ".chordflask" / "song.json"
    document = json.loads(json_path.read_text(encoding="utf-8"))
    document["user_data"] = {"edited": "keep"}
    document["chord_tracks"]["btc"] = {
        "chords": [{"timestamp": 0.0, "chord": "C"}],
        "metadata": {"keep": True},
    }
    document["lyrics_extension"] = {"text": "keep"}
    json_path.write_text(json.dumps(document), encoding="utf-8")
    journal = tmp_path / ".chordflask" / "journals" / "song.journal.json"
    journal.parent.mkdir()
    journal.write_text("keep", encoding="utf-8")
    unrelated = tmp_path / ".chordflask" / "unrelated.dat"
    unrelated.write_text("keep", encoding="utf-8")

    code, captured = _run_maintain_cli(
        capsys, "stems", "remove", str(media)
    )

    assert code == 0
    assert media.exists()
    assert other_media.exists()
    assert len(list(other_key.glob("current/*.flac"))) == 4
    assert not obsolete.parent.exists()
    after = json.loads(json_path.read_text(encoding="utf-8"))
    assert DEMUCS_AUDIO_SET_ID not in after["audio_tracks"]
    for key in ("user_data", "chord_tracks", "lyrics_extension"):
        assert after[key] == document[key]
    assert journal.read_text(encoding="utf-8") == "keep"
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert "removed  Demucs stem registration" in captured.out
    assert "PRESERVED: original media" in captured.out


def test_remove_song_is_idempotent(tmp_path, capsys):
    media = _write_owned_song(tmp_path)
    assert _run_maintain_cli(capsys, "stems", "remove", str(media))[0] == 0

    code, captured = _run_maintain_cli(capsys, "stems", "remove", str(media))

    assert code == 0
    assert "UNCHANGED: no registered or stored Demucs stems" in captured.out


def test_remove_song_dry_run_reports_every_file_without_changes(tmp_path, capsys):
    media = _write_owned_song(tmp_path)
    json_before = (tmp_path / ".chordflask" / "song.json").read_bytes()
    paths_before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    code, captured = _run_maintain_cli(
        capsys, "stems", "remove", str(media), "--dry-run"
    )

    assert code == 0
    for stem in DEMUCS_STEM_NAMES:
        assert f"{stem}.flac" in captured.out
    assert "would remove  Demucs stem registration" in captured.out
    assert (tmp_path / ".chordflask" / "song.json").read_bytes() == json_before
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == paths_before
    key_dir = stems_mod.stems_root(tmp_path) / stems_mod._media_key(media)
    assert len(list(key_dir.glob("current/*.flac"))) == 4


def test_remove_song_retry_finishes_after_file_deletion_failure(
    tmp_path, monkeypatch
):
    media = _write_owned_song(tmp_path)
    original_unlink = Path.unlink
    failed_once = False

    def fail_one_file(path, *args, **kwargs):
        nonlocal failed_once
        if path.name == "vocals.flac" and not failed_once:
            failed_once = True
            raise PermissionError("simulated denial")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_one_file)
    first = remove_stems(media)

    assert first.failures
    assert first.removals[0].registration_removed is True
    assert not stems_mod.ChordTrackRepository().load(
        tmp_path / ".chordflask" / "song.json"
    ).has_audio_track(DEMUCS_AUDIO_SET_ID)

    second = remove_stems(media)

    assert not second.failures
    assert not (stems_mod.stems_root(tmp_path) / stems_mod._media_key(media)).exists()


def test_remove_song_reports_key_directory_failure_and_retry_finishes(
    tmp_path, monkeypatch
):
    media = _write_owned_song(tmp_path)
    key_dir = stems_mod.stems_root(tmp_path) / stems_mod._media_key(media)
    original_rmdir = Path.rmdir
    failed_once = False

    def fail_key_directory(path, *args, **kwargs):
        nonlocal failed_once
        if path == key_dir and not failed_once:
            failed_once = True
            raise PermissionError("simulated directory denial")
        return original_rmdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "rmdir", fail_key_directory)
    first = remove_stems(media)

    assert first.failures == [
        f"could not remove song stem directory {key_dir}: simulated directory denial"
    ]
    assert key_dir.is_dir()

    second = remove_stems(media)

    assert not second.failures
    assert second.removals[0].key_directory_removed is True
    assert not key_dir.exists()


def test_remove_song_refuses_symlink_inside_owned_storage(tmp_path):
    media = _write_owned_song(tmp_path)
    generation = stems_mod.stems_root(tmp_path) / stems_mod._media_key(media) / "current"
    (generation / "vocals.flac").unlink()
    outside = tmp_path / "outside.flac"
    outside.write_bytes(b"keep")
    (generation / "vocals.flac").symlink_to(outside)

    result = remove_stems(media)

    assert result.refused is True
    assert outside.read_bytes() == b"keep"
    assert stems_mod.ChordTrackRepository().load(
        tmp_path / ".chordflask" / "song.json"
    ).has_audio_track(DEMUCS_AUDIO_SET_ID)


def test_remove_song_refuses_active_demucs_processing(tmp_path):
    media = _write_owned_song(tmp_path)
    lock_handle = stems_mod._demucs_lock_path(media).open("a+")
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        result = remove_stems(media)
    finally:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()

    assert result.refused is True
    assert "Demucs processing is active" in result.removals[0].reason
    assert len(list((stems_mod.stems_root(tmp_path) / stems_mod._media_key(media)).glob("current/*.flac"))) == 4


def test_remove_song_succeeds_while_global_worker_lock_is_held(tmp_path, capsys):
    media = _write_owned_song(tmp_path)
    queue = tmp_path / "queue"
    queue.mkdir()
    lock_handle = (queue / "analysis_worker.lock").open("a+")
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        code, captured = _run_maintain_cli(
            capsys, "stems", "remove", str(media)
        )
    finally:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()

    assert code == 0
    assert "worker" not in captured.out.lower()
    assert not (stems_mod.stems_root(tmp_path) / stems_mod._media_key(media)).exists()


def test_remove_song_refuses_invalid_analysis_without_deleting_stems(tmp_path):
    media = _write_owned_song(tmp_path)
    (tmp_path / ".chordflask" / "song.json").write_text(
        "{invalid", encoding="utf-8"
    )

    result = remove_stems(media)

    assert result.refused is True
    assert "invalid analysis JSON" in result.removals[0].reason
    assert len(list((stems_mod.stems_root(tmp_path) / stems_mod._media_key(media)).glob("current/*.flac"))) == 4


def test_remove_same_stem_media_never_removes_other_filename_owner(tmp_path):
    requested = tmp_path / "song.mp3"
    requested.write_bytes(b"mp3")
    owner = _write_owned_song(tmp_path, name="song.mp4")
    requested_rel = (
        Path(".chordflask")
        / "stems"
        / "demucs"
        / "htdemucs"
        / stems_mod._media_key(requested)
        / "obsolete"
    )
    _write_flac(tmp_path, requested_rel, "vocals", b"old")

    result = remove_stems(requested)

    assert not result.refused
    assert not (tmp_path / requested_rel).exists()
    owner_key = stems_mod.stems_root(tmp_path) / stems_mod._media_key(owner)
    assert len(list(owner_key.glob("current/*.flac"))) == 4
    assert stems_mod.ChordTrackRepository().load(
        tmp_path / ".chordflask" / "song.json"
    ).has_audio_track(DEMUCS_AUDIO_SET_ID)


def test_remove_all_requires_explicit_flag_and_removes_each_song(tmp_path, capsys):
    first = _write_owned_song(tmp_path, name="first.mp3")
    second = _write_owned_song(tmp_path, name="second.webm")

    error_code, _ = _run_maintain_cli(capsys, "stems", "remove", str(tmp_path))
    code, captured = _run_maintain_cli(
        capsys, "stems", "remove", "--all", str(tmp_path)
    )

    assert error_code == 2
    assert code == 0
    assert str(first) in captured.out
    assert str(second) in captured.out
    assert "songs 2 changed" in captured.out


# ── CLI dispatch ──────────────────────────────────────────────────────


def test_stems_subcommand_is_listed_in_help(capsys):
    from chordflask_maintain import cli

    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    assert "stems" in capsys.readouterr().out


def test_stems_report_dispatches(capsys, tmp_path):
    from chordflask_maintain import cli

    with pytest.raises(SystemExit) as exc:
        cli.main(["stems", "report", str(tmp_path)])
    assert exc.value.code == 0
    assert "no Demucs stem storage" in capsys.readouterr().out


# ── framework-free boundary ───────────────────────────────────────────


def test_stems_module_has_no_demucs_or_torch_import():
    source = (REPO_ROOT / "chordflask_maintain" / "stems.py").read_text(encoding="utf-8")
    for forbidden in (
        "import torch",
        "import demucs",
        "from chordflask_demucs",
        "import chordflask_demucs",
        "import librosa",
    ):
        assert forbidden not in source
