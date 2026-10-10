"""Chordino analysis of one registered Demucs stem, stored as its own chord track.

Stems are pad/trimmed by the producer to the exact sample count of the decoded
original, start at sample zero and play with no offset, so Chordino timestamps
from a stem are already original-timeline times. No beat tracking runs here;
the track is displayed on the original rhythm grid. Only this producer's
``chordino_stem_<stem>`` track is written, under the shared analysis lock.
"""

import hashlib
import sys
from pathlib import Path

from chordflask_base import (
    ANALYSIS_DIR_NAME,
    DEFAULT_CHORD_TRACK,
    ChordTrackRepository,
    analysis_json_lock,
    analysis_json_path,
    build_stem_chord_metadata,
    is_canonical_analysis_complete,
    media_source_identity,
    stem_chord_track_id,
)

from .mp4playerflask import STEMS_AUDIO_SET_ID


class StemChordAnalysisError(RuntimeError):
    """The selected stem cannot be analyzed safely."""


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(json_path):
    if not json_path.is_file():
        raise StemChordAnalysisError(f"No analysis exists yet for this media: {json_path}")
    try:
        return ChordTrackRepository().load(json_path)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as error:
        raise StemChordAnalysisError(f"Invalid analysis JSON {json_path}: {error}") from error


def resolve_registered_stem(media_path, chord_data, stem):
    """Return ``(stem_file, stem_entry, set_data)`` for one registered stem."""
    try:
        stem_chord_track_id(stem)
    except ValueError as error:
        raise StemChordAnalysisError(str(error)) from error
    if not chord_data.has_audio_track(STEMS_AUDIO_SET_ID):
        raise StemChordAnalysisError("No Demucs stem set is registered; prepare stems first")
    set_data = chord_data.audio_track_data(STEMS_AUDIO_SET_ID)
    entry = set_data.get("tracks", {}).get(stem)
    if not isinstance(entry, dict):
        raise StemChordAnalysisError(f"Unknown stem {stem!r} in {STEMS_AUDIO_SET_ID}")
    media_path = Path(media_path)
    storage_root = (media_path.parent / ANALYSIS_DIR_NAME).resolve()
    candidate = media_path.parent / Path(entry["path"])
    if candidate.is_symlink():
        raise StemChordAnalysisError(f"Stem file is a symlink: {candidate}")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(storage_root):
        raise StemChordAnalysisError(f"Stem file escapes the analysis directory: {candidate}")
    if not resolved.is_file():
        raise StemChordAnalysisError(f"Stem file is missing: {candidate}; regenerate stems")
    return resolved, entry, set_data


def analyze_stem_chords(media_path, stem, *, analyzer=None):
    media_path = Path(media_path).resolve(strict=True)
    json_path = analysis_json_path(media_path)
    data = _load(json_path)
    if not is_canonical_analysis_complete(data):
        raise StemChordAnalysisError("Chordino/QM analysis of the original is required first")
    stem_file, entry, set_data = resolve_registered_stem(media_path, data, stem)
    if stem_file.stat().st_size != entry["size"] or _sha256(stem_file) != entry["sha256"]:
        raise StemChordAnalysisError(f"The {stem} stem file is stale or changed; regenerate stems")
    set_source_sha256 = set_data["metadata"]["source"]["sha256"]
    if media_source_identity(media_path)["sha256"] != set_source_sha256:
        raise StemChordAnalysisError("Stems are stale: the media changed since separation")
    source_media = data.chord_track_metadata(DEFAULT_CHORD_TRACK).get("source_media")

    if analyzer is None:
        from .audio_analyzer import AudioAnalyzer
        analyzer = AudioAnalyzer()
    chords = analyzer.analyze_chords(str(stem_file))

    track_id = stem_chord_track_id(stem)
    with analysis_json_lock(json_path):
        current = _load(json_path)
        try:
            _, current_entry, _ = resolve_registered_stem(media_path, current, stem)
        except StemChordAnalysisError as error:
            raise StemChordAnalysisError(f"Stems changed during analysis; retry ({error})") from error
        current_source = (
            current.chord_track_metadata(DEFAULT_CHORD_TRACK).get("source_media")
            if current.has_chord_track(DEFAULT_CHORD_TRACK) else None
        )
        if current_entry["sha256"] != entry["sha256"] or current_source != source_media:
            raise StemChordAnalysisError("Stems or the original analysis changed during analysis; retry")
        current.set_chord_track(
            track_id,
            chords,
            metadata=build_stem_chord_metadata(
                stem=stem, set_id=STEMS_AUDIO_SET_ID, stem_entry=entry,
                set_source_sha256=set_source_sha256, source_media=source_media,
            ),
        )
        ChordTrackRepository().save(current, json_path)
    return {"track_id": track_id, "chords": len(chords)}


def cli_analyze_stem(stem, media):
    """Entry point for the hidden ``chordflask --analyze-stem STEM MEDIA`` flag."""
    try:
        result = analyze_stem_chords(Path(media), stem)
    except (StemChordAnalysisError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Stem chords written: {result['track_id']} ({result['chords']} chords)")
    return 0
