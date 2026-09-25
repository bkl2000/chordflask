"""Small LRCLIB client and pure response/matching helpers."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import json
import math
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_ROOT = "https://lrclib.net/api"
_LRC_TIMESTAMP = re.compile(r"\[(\d+):(\d{2}(?:\.\d+)?)\]")
_WORDS = re.compile(r"[\w]+", re.UNICODE)


class LRCLIBError(RuntimeError):
    """A user-facing lookup or response error."""


@dataclass(frozen=True)
class SongIdentity:
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    duration: float | None = None


@dataclass(frozen=True)
class TimedLyricLine:
    """One LRCLIB line timestamp, in media seconds, and its verbatim text."""

    timestamp: float
    text: str


@dataclass(frozen=True)
class LyricsRecord:
    record_id: int
    title: str
    artist: str
    album: str | None
    duration: float | None
    lines: tuple[TimedLyricLine, ...]
    plain_text: str | None = None


def parse_synced_lyrics(value: object) -> tuple[TimedLyricLine, ...]:
    """Parse line-synchronized LRC; blank and untimed lines are ignored."""
    if not isinstance(value, str) or not value:
        return ()
    parsed = []
    for source_line in value.splitlines():
        matches = list(_LRC_TIMESTAMP.finditer(source_line))
        if not matches:
            continue
        text = source_line[matches[-1].end() :]
        if not text:
            continue
        for match in matches:
            timestamp = int(match.group(1)) * 60 + float(match.group(2))
            parsed.append(TimedLyricLine(timestamp, text))
    parsed.sort(key=lambda line: line.timestamp)
    return tuple(parsed)


def parse_record(value: object) -> LyricsRecord | None:
    """Return a record containing usable synchronized or plain lyrics."""
    if not isinstance(value, dict):
        raise LRCLIBError("LRCLIB returned a malformed lyrics record")
    title = value.get("trackName", value.get("name"))
    artist = value.get("artistName")
    record_id = value.get("id")
    if not isinstance(title, str) or not title.strip():
        raise LRCLIBError("LRCLIB returned a record without a track name")
    if not isinstance(artist, str) or not artist.strip():
        raise LRCLIBError("LRCLIB returned a record without an artist name")
    if not isinstance(record_id, int) or isinstance(record_id, bool):
        raise LRCLIBError("LRCLIB returned a record without a valid id")
    duration = value.get("duration")
    if not (
        isinstance(duration, (int, float))
        and not isinstance(duration, bool)
        and math.isfinite(duration)
        and duration > 0
    ):
        duration = None
    album = value.get("albumName")
    if not isinstance(album, str) or not album.strip():
        album = None
    lines = parse_synced_lyrics(value.get("syncedLyrics"))
    if lines:
        return LyricsRecord(record_id, title, artist, album, duration, lines)
    plain_text = value.get("plainLyrics")
    if not isinstance(plain_text, str) or not plain_text.strip():
        return None
    return LyricsRecord(record_id, title, artist, album, duration, (), plain_text)


def parse_response(value: object) -> list[LyricsRecord]:
    """Parse either a get object or search array, retaining usable results."""
    if isinstance(value, dict):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        raise LRCLIBError("LRCLIB returned malformed JSON")
    records = []
    for item in values:
        record = parse_record(item)
        if record is not None:
            records.append(record)
    return records


def _normalized(value: str | None) -> str:
    return " ".join(_WORDS.findall((value or "").casefold()))


def _similarity(left: str | None, right: str | None) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, _normalized(left), _normalized(right)).ratio()


def _query_coverage(query: str, record: LyricsRecord) -> float:
    query_words = set(_WORDS.findall(query.casefold()))
    candidate_words = set(_WORDS.findall(f"{record.artist} {record.title}".casefold()))
    if not query_words:
        return 0.0
    return len(query_words & candidate_words) / len(query_words)


def _duration_matches(expected: float | None, actual: float | None) -> bool:
    if expected is None or actual is None:
        return True
    return abs(expected - actual) <= max(4.0, expected * 0.05)


def select_best_record(
    records: list[LyricsRecord],
    identity: SongIdentity,
    *,
    search_hint: str | None = None,
) -> LyricsRecord | None:
    """Select the best plausible match rather than trusting result ordering."""
    ranked = []
    for record in records:
        if not search_hint and not _duration_matches(identity.duration, record.duration):
            continue
        title_score = _similarity(identity.title, record.title)
        artist_score = _similarity(identity.artist, record.artist)
        if identity.title and title_score < 0.55:
            continue
        if identity.artist and artist_score < 0.45:
            continue
        hint_score = _query_coverage(search_hint, record) if search_hint else 0.0
        if search_hint and hint_score < 0.5:
            continue
        duration_score = 0.0
        if identity.duration is not None and record.duration is not None:
            difference = abs(identity.duration - record.duration)
            if search_hint:
                duration_score = 1.0 / (1.0 + difference)
            else:
                duration_score = 1.0 - min(difference / 10.0, 1.0)
        ranked.append((title_score + artist_score + hint_score + duration_score, -record.record_id, record))
    return max(ranked, default=(0.0, 0, None), key=lambda item: (item[0], item[1]))[2]


class LRCLIBClient:
    """Sequential urllib client for LRCLIB's get and search endpoints."""

    def __init__(self, *, timeout: float = 10.0, minimum_interval: float = 0.25):
        self.timeout = timeout
        self.minimum_interval = minimum_interval
        self.__last_request = 0.0

    def __request(self, endpoint: str, parameters: dict[str, object]) -> object | None:
        delay = self.minimum_interval - (time.monotonic() - self.__last_request)
        if delay > 0:
            time.sleep(delay)
        url = f"{API_ROOT}/{endpoint}?{urlencode(parameters)}"
        request = Request(url, headers={"User-Agent": "ChordFlask lyrics integration"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
        except HTTPError as error:
            if error.code == 404:
                return None
            if error.code == 429:
                retry = error.headers.get("Retry-After")
                detail = f"; retry after {retry} seconds" if retry else ""
                raise LRCLIBError(f"LRCLIB rate limit exceeded{detail}") from error
            raise LRCLIBError(f"LRCLIB request failed with HTTP {error.code}") from error
        except (OSError, URLError) as error:
            raise LRCLIBError(f"LRCLIB request failed: {error}") from error
        finally:
            self.__last_request = time.monotonic()
        try:
            return json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise LRCLIBError("LRCLIB returned invalid JSON") from error

    def lookup(self, identity: SongIdentity, *, search_hint: str | None = None) -> LyricsRecord | None:
        """Look up and validate one synchronized lyrics record."""
        if search_hint:
            response = self.__request("search", {"q": search_hint})
            records = parse_response(response or [])
            return select_best_record(records, identity, search_hint=search_hint)

        if identity.title and identity.artist:
            parameters: dict[str, object] = {
                "track_name": identity.title,
                "artist_name": identity.artist,
            }
            if identity.album:
                parameters["album_name"] = identity.album
            if identity.duration is not None and 1 <= identity.duration <= 3600:
                parameters["duration"] = round(identity.duration)
            response = self.__request("get", parameters)
            if response is not None:
                match = select_best_record(parse_response(response), identity)
                if match is not None:
                    return match

        query = " ".join(part for part in (identity.artist, identity.title) if part)
        if not query:
            return None
        response = self.__request("search", {"q": query})
        return select_best_record(parse_response(response or []), identity)
