#!/usr/bin/env python3

"""
Single-worker chord analysis queue consumer.
"""

import fcntl
import logging
from logging.handlers import RotatingFileHandler
import subprocess
import sys
import time

from .analysis_queue import AnalysisQueue
from .canonical_analysis import analyze_media, json_validation_error, preserve_corrupt_json


def _worker_log(msg):
    logging.getLogger("chordflask.worker").info(msg)


class AnalysisWorker:
    def __init__(self, queue=None, poll_seconds=2, analyzer_cls=None):
        self.queue = queue or AnalysisQueue()
        self.poll_seconds = poll_seconds
        self.analyzer_cls = analyzer_cls
        self.worker_lock_file = self.queue.queue_dir / "analysis_worker.lock"

    def run_forever(self):
        self.queue.queue_dir.mkdir(parents=True, exist_ok=True)
        self._configure_logging()
        with self.worker_lock_file.open("a+") as lock_handle:
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("Worker already running.")
                return 1

            recovered = self.queue.requeue_processing()
            if recovered:
                _worker_log(f"Recovered {recovered} interrupted analysis job(s).")
            print(f"Worker running (queue: {self.queue.queue_file})")
            while True:
                did_work = self.run_once()
                if not did_work:
                    time.sleep(self.poll_seconds)

    def _configure_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
            handlers=[
                RotatingFileHandler(
                    self.queue.queue_dir / "worker.log",
                    maxBytes=2 * 1024 * 1024,
                    backupCount=3,
                )
            ],
        )

    def run_once(self):
        item = self.queue.peek()
        if not item:
            return False

        media_path = item["path"]
        try:
            self._analyze(
                media_path,
                force=item.get("force", False),
                discard_edits=item.get("discard_edits", False),
            )
            self.queue.complete(media_path)
        except Exception as error:
            _worker_log(f"Analysis failed for {media_path}: {error}")
            self.queue.fail(media_path, error)
        return True

    @staticmethod
    def is_running(queue):
        """Return whether another process holds this queue's worker lock."""
        queue.queue_dir.mkdir(parents=True, exist_ok=True)
        lock_file = queue.queue_dir / "analysis_worker.lock"
        with lock_file.open("a+") as lock_handle:
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            return False

    def _analyze(self, media_path, force=False, discard_edits=False):
        return analyze_media(media_path, force=force, discard_edits=discard_edits,
                             analyzer_cls=self.analyzer_cls)

    @staticmethod
    def _json_is_valid(json_path):
        return json_validation_error(json_path) is None

    _json_validation_error = staticmethod(json_validation_error)
    _preserve_corrupt_json = staticmethod(preserve_corrupt_json)


class WorkerSupervisor:
    """Own the worker child started alongside the web application."""

    def __init__(self, queue, process_factory=subprocess.Popen, shutdown_timeout=5):
        self.queue = queue
        self.process_factory = process_factory
        self.shutdown_timeout = shutdown_timeout
        self.process = None

    @staticmethod
    def command():
        if getattr(sys, "frozen", False):
            return [sys.executable, "--worker"]
        return [sys.executable, "-m", "chordflask", "--worker"]

    def start(self):
        if AnalysisWorker.is_running(self.queue):
            return False
        self.process = self.process_factory(self.command(), start_new_session=True)
        return True

    def child_running(self):
        return self.process is not None and self.process.poll() is None

    def stop(self):
        if not self.child_running():
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=self.shutdown_timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=self.shutdown_timeout)


if __name__ == "__main__":
    raise SystemExit(AnalysisWorker().run_forever())
