"""Shared, pure export model for chord grids and existing local lyrics."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ExportLyricRun:
    """One lyric fragment, optionally anchored to an analyzed beat."""

    lyric: str
    chord: str | None = None
    start_beat: int | None = None
    end_beat: int | None = None


@dataclass(frozen=True)
class ExportLyricBlock:
    """A display block retained from an existing ChordPro song sheet."""

    type: str
    runs: tuple[ExportLyricRun, ...] = ()
    romanized: str | None = None
    section: str | None = None
    heading: str | None = None
    comment_style: str | None = None
    text: str | None = None
    line_start_beat: int | None = None
    line_end_beat: int | None = None


@dataclass(frozen=True)
class ExportSheet:
    """One authoritative export input shared by all document renderers."""

    title: str
    chord_track: str
    rhythm_track: str
    version: str
    transpose: int
    spelling: str
    unicode_symbols: bool
    bpm: int | float | None
    meter: int | None
    beats: tuple[tuple[int | str, str], ...]
    repeat_mode: str
    lyrics: tuple[ExportLyricBlock, ...] = ()


def build_export_sheet(title, snapshot, song=None):
    """Combine the current display snapshot with lyrics from a parsed sidecar.

    Sidecar chord labels are deliberately discarded. A synchronized marker is
    replaced by the chord at the same absolute beat in the current snapshot;
    an unsynchronized marker becomes lyric-only rather than leaking a stale
    chord from another analysis track.
    """
    current_chords = [chord for _, chord in snapshot["beats"]]
    lyric_blocks = []
    for block in (song or {}).get("blocks", ()):
        block_type = block.get("type")
        if block_type == "line":
            runs = []
            for run in block.get("runs", ()):
                start = run.get("start_beat")
                chord = None
                if run.get("chord") is not None and isinstance(start, int):
                    if 0 <= start < len(current_chords):
                        chord = current_chords[start]
                runs.append(ExportLyricRun(
                    lyric=str(run.get("lyric", "")),
                    chord=chord,
                    start_beat=start if isinstance(start, int) else None,
                    end_beat=(
                        run.get("end_beat")
                        if isinstance(run.get("end_beat"), int)
                        else None
                    ),
                ))
            lyric_blocks.append(ExportLyricBlock(
                type="line",
                runs=tuple(runs),
                romanized=block.get("romanized"),
                line_start_beat=block.get("line_start_beat"),
                line_end_beat=block.get("line_end_beat"),
            ))
        elif block_type in {"blank", "section_end"}:
            lyric_blocks.append(ExportLyricBlock(
                type=block_type,
                section=block.get("section"),
            ))
        elif block_type == "section_start":
            lyric_blocks.append(ExportLyricBlock(
                type=block_type,
                section=block.get("section"),
                heading=block.get("heading"),
            ))
        elif block_type == "comment":
            lyric_blocks.append(ExportLyricBlock(
                type=block_type,
                comment_style=block.get("style"),
                text=block.get("text"),
            ))

    return ExportSheet(
        title=title,
        chord_track=snapshot["chord_track_label"],
        rhythm_track=snapshot["rhythm_track_label"],
        version=snapshot["version"].capitalize(),
        transpose=snapshot["transpose"],
        spelling="Flats" if snapshot["prefer_flats"] else "Sharps",
        unicode_symbols=snapshot["use_unicode"],
        bpm=snapshot["bpm"],
        meter=snapshot["meter"],
        beats=tuple(snapshot["beats"]),
        repeat_mode=snapshot["repeat_mode"],
        lyrics=tuple(lyric_blocks),
    )


def lyric_line_text(block):
    """Return one lyric line with the model's current chord markers."""
    return "".join(
        (f"[{run.chord}]" if run.chord is not None else "") + run.lyric
        for run in block.runs
    )
