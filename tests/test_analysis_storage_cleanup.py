import fcntl
import os
import time

import pytest


from chordflask_maintain.storage import (  # noqa: E402
    cleanup_cached_audio,
    cleanup_corrupt_backups,
    cleanup_orphan_temp,
)


def _write(path, size=10):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def _old_mtime(path, days=40):
    atime = time.time()
    os.utime(path, (atime, atime - days * 86400))


@pytest.fixture(autouse=True)
def isolate_queue(monkeypatch, tmp_path):
    monkeypatch.setenv("CHORDFLASK_QUEUE_DIR", str(tmp_path / "queue"))


# ── orphan temp cleanup ─────────────────────────────────────────────


def test_orphan_analyze_directory_removed(tmp_path):
    media = tmp_path / "album"
    orphan = media / ".chordflask" / ".song.analyze-abc"
    _write(orphan / "song.json", 20)

    result = cleanup_orphan_temp(media)

    assert result.removed_count == 1
    assert result.removed_bytes == 20
    assert not orphan.exists()


def test_orphan_reanalyze_directory_removed(tmp_path):
    media = tmp_path / "album"
    orphan = media / ".chordflask" / ".song.reanalyze-xyz"
    _write(orphan / "song.json", 30)

    result = cleanup_orphan_temp(media)

    assert result.removed_count == 1
    assert not orphan.exists()


def test_convert_temp_file_removed(tmp_path):
    media = tmp_path / "album"
    temp = _write(media / ".chordflask" / ".song.convert-abc123.mp3", 50)

    result = cleanup_orphan_temp(media)

    assert result.removed_count == 1
    assert result.removed_bytes == 50
    assert not temp.exists()


def test_analysis_json_with_convert_stem_not_removed(tmp_path):
    media = tmp_path / "album"
    analysis = _write(media / ".chordflask" / "song.convert-demo.json", 40)

    result = cleanup_orphan_temp(media)

    assert result.removed_count == 0
    assert analysis.exists()


def test_similarly_named_non_temp_files_not_removed(tmp_path):
    media = tmp_path / "album"
    store = media / ".chordflask"
    cache = _write(store / "song.convert-demo.mp3", 30)
    xml = _write(store / "song.convert-demo.xml", 20)
    non_hidden_mp3 = _write(store / "song.convert-abc123.mp3", 40)

    result = cleanup_orphan_temp(media)

    assert result.removed_count == 0
    assert cache.exists()
    assert xml.exists()
    assert non_hidden_mp3.exists()


def test_unrelated_hidden_directory_untouched(tmp_path):
    media = tmp_path / "album"
    other = media / ".chordflask" / ".hidden"
    other.mkdir(parents=True)

    cleanup_orphan_temp(media)

    assert other.exists()


def test_similarly_named_non_matching_dir_untouched(tmp_path):
    media = tmp_path / "album"
    not_temp = media / ".chordflask" / ".song.analyze"
    not_temp.mkdir(parents=True)

    cleanup_orphan_temp(media)

    assert not_temp.exists()


def test_symlink_matching_temp_pattern_not_followed(tmp_path):
    media = tmp_path / "album"
    store = media / ".chordflask"
    store.mkdir(parents=True)
    target = _write(tmp_path / "target.bin", 100)
    link = store / ".song.analyze-link"
    link.symlink_to(target)

    cleanup_orphan_temp(media)

    assert target.exists()
    assert link.is_symlink()


def test_orphan_temp_refused_while_worker_active(tmp_path):
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()

    media = tmp_path / "album"
    orphan = media / ".chordflask" / ".song.analyze-abc"
    _write(orphan / "song.json", 20)

    lock_handle = (queue_dir / "analysis_worker.lock").open("a+")
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        result = cleanup_orphan_temp(media)
    finally:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()

    assert result.refused is True
    assert result.removed_count == 0
    assert orphan.exists()


def test_orphan_cleanup_a_does_not_affect_b(tmp_path):
    orphan_a = tmp_path / "a" / ".chordflask" / ".a.analyze-1"
    orphan_b = tmp_path / "b" / ".chordflask" / ".b.analyze-1"
    _write(orphan_a / "a.json", 10)
    _write(orphan_b / "b.json", 10)

    cleanup_orphan_temp(tmp_path / "a")

    assert not orphan_a.exists()
    assert orphan_b.exists()


# ── cached audio cleanup ────────────────────────────────────────────


def test_cached_audio_for_video_source_removed(tmp_path):
    media = tmp_path / "album"
    _write(media / "song.mp4", 5)
    cache = _write(media / ".chordflask" / "song.mp3", 100)
    analysis = _write(media / ".chordflask" / "song.json", 40)

    result = cleanup_cached_audio(media)

    assert result.removed_count == 1
    assert result.removed_bytes == 100
    assert not cache.exists()
    assert analysis.exists()


def test_cached_audio_webm_source_removed(tmp_path):
    media = tmp_path / "album"
    _write(media / "song.webm", 5)
    cache = _write(media / ".chordflask" / "song.mp3", 100)

    cleanup_cached_audio(media)

    assert not cache.exists()


def test_mp3_without_video_source_untouched(tmp_path):
    media = tmp_path / "album"
    unverified = _write(media / ".chordflask" / "song.mp3", 100)

    result = cleanup_cached_audio(media)

    assert result.removed_count == 0
    assert unverified.exists()


def test_source_mp3_untouched(tmp_path):
    media = tmp_path / "album"
    source = _write(media / "song.mp3", 100)

    result = cleanup_cached_audio(media)

    assert result.removed_count == 0
    assert source.exists()


def test_non_mp3_file_untouched(tmp_path):
    media = tmp_path / "album"
    _write(media / "song.mp4", 5)
    other = _write(media / ".chordflask" / "song.mid", 100)

    cleanup_cached_audio(media)

    assert other.exists()


def test_cached_audio_symlink_not_followed(tmp_path):
    media = tmp_path / "album"
    _write(media / "song.mp4", 5)
    store = media / ".chordflask"
    store.mkdir(parents=True)
    target = _write(tmp_path / "target.mp3", 100)
    link = store / "song.mp3"
    link.symlink_to(target)

    cleanup_cached_audio(media)

    assert link.is_symlink()
    assert target.exists()


def test_cached_audio_cleanup_a_does_not_affect_b(tmp_path):
    _write(tmp_path / "a" / "song.mp4", 5)
    _write(tmp_path / "b" / "song.mp4", 5)
    cache_a = _write(tmp_path / "a" / ".chordflask" / "song.mp3", 10)
    cache_b = _write(tmp_path / "b" / ".chordflask" / "song.mp3", 20)

    cleanup_cached_audio(tmp_path / "a")

    assert not cache_a.exists()
    assert cache_b.exists()


def test_cached_audio_refused_while_worker_active(tmp_path):
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()

    media = tmp_path / "album"
    _write(media / "song.mp4", 5)
    cache = _write(media / ".chordflask" / "song.mp3", 100)

    lock_handle = (queue_dir / "analysis_worker.lock").open("a+")
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        result = cleanup_cached_audio(media)
    finally:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()

    assert result.refused is True
    assert result.removed_count == 0
    assert cache.exists()


# ── corrupt backup retention ────────────────────────────────────────


def _corrupt_name(stem="song"):
    return f"{stem}.corrupt-20260101T123456123456Z-abcdef12.json"


def test_old_corrupt_backup_removed(tmp_path):
    media = tmp_path / "album"
    backup = _write(media / ".chordflask" / _corrupt_name(), 60)
    _old_mtime(backup)

    result = cleanup_corrupt_backups(media, older_than_days=30)

    assert result.removed_count == 1
    assert result.removed_bytes == 60
    assert not backup.exists()


def test_recent_corrupt_backup_retained(tmp_path):
    media = tmp_path / "album"
    backup = _write(media / ".chordflask" / _corrupt_name(), 60)

    result = cleanup_corrupt_backups(media, older_than_days=30)

    assert result.removed_count == 0
    assert backup.exists()


def test_valid_analysis_json_retained(tmp_path):
    media = tmp_path / "album"
    analysis = _write(media / ".chordflask" / "song.json", 40)

    cleanup_corrupt_backups(media, older_than_days=30)

    assert analysis.exists()


def test_arbitrary_json_named_corrupt_retained(tmp_path):
    media = tmp_path / "album"
    not_backup = _write(media / ".chordflask" / "corrupt-test.json", 40)
    _old_mtime(not_backup)

    cleanup_corrupt_backups(media, older_than_days=30)

    assert not_backup.exists()


def test_malformed_corrupt_filename_retained(tmp_path):
    media = tmp_path / "album"
    malformed = _write(media / ".chordflask" / "song.corrupt-20260101.json", 40)
    _old_mtime(malformed)

    cleanup_corrupt_backups(media, older_than_days=30)

    assert malformed.exists()


def test_corrupt_symlink_retained(tmp_path):
    media = tmp_path / "album"
    store = media / ".chordflask"
    store.mkdir(parents=True)
    target = _write(tmp_path / "backup.json", 60)
    link = store / _corrupt_name()
    link.symlink_to(target)

    cleanup_corrupt_backups(media, older_than_days=30)

    assert link.is_symlink()
    assert target.exists()


def test_corrupt_backup_requires_positive_age(tmp_path):
    media = tmp_path / "album"
    media.mkdir()

    with pytest.raises(ValueError):
        cleanup_corrupt_backups(media, older_than_days=0)
    with pytest.raises(ValueError):
        cleanup_corrupt_backups(media, older_than_days=-1)


def test_corrupt_backup_byte_and_count(tmp_path):
    media = tmp_path / "album"
    b1 = _write(media / ".chordflask" / _corrupt_name("a"), 10)
    b2 = _write(media / ".chordflask" / _corrupt_name("b"), 20)
    _old_mtime(b1)
    _old_mtime(b2)

    result = cleanup_corrupt_backups(media, older_than_days=30)

    assert result.removed_count == 2
    assert result.removed_bytes == 30


# ── scope / safety ──────────────────────────────────────────────────


def test_missing_chordflask_is_noop(tmp_path):
    media = tmp_path / "album"
    media.mkdir()

    result = cleanup_orphan_temp(media)
    assert result.removed_count == 0
    assert result.refused is False


def test_chordy_ignored(tmp_path):
    media = tmp_path / "album"
    media.mkdir()
    orphan = _write(media / ".chordy" / ".song.analyze-x" / "x.json", 20)

    cleanup_orphan_temp(media)

    assert orphan.exists()


def test_nested_chordflask_not_touched(tmp_path):
    media = tmp_path / "album"
    nested = media / ".chordflask" / "nested" / ".song.analyze-1"
    _write(nested / "x.json", 20)

    cleanup_orphan_temp(media)

    assert nested.exists()


def test_source_media_unchanged(tmp_path):
    media = tmp_path / "album"
    source = _write(media / "song.mp4", 100)
    orphan = media / ".chordflask" / ".song.analyze-1"
    _write(orphan / "song.json", 20)
    before = source.read_bytes()

    cleanup_orphan_temp(media)

    assert source.read_bytes() == before


# ── CLI validation ──────────────────────────────────────────────────


def _run_maintain_cli(capsys, *args):
    from chordflask_maintain import cli

    with pytest.raises(SystemExit) as exc:
        cli.main(list(args))
    return exc.value.code, capsys.readouterr()


def test_cli_cleanup_requires_category(tmp_path, capsys):
    media = tmp_path / "album"
    media.mkdir()

    code, captured = _run_maintain_cli(capsys, "storage", "cleanup", str(media))

    assert code == 2
    assert "cleanup category" in captured.err
    assert "--orphan-temp" in captured.err
    assert "--cached-audio" in captured.err
    assert "--corrupt-backups" in captured.err
    assert "--dry-run" in captured.err


def test_cli_older_than_days_requires_corrupt_backups(tmp_path, capsys):
    media = tmp_path / "album"
    media.mkdir()

    code, captured = _run_maintain_cli(
        capsys, "storage", "cleanup", str(media), "--orphan-temp", "--older-than-days", "30"
    )

    assert code == 2
    assert "--older-than-days belongs to and requires --corrupt-backups" in captured.err


def test_cli_corrupt_backups_requires_age(tmp_path, capsys):
    media = tmp_path / "album"
    media.mkdir()

    code, captured = _run_maintain_cli(
        capsys, "storage", "cleanup", str(media), "--corrupt-backups"
    )

    assert code == 2
    assert "--older-than-days" in captured.err
    assert (
        "chordflask-maintain storage cleanup DIR --corrupt-backups "
        "--older-than-days 30 --dry-run"
    ) in captured.err


def test_cli_orphan_temp_dry_run_reports_without_removing(tmp_path, capsys):
    media = tmp_path / "album"
    orphan = media / ".chordflask" / ".song.analyze-abc"
    _write(orphan / "song.json", 20)

    code, captured = _run_maintain_cli(
        capsys, "storage", "cleanup", str(media), "--orphan-temp", "--dry-run"
    )

    assert code == 0
    assert "would remove  .song.analyze-abc" in captured.out
    assert "would reclaim 20 B" in captured.out
    assert orphan.exists()


def test_cli_cached_audio_dry_run_preserves_cache_source_and_analysis(tmp_path, capsys):
    media = tmp_path / "album"
    source = _write(media / "song.mp4", 5)
    cache = _write(media / ".chordflask" / "song.mp3", 100)
    analysis = _write(media / ".chordflask" / "song.json", 40)

    code, captured = _run_maintain_cli(
        capsys, "storage", "cleanup", str(media), "--cached-audio", "--dry-run"
    )

    assert code == 0
    assert "would remove  song.mp3" in captured.out
    assert cache.exists()
    assert source.exists()
    assert analysis.exists()


def test_cli_corrupt_backup_dry_run_preserves_eligible_backup(tmp_path, capsys):
    media = tmp_path / "album"
    backup = _write(media / ".chordflask" / _corrupt_name(), 60)
    _old_mtime(backup)

    code, captured = _run_maintain_cli(
        capsys,
        "storage",
        "cleanup",
        str(media),
        "--corrupt-backups",
        "--older-than-days",
        "30",
        "--dry-run",
    )

    assert code == 0
    assert f"would remove  {backup.name}" in captured.out
    assert backup.exists()


def test_cli_combined_storage_dry_run_mutates_nothing(tmp_path, capsys):
    media = tmp_path / "album"
    source = _write(media / "song.mp4", 5)
    cache = _write(media / ".chordflask" / "song.mp3", 100)
    analysis = _write(media / ".chordflask" / "song.json", 40)
    orphan = media / ".chordflask" / ".song.analyze-abc"
    _write(orphan / "partial.json", 20)
    backup = _write(media / ".chordflask" / _corrupt_name(), 60)
    _old_mtime(backup)

    code, captured = _run_maintain_cli(
        capsys,
        "storage",
        "cleanup",
        str(media),
        "--orphan-temp",
        "--cached-audio",
        "--corrupt-backups",
        "--older-than-days",
        "30",
        "--dry-run",
    )

    assert code == 0
    assert captured.out.count("would remove  ") == 3
    assert all(path.exists() for path in (source, cache, analysis, orphan, backup))


def test_cli_storage_cleanup_refuses_uninspectable_worker_lock(tmp_path, capsys):
    queue = tmp_path / "queue"
    (queue / "analysis_worker.lock").mkdir(parents=True)
    media = tmp_path / "album"
    orphan = media / ".chordflask" / ".song.analyze-abc"
    _write(orphan / "song.json", 20)

    code, captured = _run_maintain_cli(
        capsys, "storage", "cleanup", str(media), "--orphan-temp"
    )

    assert code == 1
    assert "REFUSED" in captured.out
    assert "cannot inspect analysis worker lock" in captured.out
    assert "lock state could not be verified safely" in captured.out
    assert "Check permissions and process state, then retry." in captured.out
    assert f"chordflask-maintain storage report {media}" in captured.out
    assert "nothing deleted" in captured.out
    assert orphan.exists()


def test_cli_storage_cleanup_active_worker_has_retry_guidance(tmp_path, capsys):
    queue = tmp_path / "queue"
    queue.mkdir()
    media = tmp_path / "album"
    orphan = media / ".chordflask" / ".song.analyze-abc"
    _write(orphan / "song.json", 20)

    lock_handle = (queue / "analysis_worker.lock").open("a+")
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        code, captured = _run_maintain_cli(
            capsys, "storage", "cleanup", str(media), "--orphan-temp"
        )
    finally:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()

    assert code == 1
    assert "an analysis worker is active" in captured.out
    assert "nothing deleted" in captured.out
    assert "Retry after analysis has finished or stopped." in captured.out
    assert f"chordflask-maintain storage report {media}" in captured.out
    assert orphan.exists()


def test_cli_storage_cleanup_nothing_to_remove_is_concise(tmp_path, capsys):
    media = tmp_path / "album"
    (media / ".chordflask").mkdir(parents=True)

    code, captured = _run_maintain_cli(
        capsys, "storage", "cleanup", str(media), "--orphan-temp"
    )

    assert code == 0
    assert "nothing to remove" in captured.out
    assert "Retry" not in captured.out
    assert "Safe inspection" not in captured.out
    assert "Check permissions" not in captured.out


def test_storage_cleanup_help_describes_dry_run(capsys):
    code, captured = _run_maintain_cli(capsys, "storage", "cleanup", "--help")

    assert code == 0
    assert "--dry-run" in captured.out
    assert "without deleting anything" in captured.out
