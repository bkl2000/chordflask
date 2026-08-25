#!/usr/bin/env python3

"""Serial batch leadsheet exporter for ChordFlask analysis files.

This CLI helper is independent of the Flask server. It discovers MP3/MP4/WebM
media non-recursively, reuses valid analysis JSON, analyzes only missing files
serially, and writes matching playable Markdown and PDF leadsheets into each
``.chordflask`` directory.

Exit codes: 0 all exports succeeded, 1 partial or file errors, 2 argparse or
invalid invocation.
"""

import argparse
import os
import sys
import tempfile


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.dirname(__file__))

from batch_core import find_media_files  # noqa: E402
from chord_markdown import download_track_slug, format_chord_markdown  # noqa: E402
from chord_sheet_pdf import ChordSheetPdfRenderer  # noqa: E402
from chordflask_base import (  # noqa: E402
    DEFAULT_CHORD_TRACK,
    DEFAULT_RHYTHM_TRACK,
    USER_EDITED_TRACK_ID,
)

EDITED_TRACK_ID = USER_EDITED_TRACK_ID
CHORDINO_TRACK_ID = DEFAULT_CHORD_TRACK
QM_RHYTHM_TRACK_ID = DEFAULT_RHYTHM_TRACK

_BUILTIN_TRACK_NAMES = {
    CHORDINO_TRACK_ID: "Chordino",
    "madmom": "Madmom",
    QM_RHYTHM_TRACK_ID: "QM Bar/Beat Tracker",
}

_FORMAT_FILES = {
    "markdown": {"md"},
    "pdf": {"pdf"},
    "both": {"md", "pdf"},
}


class LeadsheetExportError(Exception):
    """A per-file failure with the completed analysis action, if any."""

    def __init__(self, message, analysis_action=None):
        super().__init__(message)
        self.analysis_action = analysis_action


def add_export_options(parser):
    parser.add_argument(
        "--chord-track",
        default="auto",
        metavar="auto|original|edited|TRACK_ID",
        help="Chord track to export (default: auto = Edited if present else Chordino)",
    )
    parser.add_argument(
        "--rhythm-track",
        default=QM_RHYTHM_TRACK_ID,
        metavar="TRACK_ID",
        help="Rhythm track to use for the beat grid (default: %(default)s)",
    )
    parser.add_argument(
        "--transpose",
        type=int,
        default=0,
        metavar="N",
        help="Display transposition in semitones (default: 0)",
    )
    parser.add_argument(
        "--sharps",
        action="store_true",
        help="Spell chord roots with sharps instead of flats",
    )
    parser.add_argument(
        "--unicode",
        action="store_true",
        help="Render accidentals as Unicode symbols",
    )
    parser.add_argument(
        "--repeat-mode",
        choices=("changes", "chords"),
        default="changes",
        help="changes writes held beats as -, chords writes every beat (default: changes)",
    )
    parser.add_argument(
        "--no-metric-chords",
        action="store_true",
        help="Use the unfiltered nearest-beat chord display instead of metric smoothing",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "pdf", "both"),
        default="both",
        help="Leadsheet format to write (default: both)",
    )
    return parser


def build_argument_parser():
    parser = argparse.ArgumentParser(
        description="Export playable Markdown leadsheets for all media in a directory."
    )
    parser.add_argument(
        "directory",
        help="Directory with MP3/MP4/WebM files (non-recursive)",
    )
    add_export_options(parser)
    return parser


def _track_display_name(track_id, metadata):
    display_name = metadata.get("display_name")
    if isinstance(display_name, str) and display_name.strip():
        return display_name.strip()
    return _BUILTIN_TRACK_NAMES.get(track_id, track_id)


def _version_label(track_id):
    return "Edited" if track_id == EDITED_TRACK_ID else "Original"


def resolve_chord_track(chord_data, choice):
    """Resolve the requested chord track against an analysis file."""
    if choice == "edited":
        return EDITED_TRACK_ID
    if choice == "original":
        return CHORDINO_TRACK_ID
    if choice == "auto":
        if chord_data.has_chord_track(EDITED_TRACK_ID):
            return EDITED_TRACK_ID
        return CHORDINO_TRACK_ID
    return choice


def resolve_rhythm_track(chord_data, chord_track_id, choice):
    """Keep Edited exports on the rhythm grid recorded in their metadata."""
    if chord_track_id != EDITED_TRACK_ID:
        return choice
    metadata = chord_data.chord_track_metadata(chord_track_id)
    sources = metadata.get("sources")
    rhythm_track_id = sources.get("rhythm") if isinstance(sources, dict) else None
    if not isinstance(rhythm_track_id, str) or not rhythm_track_id:
        raise ValueError("Edited chord rhythm source metadata is invalid")
    return rhythm_track_id


def _write_atomic(path, content):
    path = os.path.abspath(os.fspath(path))
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    descriptor, tmp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.",
        suffix=".tmp",
        dir=directory,
    )
    try:
        mode = "wb" if isinstance(content, bytes) else "w"
        options = {} if mode == "wb" else {"encoding": "utf-8"}
        with os.fdopen(descriptor, mode, **options) as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass


def _load_chord_data(json_path, args):
    from chordflask_base import ChordData

    cd = ChordData(prefer_flats=not args.sharps, use_unicode=args.unicode)
    cd.load_from_file(json_path)
    cd.set_prefer_flats(not args.sharps)
    cd.set_unicode(args.unicode)
    cd.transpose(args.transpose)
    return cd


def _analyze_media(media_path):
    from chordanalyzer import ChordAnalyzer

    analyzer = ChordAnalyzer(str(media_path))
    analyzer.process()


def export_file(media_path, args):
    """Reuse or create the analysis and write one leadsheet file."""
    from filerepr import FileRepr
    from playbackview import PlaybackView

    file_repr = FileRepr(str(media_path), create=True)
    json_path = file_repr.get("json")
    analysis_action = None
    try:
        if not os.path.isfile(json_path):
            _analyze_media(media_path)
            if not os.path.isfile(json_path):
                raise FileNotFoundError(f"Analysis file does not exist: {json_path}")
            analysis_action = "created"

        cd = _load_chord_data(json_path, args)
        if analysis_action is None:
            analysis_action = "reused"

        chord_track_id = resolve_chord_track(cd, args.chord_track)
        if not cd.has_chord_track(chord_track_id):
            raise ValueError(f'chord track "{chord_track_id}" not available')
        rhythm_track_id = resolve_rhythm_track(cd, chord_track_id, args.rhythm_track)
        if not cd.has_rhythm_track(rhythm_track_id):
            raise ValueError(f'rhythm track "{rhythm_track_id}" not available')

        cd.select_chord_track(chord_track_id)
        cd.select_rhythm_track(rhythm_track_id)

        view = PlaybackView(
            cd,
            metric_chords=not args.no_metric_chords,
            repeat_mode=args.repeat_mode,
        )
        beat_chords = view.full_beat_view()
        if not beat_chords:
            raise ValueError("the active analysis has no beat grid to export")
        beat_numbers = cd.beat_numbers
        beats = [
            (beat_numbers[i] if i < len(beat_numbers) else "", chord) for i, chord in enumerate(beat_chords)
        ]

        chord_label = _track_display_name(chord_track_id, cd.chord_track_metadata(chord_track_id))
        rhythm_label = _track_display_name(rhythm_track_id, cd.rhythm_track_metadata(rhythm_track_id))
        markdown = format_chord_markdown(
            title=file_repr.basename,
            chord_track=chord_label,
            rhythm_track=rhythm_label,
            version=_version_label(chord_track_id),
            transpose=args.transpose,
            spelling="Sharps" if args.sharps else "Flats",
            unicode_symbols=args.unicode,
            bpm=cd.bpm,
            meter=cd.meter_signature,
            beats=beats,
            repeat_mode=args.repeat_mode,
        )

        output_stem = os.path.join(
            file_repr.datapath,
            f"{file_repr.basename}-chords-{download_track_slug(chord_track_id)}",
        )
        formats = _FORMAT_FILES[getattr(args, "format", "both")]
        pdf = ChordSheetPdfRenderer().render_markdown(markdown) if "pdf" in formats else None
        if "md" in formats:
            _write_atomic(f"{output_stem}.md", markdown)
        if "pdf" in formats:
            _write_atomic(f"{output_stem}.pdf", pdf)
    except LeadsheetExportError:
        raise
    except Exception as error:
        raise LeadsheetExportError(str(error), analysis_action) from error

    return {
        "media": str(media_path),
        "ok": True,
        "analysis_action": analysis_action,
        "exported": True,
        "error": None,
    }


def run(media_dir, args, output=print):
    files = find_media_files(media_dir)
    output(f"Found {len(files)} media files in {media_dir}")

    failures = []
    reused = 0
    created = 0
    exported = 0
    for path in files:
        try:
            result = export_file(path, args)
        except Exception as error:  # noqa: BLE001 - continue after per-file errors
            analysis_action = getattr(error, "analysis_action", None)
            reused += analysis_action == "reused"
            created += analysis_action == "created"
            failures.append((path, error))
            output(f"Error: {path}: {error}")
            continue
        reused += result["analysis_action"] == "reused"
        created += result["analysis_action"] == "created"
        exported += 1
        output(f"Exported: {path}")

    output("")
    output(
        f"Done: {len(files)} files, "
        f"{reused} reused analyses, {created} new analyses, "
        f"{exported} leadsheets, {len(failures)} failed"
    )
    return 1 if failures else 0


def main(argv=None):
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    try:
        return run(args.directory, args)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
