"""Bounded parser for user-supplied lyric-bearing ChordPro song sheets."""

from pathlib import Path
import re


MAX_SONG_BYTES = 1024 * 1024
MAX_SONG_LINE_BYTES = 16 * 1024


class ChordProSongError(ValueError):
    """A safe, user-facing failure while reading a Song sidecar."""

    def __init__(self, message, status_code=422):
        super().__init__(message)
        self.status_code = status_code


_DIRECTIVE_RE = re.compile(
    r"^\{([A-Za-z][A-Za-z0-9_]*)(?:\s*:\s*((?:\\[\\\[\]{}]|[^{}])*))?\}$"
)
_ESCAPED_CHARACTERS = frozenset("[]{}\\")
_METADATA_DIRECTIVES = frozenset(("title", "artist", "subtitle", "key", "capo"))
_SECTION_STARTS = {
    "start_of_verse": ("verse", "Verse"),
    "sov": ("verse", "Verse"),
    "start_of_chorus": ("chorus", "Chorus"),
    "soc": ("chorus", "Chorus"),
    "start_of_bridge": ("bridge", "Bridge"),
    "sob": ("bridge", "Bridge"),
}
_SECTION_ENDS = {
    "end_of_verse": "verse",
    "eov": "verse",
    "end_of_chorus": "chorus",
    "eoc": "chorus",
    "end_of_bridge": "bridge",
    "eob": "bridge",
}
_COMMENTS = {
    "comment": "normal",
    "c": "normal",
    "comment_italic": "italic",
    "ci": "italic",
    "comment_box": "box",
    "cb": "box",
}


def _unescape(value):
    output = []
    index = 0
    while index < len(value):
        if (
            value[index] == "\\"
            and index + 1 < len(value)
            and value[index + 1] in _ESCAPED_CHARACTERS
        ):
            index += 1
        output.append(value[index])
        index += 1
    return "".join(output)


def _literal_line(line):
    return {"type": "line", "runs": [{"chord": None, "lyric": _unescape(line)}]}


def _parse_lyric_line(line):
    runs = []
    lyric = []
    chord = None
    index = 0
    saw_marker = False

    while index < len(line):
        character = line[index]
        if character == "\\" and index + 1 < len(line):
            escaped = line[index + 1]
            if escaped in _ESCAPED_CHARACTERS:
                lyric.append(escaped)
                index += 2
                continue
        if character == "]":
            return _literal_line(line)
        if character != "[":
            lyric.append(character)
            index += 1
            continue

        marker = []
        marker_index = index + 1
        closed = False
        while marker_index < len(line):
            marker_character = line[marker_index]
            if marker_character == "\\" and marker_index + 1 < len(line):
                escaped = line[marker_index + 1]
                if escaped in _ESCAPED_CHARACTERS:
                    marker.append(escaped)
                    marker_index += 2
                    continue
            if marker_character == "[":
                return _literal_line(line)
            if marker_character == "]":
                closed = True
                break
            marker.append(marker_character)
            marker_index += 1
        if not closed or not "".join(marker).strip():
            return _literal_line(line)

        if lyric or chord is not None:
            runs.append({"chord": chord, "lyric": "".join(lyric)})
        chord = "".join(marker)
        lyric = []
        saw_marker = True
        index = marker_index + 1

    if saw_marker:
        runs.append({"chord": chord, "lyric": "".join(lyric)})
        return {"type": "line", "runs": runs}
    return _literal_line(line)


def parse_chordpro(text):
    """Parse the phase-1 ChordPro subset into JSON-serializable records."""
    metadata = {}
    blocks = []
    section_stack = []

    for source_line in text.splitlines():
        if not source_line:
            blocks.append({"type": "blank"})
            continue

        if source_line.startswith("{"):
            match = _DIRECTIVE_RE.fullmatch(source_line)
            if match is None:
                blocks.append(_literal_line(source_line))
                continue
            name = match.group(1).lower()
            value = _unescape(match.group(2) or "")
            if name in _METADATA_DIRECTIVES:
                if match.group(2) is None:
                    blocks.append(_literal_line(source_line))
                else:
                    metadata[name] = value
                continue
            if name in _SECTION_STARTS:
                section, default_heading = _SECTION_STARTS[name]
                section_stack.append(section)
                blocks.append({
                    "type": "section_start",
                    "section": section,
                    "heading": value or default_heading,
                })
                continue
            if name in _SECTION_ENDS:
                section = _SECTION_ENDS[name]
                if match.group(2) is not None or not section_stack or section_stack[-1] != section:
                    blocks.append(_literal_line(source_line))
                else:
                    section_stack.pop()
                    blocks.append({"type": "section_end", "section": section})
                continue
            if name in _COMMENTS:
                if match.group(2) is None:
                    blocks.append(_literal_line(source_line))
                else:
                    blocks.append({"type": "comment", "style": _COMMENTS[name], "text": value})
                continue
            continue

        blocks.append(_parse_lyric_line(source_line))

    return {"metadata": metadata, "blocks": blocks}


def read_chordpro(path):
    """Read strict bounded UTF-8 ChordPro input and return parsed records."""
    path = Path(path)
    try:
        with path.open("rb") as song_file:
            content = song_file.read(MAX_SONG_BYTES + 1)
    except OSError as error:
        raise ChordProSongError("Song sheet could not be read") from error

    if len(content) > MAX_SONG_BYTES:
        raise ChordProSongError("Song sheet is too large", status_code=413)
    if not content:
        raise ChordProSongError("Song sheet is empty")
    for line in content.splitlines():
        if len(line) > MAX_SONG_LINE_BYTES:
            raise ChordProSongError(
                "Song sheet contains an oversized line", status_code=413
            )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ChordProSongError("Song sheet is not valid UTF-8") from error
    if not text.strip():
        raise ChordProSongError("Song sheet is empty")
    return parse_chordpro(text)
