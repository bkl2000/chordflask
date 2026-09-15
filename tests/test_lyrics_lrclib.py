import json

import pytest

from chordflask_lyrics import lrclib
from chordflask_lyrics.lrclib import (
    LRCLIBClient,
    LRCLIBError,
    LyricsRecord,
    SongIdentity,
    TimedLyricLine,
    parse_response,
    parse_synced_lyrics,
    select_best_record,
)


def record_data(**overrides):
    value = {
        "id": 7,
        "trackName": "Hotel California",
        "artistName": "Eagles",
        "albumName": "Hotel California",
        "duration": 391.0,
        "plainLyrics": "plain only",
        "syncedLyrics": "[00:01.25]First line\n[00:05.00]Second [line]",
    }
    value.update(overrides)
    return value


def test_parses_line_synchronized_lyrics_and_preserves_text():
    assert parse_synced_lyrics("[00:01.25] First\n[01:02.5]Second [line]") == (
        TimedLyricLine(1.25, " First"),
        TimedLyricLine(62.5, "Second [line]"),
    )


def test_response_retains_synced_and_ignores_plain_only_records():
    records = parse_response(
        [
            record_data(id=1, syncedLyrics=None),
            record_data(id=2),
        ]
    )
    assert [record.record_id for record in records] == [2]
    assert records[0].lines[0].text == "First line"


@pytest.mark.parametrize("payload", [None, "", 42, {"id": 1}, [{"id": 1}]])
def test_malformed_or_empty_response_is_handled(payload):
    if payload == "":
        with pytest.raises(LRCLIBError, match="malformed JSON"):
            parse_response(payload)
    elif payload is None or payload == 42:
        with pytest.raises(LRCLIBError, match="malformed JSON"):
            parse_response(payload)
    else:
        with pytest.raises(LRCLIBError, match="track name"):
            parse_response(payload)
    assert parse_response([]) == []


def test_selection_does_not_accept_first_bad_or_plain_result():
    records = parse_response(
        [
            record_data(id=1, trackName="Unrelated", artistName="Elsewhere"),
            record_data(id=2, duration=390.0),
        ]
    )
    selected = select_best_record(
        records,
        SongIdentity(title="Hotel California", artist="Eagles", duration=391.5),
    )
    assert selected.record_id == 2


def test_explicit_search_hint_and_duration_still_validate_candidates():
    good = parse_response(record_data(id=9))[0]
    wrong_duration = LyricsRecord(
        10,
        good.title,
        good.artist,
        good.album,
        200,
        good.lines,
    )
    identity = SongIdentity(duration=391)
    assert select_best_record([wrong_duration, good], identity, search_hint="Eagles Hotel California") == good
    assert select_best_record([good], identity, search_hint="Other Artist Unknown Song") is None


def test_sample_response_is_json_serializable_for_network_fixture_shape():
    assert json.loads(json.dumps(record_data()))["syncedLyrics"].startswith("[")


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self.payload


def test_client_automatic_metadata_lookup_uses_get(monkeypatch):
    urls = []

    def open_request(request, timeout):
        urls.append(request.full_url)
        return FakeResponse(record_data())

    monkeypatch.setattr(lrclib, "urlopen", open_request)
    client = LRCLIBClient(minimum_interval=0)
    selected = client.lookup(
        SongIdentity(title="Hotel California", artist="Eagles", album="Album", duration=391)
    )
    assert selected.record_id == 7
    assert len(urls) == 1
    assert "/api/get?" in urls[0]
    assert "track_name=Hotel+California" in urls[0]
    assert "artist_name=Eagles" in urls[0]


def test_client_explicit_tag_uses_search_and_ranks_all_results(monkeypatch):
    urls = []

    def open_request(request, timeout):
        urls.append(request.full_url)
        return FakeResponse(
            [
                record_data(id=1, trackName="Unrelated", artistName="Elsewhere"),
                record_data(id=2),
            ]
        )

    monkeypatch.setattr(lrclib, "urlopen", open_request)
    selected = LRCLIBClient(minimum_interval=0).lookup(
        SongIdentity(duration=391), search_hint="Eagles Hotel California"
    )
    assert selected.record_id == 2
    assert len(urls) == 1
    assert "/api/search?q=Eagles+Hotel+California" in urls[0]
