from argparse import Namespace
from pathlib import Path

import pytest

from chordflask.chordpro_song import read_chordpro
from chordflask.filerepr import FileRepr
from chordflask_base import ChordData
from chordflask_lyrics import cli
from chordflask_lyrics.lrclib import LyricsRecord, SongIdentity, TimedLyricLine


def make_analysis(media: Path, *, extra_tracks=None):
    media.write_bytes(b"media")
    data = ChordData()
    data.set_chord_track(
        "chordino",
        [
            {"timestamp": 0.0, "chord": "C"},
            {"timestamp": 4.0, "chord": "G"},
        ],
    )
    for track_id, chords, metadata in extra_tracks or ():
        data.set_chord_track(track_id, chords, metadata=metadata)
    data.set_rhythm_track(
        "qm_barbeattracker",
        bpm=60,
        meter_signature=4,
        beat_times=[float(index) for index in range(8)],
        beat_numbers=[1, 2, 3, 4, 1, 2, 3, 4],
    )
    data.save_to_file(FileRepr(media, create=True).get("json"))


class FakeClient:
    def __init__(self, record=None):
        self.record = record
        self.calls = []

    def lookup(self, identity, *, search_hint=None):
        self.calls.append((identity, search_hint))
        return self.record


def lyrics_record():
    return LyricsRecord(
        1,
        "Song",
        "Artist",
        "Album",
        8,
        (TimedLyricLine(0.2, "first"), TimedLyricLine(4.2, "second")),
    )


def track_chords(chord):
    return [
        {"timestamp": 0.0, "chord": chord},
        {"timestamp": 4.0, "chord": "G"},
    ]


def edited_track(chord="Am"):
    return (
        "user_edited",
        track_chords(chord),
        {"sources": {"chord": "chordino", "rhythm": "qm_barbeattracker"}},
    )


def args(target, **overrides):
    values = {
        "target": target,
        "tag": None,
        "track": "auto",
        "force": False,
        "dry_run": False,
    }
    values.update(overrides)
    return Namespace(**values)


def test_track_cli_defaults_to_auto_and_accepts_explicit_id():
    parser = cli.build_parser()

    assert parser.parse_args(["song.mp3"]).track == "auto"
    assert parser.parse_args(["--track", "btc", "song.mp3"]).track == "btc"


def test_filename_and_embedded_metadata_lookup(monkeypatch, tmp_path):
    media = tmp_path / "Filename Artist - Filename Title.mp3"
    monkeypatch.setattr(
        cli,
        "probe_media",
        lambda path: SongIdentity(title="Tagged Title", artist="Tagged Artist", album="Album", duration=9),
    )
    assert cli.lookup_identity(media, analysis_duration=8) == SongIdentity(
        title="Tagged Title", artist="Tagged Artist", album="Album", duration=9
    )
    monkeypatch.setattr(cli, "probe_media", lambda path: SongIdentity())
    assert cli.lookup_identity(media, analysis_duration=8) == SongIdentity(
        title="Filename Title", artist="Filename Artist", duration=8
    )
    assert cli.lookup_identity(
        media, analysis_duration=8, include_filename=False
    ) == SongIdentity(duration=8)


def test_tag_is_passed_exactly_and_preserved_but_not_visible(monkeypatch, tmp_path):
    media = tmp_path / "awkward.mp3"
    make_analysis(media)
    monkeypatch.setattr(cli, "probe_media", lambda path: SongIdentity(duration=8))
    client = FakeClient(lyrics_record())
    hint = r"  Artist Song {live} \\  "
    status, _ = cli.generate_file(media, client=client, search_hint=hint)
    assert status == "written"
    assert client.calls[0][1] == hint
    content = media.with_suffix(".cho").read_text(encoding="utf-8")
    assert r"{x_lrclib_search:   Artist Song \{live\} \\\\  }" in content
    parsed = read_chordpro(media.with_suffix(".cho"))
    visible = "".join(
        run["lyric"] for block in parsed["blocks"] if block["type"] == "line" for run in block["runs"]
    )
    assert hint not in visible
    assert "first" in visible and "second" in visible


def test_existing_force_and_dry_run(monkeypatch, tmp_path):
    media = tmp_path / "Artist - Song.mp3"
    make_analysis(media)
    sidecar = media.with_suffix(".cho")
    sidecar.write_text("old", encoding="utf-8")
    monkeypatch.setattr(cli, "probe_media", lambda path: SongIdentity(duration=8))
    client = FakeClient(lyrics_record())

    assert cli.generate_file(media, client=client)[0] == "skipped"
    assert client.calls == []
    assert cli.generate_file(media, client=client, force=True, dry_run=True)[0] == "dry-run"
    assert sidecar.read_text(encoding="utf-8") == "old"
    assert cli.generate_file(media, client=client, force=True)[0] == "written"
    assert sidecar.read_text(encoding="utf-8") != "old"
    assert read_chordpro(sidecar)["metadata"]["title"] == "Song"


def test_generated_sidecar_preserves_sync_metadata_and_hides_it(monkeypatch, tmp_path):
    media = tmp_path / "Artist - Song.mp3"
    make_analysis(media)
    monkeypatch.setattr(cli, "probe_media", lambda path: SongIdentity(duration=8))

    status, _ = cli.generate_file(media, client=FakeClient(lyrics_record()))
    assert status == "written"

    parsed = read_chordpro(media.with_suffix(".cho"))
    assert parsed["metadata"]["x_chordflask_track"] == "chordino"
    chord_runs = [
        (run["chord"], run["start_beat"], run["end_beat"])
        for block in parsed["blocks"] if block["type"] == "line"
        for run in block["runs"] if run["chord"]
    ]
    # Every generated marker maps to one explicit analyzed beat range.
    assert chord_runs
    assert all(
        isinstance(start, int) and isinstance(end, int) and 0 <= start < end
        for _, start, end in chord_runs
    )
    assert chord_runs == [("C", 0, 4), ("G", 4, 8)]
    content = media.with_suffix(".cho").read_text(encoding="utf-8")
    assert "[C@0]" not in content
    assert "{x_chordflask_beats:" in content
    assert "{x_chordflask_end:" in content
    visible = "".join(
        run["lyric"] for block in parsed["blocks"] if block["type"] == "line"
        for run in block["runs"]
    )
    assert "first" in visible and "second" in visible
    assert "@" not in visible
    assert "x_chordflask" not in visible


@pytest.mark.parametrize(
    ("track", "extra_tracks", "expected_chord"),
    [
        ("chordino", (), "C"),
        ("btc", (("btc", track_chords("Dm"), {}),), "Dm"),
        ("user_edited", (edited_track(),), "Am"),
    ],
)
def test_explicit_track_selection_records_resolved_provenance(
    monkeypatch, tmp_path, track, extra_tracks, expected_chord
):
    media = tmp_path / f"Artist - {track}.mp3"
    make_analysis(media, extra_tracks=extra_tracks)
    monkeypatch.setattr(cli, "probe_media", lambda path: SongIdentity(duration=8))

    status, _ = cli.generate_file(
        media,
        client=FakeClient(lyrics_record()),
        track=track,
    )
    parsed = read_chordpro(media.with_suffix(".cho"))
    markers = [
        run
        for block in parsed["blocks"] if block["type"] == "line"
        for run in block["runs"] if run["chord"]
    ]

    assert status == "written"
    assert markers[0]["chord"] == expected_chord
    assert parsed["metadata"]["x_chordflask_track"] == track


def test_auto_prefers_edited_then_uses_normal_default(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "probe_media", lambda path: SongIdentity(duration=8))
    edited_media = tmp_path / "Artist - Edited.mp3"
    default_media = tmp_path / "Artist - Default.mp3"
    make_analysis(edited_media, extra_tracks=(edited_track(),))
    make_analysis(
        default_media,
        extra_tracks=(("btc", track_chords("Dm"), {}),),
    )

    cli.generate_file(edited_media, client=FakeClient(lyrics_record()))
    cli.generate_file(default_media, client=FakeClient(lyrics_record()), track="auto")

    assert read_chordpro(edited_media.with_suffix(".cho"))["metadata"][
        "x_chordflask_track"
    ] == "user_edited"
    assert read_chordpro(default_media.with_suffix(".cho"))["metadata"][
        "x_chordflask_track"
    ] == "chordino"


def test_explicit_missing_track_fails_without_fallback(monkeypatch, tmp_path):
    media = tmp_path / "Artist - Song.mp3"
    make_analysis(media)
    monkeypatch.setattr(cli, "probe_media", lambda path: SongIdentity(duration=8))
    client = FakeClient(lyrics_record())

    with pytest.raises(cli.GenerationError, match='chord track "btc" is unavailable'):
        cli.generate_file(media, client=client, track="btc")

    assert client.calls == []
    assert not media.with_suffix(".cho").exists()


def test_directory_missing_explicit_track_is_a_per_file_failure(
    monkeypatch, tmp_path, capsys
):
    available = tmp_path / "A - Available.mp3"
    missing = tmp_path / "B - Missing.mp3"
    make_analysis(
        available,
        extra_tracks=(("btc", track_chords("Dm"), {}),),
    )
    make_analysis(missing)
    monkeypatch.setattr(cli, "probe_media", lambda path: SongIdentity(duration=8))
    client = FakeClient(lyrics_record())

    assert cli.run(args(tmp_path, track="btc"), client=client) == 1

    assert available.with_suffix(".cho").exists()
    assert not missing.with_suffix(".cho").exists()
    assert len(client.calls) == 1
    assert 'chord track "btc" is unavailable' in capsys.readouterr().err


def test_missing_analysis_and_no_synchronized_lyrics(monkeypatch, tmp_path):
    missing = tmp_path / "Artist - Missing.mp3"
    missing.write_bytes(b"media")
    client = FakeClient(lyrics_record())
    assert cli.run(args(missing), client=client) == 1
    assert client.calls == []

    media = tmp_path / "Artist - Song.mp3"
    make_analysis(media)
    monkeypatch.setattr(cli, "probe_media", lambda path: SongIdentity(duration=8))
    assert cli.run(args(media), client=FakeClient(None)) == 1
    assert not media.with_suffix(".cho").exists()


def test_directory_uses_preferred_media_continues_and_rejects_tag(monkeypatch, tmp_path):
    first_mp3 = tmp_path / "A - First.mp3"
    first_mp4 = tmp_path / "A - First.mp4"
    second = tmp_path / "B - Second.webm"
    make_analysis(first_mp4)
    first_mp3.write_bytes(b"duplicate")
    second.write_bytes(b"missing analysis")
    monkeypatch.setattr(cli, "probe_media", lambda path: SongIdentity(duration=8))
    client = FakeClient(lyrics_record())

    assert cli.run(args(tmp_path), client=client) == 1
    assert first_mp4.with_suffix(".cho").exists()
    assert len(client.calls) == 1
    assert cli.run(args(tmp_path, tag="Artist Song"), client=client) == 2
