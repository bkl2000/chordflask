import json
import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "flask"))

from analysis_queue import AnalysisQueue


def test_default_queue_migrates_legacy_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CHORDFLASK_QUEUE_DIR", raising=False)
    monkeypatch.delenv("CHORDY_QUEUE_DIR", raising=False)
    legacy_dir = tmp_path / ".chordy"
    legacy_dir.mkdir()
    (legacy_dir / "analysis_queue.json").write_text(
        '{"pending": [], "failed": [{"path": "/tmp/song.mp4"}]}'
    )

    queue = AnalysisQueue()

    assert queue.queue_dir == tmp_path / ".chordflask"
    assert len(queue.status()["failed"]) == 1
    assert not legacy_dir.exists()


def test_legacy_queue_override_remains_compatible(tmp_path, monkeypatch):
    legacy_dir = tmp_path / "custom-chordy-state"
    monkeypatch.delenv("CHORDFLASK_QUEUE_DIR", raising=False)
    monkeypatch.setenv("CHORDY_QUEUE_DIR", str(legacy_dir))

    assert AnalysisQueue().queue_dir == legacy_dir


def test_enqueue_adds_job_id_and_status(tmp_path):
    q = AnalysisQueue(queue_dir=str(tmp_path))
    result = q.enqueue("/tmp/test.mp4")
    assert result == "queued"
    status = q.status()
    assert len(status["pending"]) == 1
    item = status["pending"][0]
    assert "job_id" in item
    assert item["status"] == "pending"
    assert item["force"] is False
    assert item["attempt_count"] == 0
    assert "added_at" in item


def test_enqueue_deduplicates(tmp_path):
    q = AnalysisQueue(queue_dir=str(tmp_path))
    assert q.enqueue("/tmp/test.mp4") == "queued"
    assert q.enqueue("/tmp/test.mp4") == "already_queued"
    assert len(q.status()["pending"]) == 1


def test_enqueue_persists_reanalysis_flag_and_deduplicates(tmp_path):
    q = AnalysisQueue(queue_dir=tmp_path)

    assert q.enqueue("/tmp/test.mp4", force=True) == "queued"
    assert q.enqueue("/tmp/test.mp4", force=True) == "already_queued"

    pending = q.status()["pending"]
    assert len(pending) == 1
    assert pending[0]["force"] is True


def test_reanalysis_upgrades_a_waiting_normal_job(tmp_path):
    q = AnalysisQueue(queue_dir=tmp_path)
    q.enqueue("/tmp/test.mp4")

    assert q.enqueue("/tmp/test.mp4", force=True) == "already_queued"
    assert q.status()["pending"][0]["force"] is True


def test_enqueue_clears_previous_failure(tmp_path):
    q = AnalysisQueue(queue_dir=str(tmp_path))
    q.enqueue("/tmp/test.mp4")
    q.fail("/tmp/test.mp4", Exception("boom"))
    assert len(q.status()["failed"]) == 1
    assert q.enqueue("/tmp/test.mp4") == "queued"
    assert len(q.status()["failed"]) == 0


def test_enqueue_many_uses_limit_only_for_new_jobs_and_preserves_order(tmp_path):
    q = AnalysisQueue(queue_dir=tmp_path)
    q.enqueue("/tmp/already.mp4")

    result = q.enqueue_many([
        "/tmp/first.mp4",
        "/tmp/already.mp4",
        "/tmp/second.mp3",
        "/tmp/third.webm",
    ], limit=2)

    assert result == {
        "queued": ["/tmp/first.mp4", "/tmp/second.mp3"],
        "already_queued": ["/tmp/already.mp4"],
        "deferred": ["/tmp/third.webm"],
    }
    assert [item["path"] for item in q.status()["pending"]] == [
        "/tmp/already.mp4",
        "/tmp/first.mp4",
        "/tmp/second.mp3",
    ]


def test_enqueue_many_retries_failed_job_and_deduplicates_input(tmp_path):
    q = AnalysisQueue(queue_dir=tmp_path)
    q.enqueue("/tmp/retry.mp4")
    q.fail("/tmp/retry.mp4", "broken")

    result = q.enqueue_many(["/tmp/retry.mp4", "/tmp/retry.mp4"], limit=1)

    assert result["queued"] == ["/tmp/retry.mp4"]
    assert q.status()["failed"] == []
    assert len(q.status()["pending"]) == 1


@pytest.mark.parametrize("limit", [True, 0, 501, 1.5, "50"])
def test_enqueue_many_rejects_invalid_limit(tmp_path, limit):
    q = AnalysisQueue(queue_dir=tmp_path)

    with pytest.raises(ValueError, match="limit must be an integer from 1 to 500"):
        q.enqueue_many(["/tmp/song.mp4"], limit=limit)


def test_peek_marks_as_processing(tmp_path):
    q = AnalysisQueue(queue_dir=str(tmp_path))
    q.enqueue("/tmp/test.mp4")
    item = q.peek()
    assert item["status"] == "processing"
    assert "started_at" in item
    assert item["attempt_count"] == 1


def test_peek_returns_none_when_all_processing(tmp_path):
    q = AnalysisQueue(queue_dir=str(tmp_path))
    q.enqueue("/tmp/a.mp4")
    q.enqueue("/tmp/b.mp4")
    q.peek()  # first becomes processing
    item = q.peek()  # second item
    assert item is not None
    assert item["path"] == "/tmp/b.mp4"


def test_complete_removes_from_pending(tmp_path):
    q = AnalysisQueue(queue_dir=str(tmp_path))
    q.enqueue("/tmp/test.mp4")
    assert len(q.status()["pending"]) == 1
    q.complete("/tmp/test.mp4")
    assert len(q.status()["pending"]) == 0


def test_fail_moves_to_failed(tmp_path):
    q = AnalysisQueue(queue_dir=str(tmp_path))
    q.enqueue("/tmp/test.mp4")
    q.fail("/tmp/test.mp4", ValueError("bad data"))
    assert len(q.status()["pending"]) == 0
    assert len(q.status()["failed"]) == 1
    failed = q.status()["failed"][0]
    assert failed["path"] == "/tmp/test.mp4"
    assert "bad data" in failed["error"]


def test_retry_moves_from_failed_to_pending(tmp_path):
    q = AnalysisQueue(queue_dir=str(tmp_path))
    q.enqueue("/tmp/test.mp4")
    processing = q.peek()
    q.fail("/tmp/test.mp4", Exception("oops"))
    assert len(q.status()["failed"]) == 1
    failed = q.status()["failed"][0]
    assert failed["job_id"] == processing["job_id"]
    assert failed["attempt_count"] == 1
    q.retry("/tmp/test.mp4")
    assert len(q.status()["failed"]) == 0
    assert len(q.status()["pending"]) == 1
    pending = q.status()["pending"][0]
    assert pending["path"] == "/tmp/test.mp4"
    assert pending["job_id"] == processing["job_id"]
    assert pending["attempt_count"] == 1
    retried = q.peek()
    assert retried["attempt_count"] == 2


def test_retry_preserves_existing_pending_item(tmp_path):
    q = AnalysisQueue(queue_dir=str(tmp_path))
    q.enqueue("/tmp/test.mp4")
    q.retry("/tmp/test.mp4")
    assert len(q.status()["pending"]) == 1


def test_requeue_processing_recovers_interrupted_jobs_immediately(tmp_path):
    q = AnalysisQueue(queue_dir=tmp_path)
    q.enqueue("/tmp/test.mp4")
    q.peek()

    assert q.requeue_processing() == 1

    pending = q.status()["pending"][0]
    assert pending["status"] == "pending"
    assert "started_at" not in pending
    assert q.requeue_processing() == 0


def test_old_queue_items_are_migrated(tmp_path):
    queue_file = tmp_path / "analysis_queue.json"
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    with open(queue_file, "w") as f:
        json.dump({
            "pending": [{"path": "/tmp/a.mp4", "added_at": "2024-01-01T00:00:00"}],
            "failed": [{"path": "/tmp/b.mp4", "error": "fail", "failed_at": "2024-01-01T00:01:00"}],
        }, f)

    q = AnalysisQueue(queue_dir=str(tmp_path))
    status = q.status()
    for item in status["pending"] + status["failed"]:
        assert "job_id" in item
        assert "status" in item
        assert "attempt_count" in item
        assert item["force"] is False
    assert status["pending"][0]["status"] == "pending"
    assert status["failed"][0]["status"] == "failed"


def test_corrupt_queue_file_returns_empty(tmp_path, caplog):
    queue_file = tmp_path / "analysis_queue.json"
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    corrupt_contents = "{not valid json"
    queue_file.write_text(corrupt_contents, encoding="utf-8")
    q = AnalysisQueue(queue_dir=str(tmp_path))
    status = q.status()
    assert status["pending"] == []
    assert status["failed"] == []
    assert not queue_file.exists()
    backups = list(tmp_path.glob("analysis_queue.corrupt-*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == corrupt_contents
    assert "preserved as" in caplog.text


def test_enqueue_after_corruption_preserves_backup_and_creates_new_queue(tmp_path):
    queue_file = tmp_path / "analysis_queue.json"
    queue_file.write_text("[]", encoding="utf-8")
    q = AnalysisQueue(queue_dir=tmp_path)

    assert q.enqueue("/tmp/test.mp4") == "queued"

    assert len(list(tmp_path.glob("analysis_queue.corrupt-*.json"))) == 1
    saved = json.loads(queue_file.read_text(encoding="utf-8"))
    assert len(saved["pending"]) == 1


@pytest.mark.parametrize("started_at", [None, "not-a-timestamp", "2000-01-01T00:00:00+00:00"])
def test_peek_recovers_stale_or_invalid_processing_job(tmp_path, started_at):
    q = AnalysisQueue(queue_dir=tmp_path)
    q.enqueue("/tmp/test.mp4")
    data = json.loads(q.queue_file.read_text(encoding="utf-8"))
    data["pending"][0]["status"] = "processing"
    if started_at is not None:
        data["pending"][0]["started_at"] = started_at
    q.queue_file.write_text(json.dumps(data), encoding="utf-8")

    item = q.peek()

    assert item["status"] == "processing"
    assert item["attempt_count"] == 1
    assert item["started_at"] != started_at
