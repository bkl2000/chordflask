#!/usr/bin/env python3

"""
Single-worker chord analysis queue consumer.
"""

import fcntl
import logging
import os
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from analysis_queue import AnalysisQueue
from chordflask_config import ANALYSIS_DIR_NAME, LEGACY_ANALYSIS_DIR_NAME
from filerepr import FileRepr


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
        log_file = str(self.queue.queue_dir / "worker.log")
        logging.basicConfig(filename=log_file, level=logging.INFO,
                            format="%(asctime)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
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

    def run_once(self):
        item = self.queue.peek()
        if not item:
            return False

        media_path = item["path"]
        try:
            self._analyze(media_path, force=item.get("force", False))
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

    def _analyze(self, media_path, force=False):
        media = Path(media_path)
        if not media.exists():
            raise FileNotFoundError(media_path)

        analysis_dir = media.parent / ANALYSIS_DIR_NAME
        legacy_dir = media.parent / LEGACY_ANALYSIS_DIR_NAME
        file_repr = FileRepr(
            str(media),
            datapath=str(analysis_dir),
            create=not analysis_dir.exists() and legacy_dir.is_dir(),
        )
        json_path = file_repr.get("json")
        if force:
            analysis_dir.mkdir(parents=True, exist_ok=True)
            self.__reanalyze(media, file_repr)
            return
        if os.path.exists(json_path):
            validation_error = self._json_validation_error(json_path)
            if validation_error is None:
                _worker_log(f"Analysis already exists: {json_path}")
                return
            backup = self._preserve_corrupt_json(json_path)
            _worker_log(
                f"Existing analysis is invalid ({validation_error}); "
                f"preserved as {backup} before reanalysis."
            )

        _worker_log(f"Analyzing queued file: {media_path}")
        analyzer_cls = self.analyzer_cls
        if analyzer_cls is None:
            from chordanalyzer import ChordAnalyzer

            analyzer_cls = ChordAnalyzer

        analyzer = analyzer_cls(str(media), str(analysis_dir))
        analyzer.process()
        if not os.path.exists(json_path):
            raise RuntimeError(f"Analysis did not create {json_path}")
        validation_error = self._json_validation_error(json_path)
        if validation_error is not None:
            backup = self._preserve_corrupt_json(json_path)
            raise RuntimeError(
                f"Analysis created invalid chord data ({validation_error}); "
                f"preserved as {backup}"
            )
        _worker_log(f"Finished analysis: {json_path}")

    def __reanalyze(self, media, current_file_repr):
        current_json = current_file_repr.get("json")
        validation_error = self._json_validation_error(current_json)
        if validation_error is not None:
            raise RuntimeError(
                f"Cannot reanalyze without a valid current analysis: {validation_error}"
            )

        analysis_dir = Path(current_file_repr.datapath)
        prefix = f".{media.stem}.reanalyze-"
        _worker_log(f"Reanalyzing queued file: {media}")
        with tempfile.TemporaryDirectory(
            prefix=prefix,
            dir=analysis_dir,
            ignore_cleanup_errors=True,
        ) as temp_name:
            temp_dir = Path(temp_name)
            temporary_file_repr = FileRepr(str(media), datapath=str(temp_dir))
            self.__reuse_cached_mp3(current_file_repr, temporary_file_repr)

            analyzer_cls = self.analyzer_cls
            if analyzer_cls is None:
                from chordanalyzer import ChordAnalyzer

                analyzer_cls = ChordAnalyzer

            analyzer = analyzer_cls(str(media), str(temp_dir))
            analyzer.process()

            temporary_json = temporary_file_repr.get("json")
            if not os.path.exists(temporary_json):
                raise RuntimeError(f"Reanalysis did not create {temporary_json}")
            validation_error = self._json_validation_error(temporary_json)
            if validation_error is not None:
                raise RuntimeError(
                    f"Reanalysis created invalid chord data ({validation_error})"
                )

            self.__preserve_user_data(current_json, temporary_json)
            validation_error = self._json_validation_error(temporary_json)
            if validation_error is not None:
                raise RuntimeError(
                    f"Reanalysis created invalid merged chord data ({validation_error})"
                )

            for suffix in ("mp3", "xml", "mid"):
                self.__replace_best_effort_artifact(
                    temporary_file_repr.get(suffix),
                    current_file_repr.get(suffix),
                )

            os.replace(temporary_json, current_json)
            self.__fsync_directory(analysis_dir)
        _worker_log(f"Finished reanalysis: {current_json}")

    @staticmethod
    def __reuse_cached_mp3(current_file_repr, temporary_file_repr):
        current_mp3 = Path(current_file_repr.get("mp3"))
        temporary_mp3 = Path(temporary_file_repr.get("mp3"))
        if current_mp3.is_file():
            temporary_mp3.symlink_to(current_mp3)

    @staticmethod
    def __preserve_user_data(current_json, temporary_json):
        from chorddata import ChordTrackRepository

        repository = ChordTrackRepository()
        current_track = repository.load(current_json)
        replacement_track = repository.load(temporary_json)

        for track_id in current_track.available_chord_track_ids:
            if track_id == "chordino":
                continue
            replacement_track.set_chord_track(
                track_id,
                current_track.chord_track_chords(track_id),
                metadata=current_track.chord_track_metadata(track_id),
            )
        for track_id in current_track.available_rhythm_track_ids:
            if track_id == "qm_barbeattracker":
                continue
            rhythm = current_track.rhythm_track_data(track_id)
            replacement_track.set_rhythm_track(track_id, **rhythm)

        replacement_track.transpose(current_track.transpose_semitones)
        replacement_track.set_prefer_flats(current_track.prefer_flats)
        replacement_track.user_data = current_track.user_data
        repository.save(replacement_track, temporary_json)

    @staticmethod
    def __replace_best_effort_artifact(source_path, destination_path):
        source = Path(source_path)
        if not source.exists() or source.is_symlink():
            return
        try:
            os.replace(source, destination_path)
        except OSError as error:
            _worker_log(
                f"Could not refresh derived artifact {destination_path}: {error}"
            )

    @staticmethod
    def __fsync_directory(directory):
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            descriptor = os.open(directory, flags)
        except OSError as error:
            _worker_log(f"Could not open {directory} for directory fsync: {error}")
            return
        try:
            try:
                os.fsync(descriptor)
            except OSError as error:
                _worker_log(f"Could not fsync directory {directory}: {error}")
        finally:
            os.close(descriptor)

    @staticmethod
    def _json_is_valid(json_path):
        return AnalysisWorker._json_validation_error(json_path) is None

    @staticmethod
    def _json_validation_error(json_path):
        try:
            from chorddata import ChordTrackRepository
            ChordTrackRepository().load(json_path)
            return None
        except (OSError, UnicodeError, ValueError, TypeError, KeyError) as error:
            return error

    @staticmethod
    def _preserve_corrupt_json(json_path):
        source = Path(json_path)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = source.with_name(
            f"{source.stem}.corrupt-{timestamp}-{uuid.uuid4().hex[:8]}{source.suffix}"
        )
        os.replace(source, backup)
        return backup


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
        return [sys.executable, str(Path(__file__).with_name("chordflask.py")), "--worker"]

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
