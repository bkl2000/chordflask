"""One locked, staged canonical-analysis transaction for every entry point."""

from contextlib import contextmanager
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid

from chordflask_base import (
    analysis_json_lock, ChordTrackRepository, is_canonical_analysis_complete, preserve_analysis_user_data,
    canonical_source_status, media_source_identity, record_canonical_source,
)

from .filerepr import FileRepr

logger = logging.getLogger("chordflask.worker")


@contextmanager
def media_analysis_lock(media):
    """Persistent lock inode per published stem; flock releases on close/crash.

    Media with the same stem share an analysis JSON and therefore share a lock.
    Never unlink lock files: that would allow two processes to lock two inodes.
    """
    canonical = FileRepr(str(media), create=True)
    with analysis_json_lock(canonical.get("json")):
        yield


def json_validation_error(json_path):
    try:
        ChordTrackRepository().load(json_path)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as error:
        return error
    return None


def preserve_corrupt_json(json_path, destination_dir=None):
    source = Path(json_path)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    parent = Path(destination_dir) if destination_dir is not None else source.parent
    backup = parent / f"{source.stem}.corrupt-{timestamp}-{uuid.uuid4().hex[:8]}{source.suffix}"
    os.replace(source, backup)
    return backup


def _remove_orphaned_workdirs(directory, stem):
    """Called only while owning the stem's analysis lock, before creating staging.

    Cooperating producers hold that lock for the entire staging lifetime, so
    matching directories cannot be active. Recognize only tempfile's reserved
    eight-character suffix, not arbitrary similarly prefixed user directories.
    """
    pattern = re.compile(rf"\.{re.escape(stem)}\.(?:analyze|reanalyze)-[a-z0-9_]{{8}}")
    for path in directory.iterdir():
        if not pattern.fullmatch(path.name) or path.is_symlink() or not path.is_dir():
            continue
        try:
            shutil.rmtree(path)
        except OSError as error:
            logger.warning("Could not remove orphaned analysis directory %s: %s", path, error)


def execute_analysis(file_repr, analyze_staged, *, force=False, discard_edits=False,
                     recover_invalid=False, require_canonical=True):
    """Run a staging callback under a per-media lock and publish validated JSON last.

    The callback writes only into the supplied invocation-owned FileRepr. Existing
    optional/user data is reread after analysis, immediately before the final merge.
    The same lock serializes all cooperating analysis JSON writers.
    """
    media = Path(file_repr.get()).resolve(strict=True)
    with analysis_json_lock(file_repr.get("json")):
        directory = Path(file_repr.datapath)
        directory.mkdir(parents=True, exist_ok=True)
        json_path = Path(file_repr.get("json"))
        _remove_orphaned_workdirs(directory, json_path.stem)
        repository = ChordTrackRepository()
        existing = None
        if json_path.exists():
            try:
                existing = repository.load(json_path)
            except (OSError, UnicodeError, ValueError, TypeError, KeyError) as error:
                if force or not recover_invalid:
                    raise RuntimeError(f"Cannot reanalyze without a valid current analysis: {error}") from error
                backup = preserve_corrupt_json(json_path)
                logger.info("Existing analysis is invalid (%s); preserved as %s", error, backup)
        elif force:
            raise RuntimeError("Cannot reanalyze without a valid current analysis: file missing")
        if (existing is not None and not force and is_canonical_analysis_complete(existing)
                and canonical_source_status(existing, media) != "stale"):
            logger.info("Analysis already exists: %s", json_path)
            return existing

        source_identity = media_source_identity(media)
        kind = "reanalyze" if existing is not None else "analyze"
        with tempfile.TemporaryDirectory(
            prefix=f".{media.stem}.{kind}-", dir=directory, ignore_cleanup_errors=True,
        ) as name:
            staged = FileRepr(str(media), datapath=name)
            analyze_staged(staged)
            temporary_json = Path(staged.get("json"))
            if not temporary_json.exists():
                raise RuntimeError(f"Analysis did not create {temporary_json}")
            error = json_validation_error(temporary_json)
            if error is not None:
                if existing is None:
                    preserve_corrupt_json(temporary_json, directory)
                raise RuntimeError(f"Analysis created invalid chord data ({error})")
            replacement = repository.load(temporary_json)
            if media_source_identity(media) != source_identity:
                raise RuntimeError("Media changed during canonical analysis; retry")
            record_canonical_source(replacement, source_identity)
            # Hash before the fresh preservation reread, not after it: hashing
            # large media must not extend the optional-update merge window.
            if json_path.exists():
                current = repository.load(json_path)
                preserve_analysis_user_data(current, replacement, drop_edited=discard_edits)
            repository.save(replacement, temporary_json)
            if require_canonical and not is_canonical_analysis_complete(replacement):
                raise RuntimeError("Analysis did not create complete canonical tracks")
            # Validate the final merged generation before moving any artifact.
            replacement = repository.load(temporary_json)
            for suffix in ("mp3", "xml", "mid"):
                source = Path(staged.get(suffix))
                if not source.exists() or source.is_symlink():
                    continue
                try:
                    os.replace(source, file_repr.get(suffix))
                except OSError as error:
                    logger.info("Could not refresh derived artifact %s: %s", file_repr.get(suffix), error)
            os.replace(temporary_json, json_path)
            # write_atomic supplied a durable staged JSON; persist the final rename.
            descriptor = None
            try:
                descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                os.fsync(descriptor)
            except OSError as error:
                logger.info("Could not fsync directory %s: %s", directory, error)
            finally:
                if descriptor is not None:
                    os.close(descriptor)
        logger.info("Finished analysis: %s", json_path)
        return replacement


def analyze_media(media_path, *, force=False, discard_edits=False, analyzer_cls=None):
    """Public worker/CLI adapter; component services use execute_analysis directly."""
    file_repr = FileRepr(str(media_path), create=True)

    def run(staged):
        factory = analyzer_cls
        if factory is None:
            from .chordanalyzer import ChordAnalyzer
            factory = ChordAnalyzer
        analyzer = factory(str(staged.get()), staged.datapath)
        if hasattr(analyzer, "analysis_service"):
            analyzer.analysis_service.analyze_staged(staged)
        else:
            # Injectable analyzer facade used by synthetic workers/tests.
            analyzer.process()

    return execute_analysis(file_repr, run, force=force, discard_edits=discard_edits,
                            recover_invalid=True)
