"""Command line entry point for on-demand lyrics ChordPro generation."""

from __future__ import annotations

import argparse
from functools import partial
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from chordflask.filerepr import FileRepr
from chordflask.media_library import preferred_media_files
from chordflask.playbackview import PlaybackView
from chordflask_base import (
    DEFAULT_CHORD_TRACK,
    DEFAULT_RHYTHM_TRACK,
    USER_EDITED_TRACK_ID,
    ChordData,
)

from .align import align_lyrics, render_chordpro, time_plain_lyrics
from .embedded import get_embedded_lyrics
from .lrclib import (
    LRCLIBClient,
    LRCLIBError,
    LyricsRecord,
    SongIdentity,
    TimedLyricLine,
    parse_synced_lyrics,
)
from .romanize import DEFAULT_ENGINE, SUPPORTED_ENGINES, RomanizationError, romanize_thai


_FILENAME_SEPARATOR = re.compile(r"\s+(?:-|–|—)\s+")
_LYRICS_SOURCES = ("lrc", "embedded", "lrclib")
DEFAULT_LYRICS_SOURCES = _LYRICS_SOURCES


class GenerationError(RuntimeError):
    """A clean per-file failure reported by the CLI."""


def _parse_lyrics_sources(value: str) -> tuple[str, ...]:
    sources = tuple(value.split(":"))
    if not sources or any(not source for source in sources):
        raise argparse.ArgumentTypeError("lyrics source list must not be empty")
    unknown = [source for source in sources if source not in _LYRICS_SOURCES]
    if unknown:
        raise argparse.ArgumentTypeError(f'unknown lyrics source "{unknown[0]}"')
    if len(set(sources)) != len(sources):
        raise argparse.ArgumentTypeError("lyrics source names must not be duplicated")
    return sources


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chordflask-genlyrics",
        description=(
            "Use external LRC, embedded, or LRCLIB lyrics and generate a .cho "
            "sidecar using existing ChordFlask analysis."
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="match and render without writing")
    parser.add_argument("--force", action="store_true", help="replace an existing same-stem .cho file")
    parser.add_argument(
        "--tag",
        metavar="SEARCH_TEXT",
        help="explicit LRCLIB search hint (single-file mode only)",
    )
    parser.add_argument(
        "--lyrics",
        type=_parse_lyrics_sources,
        default=DEFAULT_LYRICS_SOURCES,
        metavar="SOURCES",
        help="ordered colon-separated sources (default: lrc:embedded:lrclib)",
    )
    parser.add_argument(
        "--track",
        default="auto",
        metavar="TRACK_ID",
        help="chord track to embed (default: auto)",
    )
    parser.add_argument(
        "--romanize",
        action="store_true",
        help="add Thai romanization metadata to generated lyric lines",
    )
    parser.add_argument(
        "--romanize-engine",
        choices=SUPPORTED_ENGINES,
        default=DEFAULT_ENGINE,
        help=f"Thai romanization engine (default: {DEFAULT_ENGINE})",
    )
    parser.add_argument("target", type=Path, help="MP3/MP4/WebM file or a directory")
    return parser


def identity_from_filename(path: Path) -> SongIdentity:
    """Derive conventional ``Artist - Title`` identity from a media filename."""
    parts = _FILENAME_SEPARATOR.split(path.stem, maxsplit=1)
    if len(parts) == 2 and all(part.strip() for part in parts):
        return SongIdentity(title=parts[1].strip(), artist=parts[0].strip())
    return SongIdentity(title=path.stem.strip() or None)


def probe_media(path: Path) -> SongIdentity:
    """Read embedded title/artist/album and duration through the existing ffprobe toolchain."""
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:format_tags=title,artist,album",
        "-of",
        "json",
        os.fspath(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return SongIdentity()
    if result.returncode != 0:
        return SongIdentity()
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return SongIdentity()
    format_data = data.get("format", {}) if isinstance(data, dict) else {}
    tags = format_data.get("tags", {}) if isinstance(format_data, dict) else {}
    if not isinstance(tags, dict):
        tags = {}
    folded_tags = {str(key).casefold(): value for key, value in tags.items()}

    def clean(name):
        value = folded_tags.get(name)
        return value.strip() if isinstance(value, str) and value.strip() else None

    try:
        duration = float(format_data.get("duration"))
    except (TypeError, ValueError):
        duration = None
    if duration is not None and (not math.isfinite(duration) or duration <= 0):
        duration = None
    return SongIdentity(
        title=clean("title"),
        artist=clean("artist"),
        album=clean("album"),
        duration=duration,
    )


def lookup_identity(
    path: Path,
    *,
    analysis_duration: float | None = None,
    include_filename: bool = True,
) -> SongIdentity:
    """Prefer embedded metadata, optionally filling identity gaps from the filename."""
    embedded = probe_media(path)
    filename = identity_from_filename(path) if include_filename else SongIdentity()
    return SongIdentity(
        title=embedded.title or filename.title,
        artist=embedded.artist or filename.artist,
        album=embedded.album,
        duration=embedded.duration or analysis_duration,
    )


def _analysis_duration(chord_data: ChordData) -> float | None:
    beat_times = chord_data.beat_times
    if len(beat_times) >= 2:
        return beat_times[-1] + (beat_times[-1] - beat_times[-2])
    if beat_times:
        return beat_times[-1] or None
    chord_times = chord_data.chord_times
    return chord_times[-1] if chord_times and chord_times[-1] > 0 else None


def _select_tracks(chord_data: ChordData, requested_track: str) -> str:
    if requested_track == "auto":
        chord_track = (
            USER_EDITED_TRACK_ID
            if chord_data.has_chord_track(USER_EDITED_TRACK_ID)
            else chord_data.active_chord_track_id or DEFAULT_CHORD_TRACK
        )
    else:
        chord_track = requested_track
    if not chord_data.has_chord_track(chord_track):
        raise GenerationError(f'chord track "{chord_track}" is unavailable')

    if chord_track == USER_EDITED_TRACK_ID:
        chord_track = USER_EDITED_TRACK_ID
        metadata = chord_data.chord_track_metadata(chord_track)
        sources = metadata.get("sources")
        rhythm_track = sources.get("rhythm") if isinstance(sources, dict) else None
        if not isinstance(rhythm_track, str) or not rhythm_track:
            raise GenerationError("edited chord rhythm source metadata is invalid")
    else:
        rhythm_track = DEFAULT_RHYTHM_TRACK
    if not chord_data.has_rhythm_track(rhythm_track):
        raise GenerationError(f'rhythm track "{rhythm_track}" is unavailable')
    chord_data.select_chord_track(chord_track)
    chord_data.select_rhythm_track(rhythm_track)
    return chord_track


def _load_analysis(media: Path, requested_track: str) -> ChordData:
    analysis_path = Path(FileRepr(media).get("json"))
    if not analysis_path.is_file():
        raise GenerationError("valid ChordFlask analysis is missing")
    chord_data = ChordData()
    try:
        chord_data.load_from_file(analysis_path)
        _select_tracks(chord_data, requested_track)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as error:
        raise GenerationError(f"existing ChordFlask analysis is invalid: {error}") from error
    if not chord_data.beat_times:
        raise GenerationError("existing ChordFlask analysis has no beat timeline")
    return chord_data


def _write_atomic(path: Path, content: str) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            descriptor = -1
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        temporary = ""
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def _lyrics_record(identity: SongIdentity, media: Path, lines) -> LyricsRecord:
    return LyricsRecord(
        0,
        identity.title or media.stem,
        identity.artist or "Unknown Artist",
        identity.album,
        identity.duration,
        lines,
    )


def _external_lrc(media: Path) -> tuple[TimedLyricLine, ...]:
    try:
        text = media.with_suffix(".lrc").read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return ()
    return parse_synced_lyrics(text)


def _select_lyrics(
    media: Path,
    chord_data: ChordData,
    client: LRCLIBClient,
    sources: tuple[str, ...],
    search_hint: str | None,
) -> tuple[LyricsRecord, str]:
    analysis_duration = _analysis_duration(chord_data)
    media_identity = None
    for source in sources:
        if source == "lrc":
            lines = _external_lrc(media)
            if lines:
                media_identity = media_identity or lookup_identity(
                    media, analysis_duration=analysis_duration
                )
                return _lyrics_record(media_identity, media, lines), "lrc"
        elif source == "embedded":
            embedded = get_embedded_lyrics(media)
            if embedded is None:
                continue
            lines = embedded.lines or time_plain_lyrics(embedded.text, chord_data.beat_times)
            if lines:
                media_identity = media_identity or lookup_identity(
                    media, analysis_duration=analysis_duration
                )
                return (
                    _lyrics_record(media_identity, media, lines),
                    f"embedded:{embedded.source}",
                )
        elif source == "lrclib":
            identity = lookup_identity(
                media,
                analysis_duration=analysis_duration,
                include_filename=search_hint is None,
            )
            if not identity.title and not search_hint:
                raise GenerationError("song title could not be determined")
            record = client.lookup(identity, search_hint=search_hint)
            if record is not None:
                return record, "lrclib"
        else:
            raise GenerationError(f'unknown internal lyrics source "{source}"')
    raise GenerationError("no usable lyrics found from configured sources")


def generate_file(
    media: Path,
    *,
    client: LRCLIBClient,
    search_hint: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    track: str = "auto",
    romanize: bool = False,
    romanize_engine: str = DEFAULT_ENGINE,
    lyrics_sources: tuple[str, ...] = DEFAULT_LYRICS_SOURCES,
) -> tuple[str, str]:
    """Generate one sidecar and return ``(status, explanation)``."""
    output_path = media.with_suffix(".cho")
    if output_path.exists() and not force:
        return "skipped", f"{output_path.name} already exists"

    chord_data = _load_analysis(media, track)
    selected_track = chord_data.active_chord_track_id
    record, lyrics_source = _select_lyrics(
        media, chord_data, client, lyrics_sources, search_hint
    )

    beat_chords = PlaybackView(
        chord_data,
        metric_chords=True,
        repeat_mode="chords",
    ).full_beat_view()
    if not beat_chords:
        raise GenerationError("existing ChordFlask analysis has no usable beat/chord grid")
    rows = align_lyrics(
        record.lines,
        beat_times=chord_data.beat_times,
        beat_numbers=chord_data.beat_numbers,
        meter=chord_data.meter_signature,
        beat_chords=beat_chords,
    )
    romanizer = partial(romanize_thai, engine=romanize_engine) if romanize else None
    content = render_chordpro(
        record,
        rows,
        search_hint=search_hint if lyrics_source == "lrclib" else None,
        chord_track_id=selected_track,
        romanize=romanizer,
    )

    # Validate against the same parser used by the web application before publish.
    from chordflask.chordpro_song import parse_chordpro

    parse_chordpro(content)
    line_count = len(record.lines)
    line_label = "line" if line_count == 1 else "lines"
    if lyrics_source == "lrclib":
        lyrics_detail = (
            f"lyrics=lrclib ({line_count} timed {line_label}, "
            f"matched {record.artist} — {record.title})"
        )
    else:
        lyrics_detail = f"lyrics={lyrics_source} ({line_count} timed {line_label})"
    detail = f"{lyrics_detail}; beats={len(chord_data.beat_times)}"
    if romanize:
        detail += f"; romanize={romanize_engine}"
    if dry_run:
        return "dry-run", f"{detail}; would write {output_path.name}"
    _write_atomic(output_path, content)
    return "written", f"{detail}; wrote {output_path.name}"


def _resolve_files(target: Path) -> list[Path] | None:
    from chordflask.chordflask_config import SUPPORTED_MEDIA_SUFFIXES

    if target.is_dir():
        return preferred_media_files(target)
    if target.is_file() and target.suffix.lower() in SUPPORTED_MEDIA_SUFFIXES:
        return [target]
    return None


def run(args, *, client=None) -> int:
    files = _resolve_files(args.target)
    if files is None:
        print(f"ERROR: not a supported media file or directory: {args.target}", file=sys.stderr)
        return 2
    if args.tag is not None and args.target.is_dir():
        print("ERROR: --tag is valid only when the target is one media file", file=sys.stderr)
        return 2
    if args.tag is not None and not args.tag.strip():
        print("ERROR: --tag must not be empty", file=sys.stderr)
        return 2
    lyrics_sources = getattr(args, "lyrics", DEFAULT_LYRICS_SOURCES)
    if args.tag is not None and "lrclib" not in lyrics_sources:
        print("ERROR: --tag requires lrclib in --lyrics", file=sys.stderr)
        return 2

    client = client or LRCLIBClient()
    print(f"Lyrics priority: {' > '.join(lyrics_sources)}")
    failures = 0
    skipped = 0
    written = 0
    for index, media in enumerate(files, 1):
        try:
            status, detail = generate_file(
                media,
                client=client,
                search_hint=args.tag,
                force=args.force,
                dry_run=args.dry_run,
                track=getattr(args, "track", "auto"),
                romanize=getattr(args, "romanize", False),
                romanize_engine=getattr(args, "romanize_engine", DEFAULT_ENGINE),
                lyrics_sources=lyrics_sources,
            )
        except (GenerationError, LRCLIBError, RomanizationError, ValueError) as error:
            failures += 1
            print(f"[{index}/{len(files)}] SKIP {media}: {error}", file=sys.stderr)
            continue
        skipped += status == "skipped"
        written += status == "written"
        print(f"[{index}/{len(files)}] {status.upper()} {media}: {detail}")
    print(f"Done: {len(files)} files, {written} written, {skipped} skipped, {failures} failed")
    return 1 if failures else 0


def main(argv=None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        build_parser().print_help()
        raise SystemExit(0)
    args = build_parser().parse_args(argv)
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
