#!/usr/bin/env python3

"""
Persistent local queue for chord analysis requests.
"""

import fcntl
import json
import os
import tempfile
import uuid
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

STALE_PROCESSING_MINUTES = 10
MAX_BATCH_SIZE = 500


class AnalysisQueue:
    def __init__(self, queue_dir=None):
        base_dir = queue_dir or os.environ.get("CHORDFLASK_QUEUE_DIR")
        if base_dir:
            self.queue_dir = Path(base_dir).expanduser()
        else:
            self.queue_dir = self._default_queue_dir()
        self.queue_file = self.queue_dir / "analysis_queue.json"
        self.lock_file = self.queue_dir / "analysis_queue.lock"

    @staticmethod
    def _default_queue_dir():
        legacy_override = os.environ.get("CHORDY_QUEUE_DIR")
        if legacy_override:
            return Path(legacy_override).expanduser()

        queue_dir = Path.home() / ".chordflask"
        legacy_dir = Path.home() / ".chordy"
        if not queue_dir.exists() and legacy_dir.is_dir():
            try:
                legacy_dir.rename(queue_dir)
            except OSError:
                return legacy_dir
        return queue_dir

    def enqueue(self, media_path, force=False, discard_edits=False):
        if not isinstance(force, bool):
            raise TypeError("force must be a boolean")
        if not isinstance(discard_edits, bool):
            raise TypeError("discard_edits must be a boolean")
        media_path = str(Path(media_path).expanduser().resolve())
        with self._locked_data() as data:
            pending = data.setdefault("pending", [])
            failed = data.setdefault("failed", [])
            for item in pending:
                if item["path"] != media_path:
                    continue
                if force and item.get("status") != "processing":
                    item["force"] = True
                if discard_edits and item.get("status") != "processing":
                    item["discard_edits"] = True
                return "already_queued"

            data["failed"] = [item for item in failed if item.get("path") != media_path]
            pending.append(self._new_job(media_path, force=force, discard_edits=discard_edits))
            return "queued"

    def enqueue_many(self, media_paths, limit):
        """Atomically enqueue at most ``limit`` new jobs in caller order.

        Paths already pending do not consume the limit. A matching failed job is
        cleared when its path is selected for retry.
        """
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= MAX_BATCH_SIZE
        ):
            raise ValueError(f"limit must be an integer from 1 to {MAX_BATCH_SIZE}")

        normalized = []
        seen = set()
        for media_path in media_paths:
            path = str(Path(media_path).expanduser().resolve())
            if path not in seen:
                seen.add(path)
                normalized.append(path)

        with self._locked_data() as data:
            pending = data.setdefault("pending", [])
            failed = data.setdefault("failed", [])
            pending_paths = {item.get("path") for item in pending}
            queued = []
            already_queued = []
            deferred = []

            for media_path in normalized:
                if media_path in pending_paths:
                    already_queued.append(media_path)
                    continue
                if len(queued) >= limit:
                    deferred.append(media_path)
                    continue

                failed = [item for item in failed if item.get("path") != media_path]
                pending.append(self._new_job(media_path))
                pending_paths.add(media_path)
                queued.append(media_path)

            data["failed"] = failed
            return {
                "queued": queued,
                "already_queued": already_queued,
                "deferred": deferred,
            }

    def peek(self):
        with self._locked_data() as data:
            self._recover_stale(data)
            pending = data.get("pending", [])
            for item in pending:
                if item.get("status") != "processing":
                    item["status"] = "processing"
                    item["started_at"] = self._now()
                    item["attempt_count"] = item.get("attempt_count", 0) + 1
                    return item.copy()
            return None

    def complete(self, media_path):
        media_path = str(Path(media_path).expanduser().resolve())
        with self._locked_data() as data:
            data["pending"] = [
                item for item in data.get("pending", [])
                if item.get("path") != media_path
            ]

    def fail(self, media_path, error):
        media_path = str(Path(media_path).expanduser().resolve())
        with self._locked_data() as data:
            job = None
            pending = []
            for item in data.get("pending", []):
                if item.get("path") == media_path:
                    job = item
                else:
                    pending.append(item)
            data["pending"] = pending
            failed = [
                item for item in data.get("failed", [])
                if item.get("path") != media_path
            ]
            job = dict(job or {
                "job_id": uuid.uuid4().hex,
                "path": media_path,
                "force": False,
                "attempt_count": 0,
                "added_at": self._now(),
            })
            job.update({
                "status": "failed",
                "failed_at": self._now(),
                "error": str(error),
            })
            job.pop("started_at", None)
            failed.append(job)
            data["failed"] = failed

    def retry(self, media_path):
        media_path = str(Path(media_path).expanduser().resolve())
        with self._locked_data() as data:
            pending = data.setdefault("pending", [])
            if any(item["path"] == media_path for item in pending):
                return

            job = None
            failed = []
            for item in data.get("failed", []):
                if item.get("path") == media_path:
                    job = item
                else:
                    failed.append(item)
            data["failed"] = failed
            if job is None:
                job = {
                    "job_id": uuid.uuid4().hex,
                    "path": media_path,
                    "attempt_count": 0,
                    "added_at": self._now(),
                }
            job = dict(job)
            job["status"] = "pending"
            job.pop("started_at", None)
            job.pop("failed_at", None)
            job.pop("error", None)
            pending.append(job)

    def status(self):
        with self._locked_data(save=False) as data:
            return {
                "pending": list(data.get("pending", [])),
                "failed": list(data.get("failed", [])),
            }

    def requeue_processing(self):
        """Return jobs left processing by a previous worker to pending."""
        with self._locked_data() as data:
            recovered = 0
            for item in data.get("pending", []):
                if item.get("status") == "processing":
                    item["status"] = "pending"
                    item.pop("started_at", None)
                    recovered += 1
            return recovered

    @contextmanager
    def _locked_data(self, save=True):
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        with self.lock_file.open("a+") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            data = self._load()
            try:
                yield data
            except Exception:
                raise
            else:
                if save:
                    self._save(data)
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def _load(self):
        if not self.queue_file.exists():
            return {"pending": [], "failed": []}
        try:
            with self.queue_file.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("queue root must be an object")
            return {
                "pending": self._migrate_items(data.get("pending", []), "pending"),
                "failed": self._migrate_items(data.get("failed", []), "failed"),
            }
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as error:
            backup = self._preserve_corrupt_queue()
            logger.warning(
                "Analysis queue file is corrupt (%s); preserved as %s.",
                error,
                backup,
            )
            return {"pending": [], "failed": []}

    def _preserve_corrupt_queue(self):
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = self.queue_file.with_name(
            f"{self.queue_file.stem}.corrupt-{timestamp}-{uuid.uuid4().hex[:8]}"
            f"{self.queue_file.suffix}"
        )
        os.replace(self.queue_file, backup)
        return backup

    def _save(self, data):
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{self.queue_file.name}.",
            suffix=".tmp",
            dir=self.queue_dir,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = None
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.queue_file)
            temp_name = None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temp_name is not None:
                try:
                    os.unlink(temp_name)
                except FileNotFoundError:
                    pass

    @staticmethod
    def _new_job(media_path, force=False, discard_edits=False):
        return {
            "job_id": uuid.uuid4().hex,
            "path": media_path,
            "status": "pending",
            "force": force,
            "discard_edits": discard_edits,
            "attempt_count": 0,
            "added_at": AnalysisQueue._now(),
        }

    @staticmethod
    def _migrate_items(items, default_status):
        if not isinstance(items, list):
            raise ValueError("queue pending/failed fields must be lists")
        migrated = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("queue items must be objects")
            item = dict(item)
            if not isinstance(item.get("path"), str) or not item["path"]:
                raise ValueError("queue item path must be a non-empty string")
            item.setdefault("status", default_status)
            item.setdefault("force", False)
            if not isinstance(item["force"], bool):
                raise ValueError("queue item force must be a boolean")
            item.setdefault("discard_edits", False)
            if not isinstance(item["discard_edits"], bool):
                raise ValueError("queue item discard_edits must be a boolean")
            item.setdefault("attempt_count", 0)
            if (
                not isinstance(item["attempt_count"], int)
                or isinstance(item["attempt_count"], bool)
                or item["attempt_count"] < 0
            ):
                raise ValueError("queue item attempt_count must be a non-negative integer")
            if "job_id" not in item:
                item["job_id"] = uuid.uuid4().hex
            migrated.append(item)
        return migrated

    @staticmethod
    def _recover_stale(data):
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_PROCESSING_MINUTES)
        pending = data.get("pending", [])
        recovered = 0
        for item in pending:
            if item.get("status") == "processing":
                started = item.get("started_at")
                try:
                    started_at = datetime.fromisoformat(started) if started else None
                    if started_at is not None and started_at.tzinfo is None:
                        started_at = started_at.replace(tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    started_at = None
                if started_at is None or started_at <= cutoff:
                    item["status"] = "pending"
                    item.pop("started_at", None)
                    recovered += 1
        if recovered:
            logger.info("Recovered %d stale processing job(s)", recovered)

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
