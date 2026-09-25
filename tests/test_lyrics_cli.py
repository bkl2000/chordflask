from argparse import Namespace
from pathlib import Path

import pytest

from chordflask.chordpro_song import read_chordpro
from chordflask.filerepr import FileRepr
from chordflask_base import ChordData
from chordflask_lyrics import cli
from chordflask_lyrics.embedded import EmbeddedLyrics
from chordflask_lyrics.lrclib import LyricsRecord, SongIdentity, TimedLyricLine
from chordflask_lyrics.romanize import RomanizationError, romanize_thai


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
        "romanize": False,
        "romanize_engine": "thai2rom_onnx",
        "lyrics": cli.DEFAULT_LYRICS_SOURCES,
    }
    values.update(overrides)
    return Namespace(**values)


@pytest.fixture(autouse=True)
def no_embedded_lyrics(monkeypatch):
    monkeypatch.setattr(cli, "get_embedded_lyrics", lambda path: None)


def test_track_cli_defaults_to_auto_and_accepts_explicit_id():
    parser = cli.build_parser()

    assert parser.parse_args(["song.mp3"]).track == "auto"
    assert parser.parse_args(["--track", "btc", "song.mp3"]).track == "btc"


def test_lyrics_cli_defaults_to_lrc_embedded_lrclib_and_preserves_order():
    parser = cli.build_parser()

    assert parser.parse_args(["song.mp3"]).lyrics == ("lrc", "embedded", "lrclib")
    assert parser.parse_args(["--lyrics", "lrclib:lrc", "song.mp3"]).lyrics == (
        "lrclib",
        "lrc",
    )


@pytest.mark.parametrize("value", ["", "lrc:unknown", "lrc:lrc", "lrc::embedded"])
def test_invalid_lyrics_source_specifications_fail_cleanly(value):
    with pytest.raises(SystemExit) as error:
        cli.build_parser().parse_args(["--lyrics", value, "song.mp3"])

    assert error.value.code == 2


def test_romanize_cli_is_optional_and_default_engine_is_onnx():
    parser = cli.build_parser()

    plain = parser.parse_args(["song.mp3"])
    enabled = parser.parse_args(["--romanize", "song.mp3"])
    selected = parser.parse_args(["--romanize-engine", "tltk", "song.mp3"])

    assert plain.romanize is False
    assert enabled.romanize is True
    assert enabled.romanize_engine == "thai2rom_onnx"
    assert selected.romanize_engine == "tltk"


def test_thai_detection_mixed_text_and_requested_engine():
    calls = []

    def fake_romanize(text, *, engine):
        calls.append((text, engine))
        return {"ฉันรักเธอ": "chan rak thoe", "มาก": "mak"}[text]

    assert romanize_thai("Latin only", romanize=fake_romanize) is None
    assert romanize_thai(
        "ฉันรักเธอ very มาก!", engine="tltk", romanize=fake_romanize
    ) == "chan rak thoe very mak!"
    assert calls == [("ฉันรักเธอ", "tltk"), ("มาก", "tltk")]


def test_thai_words_are_segmented_for_readable_spacing():
    calls = []

    def fake_romanize(text, *, engine):
        calls.append((text, engine))
        return {"ฉัน": "chan", "รัก": "rak", "เธอ": "thoe"}[text]

    result = romanize_thai(
        "ฉันรักเธอ",
        romanize=fake_romanize,
        tokenize=lambda text: ["ฉัน", "รัก", "เธอ"],
    )

    assert result == "chan rak thoe"
    assert calls == [
        ("ฉัน", "thai2rom_onnx"),
        ("รัก", "thai2rom_onnx"),
        ("เธอ", "thai2rom_onnx"),
    ]


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
    embedded_calls = []
    monkeypatch.setattr(cli, "get_embedded_lyrics", lambda path: embedded_calls.append(path))
    client = FakeClient(lyrics_record())

    assert cli.generate_file(media, client=client)[0] == "skipped"
    assert embedded_calls == []
    assert client.calls == []
    assert cli.generate_file(media, client=client, force=True, dry_run=True)[0] == "dry-run"
    assert sidecar.read_text(encoding="utf-8") == "old"
    assert cli.generate_file(media, client=client, force=True)[0] == "written"
    assert sidecar.read_text(encoding="utf-8") != "old"
    assert read_chordpro(sidecar)["metadata"]["title"] == "Song"


def test_generation_without_romanize_is_byte_compatible(monkeypatch, tmp_path):
    media = tmp_path / "Artist - Song.mp3"
    make_analysis(media)
    monkeypatch.setattr(cli, "probe_media", lambda path: SongIdentity(duration=8))
    calls = []
    monkeypatch.setattr(cli, "romanize_thai", lambda *a, **k: calls.append((a, k)))

    cli.generate_file(media, client=FakeClient(lyrics_record()))

    assert calls == []
    assert "x_chordflask_romanized" not in media.with_suffix(".cho").read_text()


def test_generation_writes_only_thai_romanization_metadata(monkeypatch, tmp_path):
    media = tmp_path / "Artist - Thai.mp3"
    make_analysis(media)
    monkeypatch.setattr(cli, "probe_media", lambda path: SongIdentity(duration=8))
    record = LyricsRecord(
        2,
        "Thai",
        "Artist",
        None,
        8,
        (TimedLyricLine(0.2, "ฉันรักเธอ"), TimedLyricLine(4.2, "Latin only")),
    )
    calls = []

    def fake_romanize(text, *, engine):
        calls.append((text, engine))
        return "chan rak thoe Latin only" if "ฉัน" in text else None

    monkeypatch.setattr(cli, "romanize_thai", fake_romanize)

    cli.generate_file(
        media,
        client=FakeClient(record),
        romanize=True,
        romanize_engine="royin",
    )

    content = media.with_suffix(".cho").read_text(encoding="utf-8")
    parsed = read_chordpro(media.with_suffix(".cho"))
    lyric_blocks = [block for block in parsed["blocks"] if block["type"] == "line"]
    assert content.count("{x_chordflask_romanized:") == 1
    assert lyric_blocks[0]["romanized"] == "chan rak thoe Latin only"
    assert "".join(run["lyric"] for run in lyric_blocks[0]["runs"]) == "ฉันรักเธอ Latin only"
    assert calls == [("ฉันรักเธอ Latin only", "royin")]


def test_enabled_romanization_adds_nothing_to_latin_only_generation(
    monkeypatch, tmp_path
):
    media = tmp_path / "Artist - Latin.mp3"
    make_analysis(media)
    monkeypatch.setattr(cli, "probe_media", lambda path: SongIdentity(duration=8))
    calls = []

    def fake_romanize(text, *, engine):
        calls.append((text, engine))
        return None

    monkeypatch.setattr(cli, "romanize_thai", fake_romanize)

    cli.generate_file(media, client=FakeClient(lyrics_record()), romanize=True)

    assert "x_chordflask_romanized" not in media.with_suffix(".cho").read_text()
    assert calls == [("first second", "thai2rom_onnx")]


def test_romanization_failure_is_clear_and_does_not_write(monkeypatch, tmp_path, capsys):
    media = tmp_path / "Artist - Thai.mp3"
    make_analysis(media)
    monkeypatch.setattr(cli, "probe_media", lambda path: SongIdentity(duration=8))
    record = LyricsRecord(
        2, "Thai", "Artist", None, 8, (TimedLyricLine(0.2, "ภาษาไทย"),)
    )
    monkeypatch.setattr(
        cli,
        "romanize_thai",
        lambda *a, **k: (_ for _ in ()).throw(
            RomanizationError('Thai romanization engine "tltk" is unavailable')
        ),
    )

    assert cli.run(
        args(media, romanize=True, romanize_engine="tltk"),
        client=FakeClient(record),
    ) == 1
    assert 'engine "tltk" is unavailable' in capsys.readouterr().err
    assert not media.with_suffix(".cho").exists()


def test_missing_base_dependency_points_to_normal_setup(monkeypatch):
    real_import = __import__

    def fail_pythainlp(name, *args, **kwargs):
        if name.startswith("pythainlp"):
            raise ModuleNotFoundError("No module named 'pythainlp'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fail_pythainlp)

    with pytest.raises(RomanizationError, match="rerun make setup"):
        romanize_thai("ภาษาไทย")


def test_romanized_dry_run_does_not_write(monkeypatch, tmp_path):
    media = tmp_path / "Artist - Thai.mp3"
    make_analysis(media)
    monkeypatch.setattr(cli, "probe_media", lambda path: SongIdentity(duration=8))
    record = LyricsRecord(
        2, "Thai", "Artist", None, 8, (TimedLyricLine(0.2, "ภาษาไทย"),)
    )
    monkeypatch.setattr(cli, "romanize_thai", lambda text, *, engine: "phasa thai")

    status, _ = cli.generate_file(
        media,
        client=FakeClient(record),
        romanize=True,
        dry_run=True,
    )

    assert status == "dry-run"
    assert not media.with_suffix(".cho").exists()


def test_missing_embedded_lyrics_fall_back_to_lrclib(monkeypatch, tmp_path):
    media = tmp_path / "Artist - Song.mp3"
    make_analysis(media)
    monkeypatch.setattr(cli, "probe_media", lambda path: SongIdentity(duration=8))
    client = FakeClient(lyrics_record())

    assert cli.generate_file(media, client=client)[0] == "written"
    assert len(client.calls) == 1


def test_same_stem_lrc_wins_over_embedded_and_lrclib(monkeypatch, tmp_path):
    media = tmp_path / "Artist - Song.mp3"
    make_analysis(media)
    media.with_suffix(".lrc").write_text(
        "\ufeff[00:00.20]external first\n[00:04.20]external second\n",
        encoding="utf-8",
    )
    embedded_calls = []
    monkeypatch.setattr(
        cli,
        "get_embedded_lyrics",
        lambda path: embedded_calls.append(path),
    )
    client = FakeClient(lyrics_record())

    status, detail = cli.generate_file(media, client=client)

    assert status == "written"
    assert "lyrics=lrc (2 timed lines)" in detail
    assert embedded_calls == []
    assert client.calls == []
    parsed = read_chordpro(media.with_suffix(".cho"))
    visible = "".join(
        run["lyric"]
        for block in parsed["blocks"]
        if block["type"] == "line"
        for run in block["runs"]
    )
    assert "external first" in visible


def test_missing_and_unusable_lrc_fall_through(monkeypatch, tmp_path):
    missing = tmp_path / "Artist - Missing.mp3"
    untimed = tmp_path / "Artist - Untimed.mp3"
    unreadable = tmp_path / "Artist - Unreadable.mp3"
    for media in (missing, untimed, unreadable):
        make_analysis(media)
    untimed.with_suffix(".lrc").write_text("plain untimed lyrics", encoding="utf-8")
    unreadable.with_suffix(".lrc").write_bytes(b"\xff\xfe")
    monkeypatch.setattr(
        cli,
        "get_embedded_lyrics",
        lambda path: EmbeddedLyrics("ffprobe:lyrics", "embedded first\nembedded second"),
    )

    for media in (missing, untimed, unreadable):
        client = FakeClient(lyrics_record())
        _, detail = cli.generate_file(media, client=client)
        assert "lyrics=embedded:ffprobe:lyrics" in detail
        assert client.calls == []


def test_unusable_embedded_lyrics_fall_through_to_lrclib(monkeypatch, tmp_path):
    media = tmp_path / "Artist - Song.mp3"
    make_analysis(media)
    monkeypatch.setattr(
        cli,
        "get_embedded_lyrics",
        lambda path: EmbeddedLyrics("ffprobe:lyrics", " \n "),
    )
    client = FakeClient(lyrics_record())

    _, detail = cli.generate_file(media, client=client)

    assert "lyrics=lrclib (2 timed lines, matched Artist — Song)" in detail
    assert len(client.calls) == 1


def test_explicit_source_ordering_is_honored(monkeypatch, tmp_path):
    media = tmp_path / "Artist - Song.mp3"
    make_analysis(media)
    media.with_suffix(".lrc").write_text("[00:00.20]external", encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "get_embedded_lyrics",
        lambda path: EmbeddedLyrics("ffprobe:lyrics", "embedded"),
    )
    client = FakeClient(lyrics_record())

    _, detail = cli.generate_file(
        media,
        client=client,
        lyrics_sources=("embedded", "lrc", "lrclib"),
    )

    assert "lyrics=embedded:ffprobe:lyrics" in detail
    assert client.calls == []


@pytest.mark.parametrize("lrc_text", [None, "plain untimed lyrics"])
def test_lrc_only_never_probes_identity_or_uses_network(
    monkeypatch, tmp_path, lrc_text
):
    media = tmp_path / "Artist - Song.mp3"
    make_analysis(media)
    if lrc_text is not None:
        media.with_suffix(".lrc").write_text(lrc_text, encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "lookup_identity",
        lambda *args, **kwargs: pytest.fail("identity must not be probed"),
    )
    client = FakeClient(lyrics_record())

    with pytest.raises(cli.GenerationError, match="no usable lyrics"):
        cli.generate_file(media, client=client, lyrics_sources=("lrc",))

    assert client.calls == []


def test_unknown_internal_lyrics_source_fails_defensively(tmp_path):
    media = tmp_path / "Artist - Song.mp3"
    make_analysis(media)

    with pytest.raises(cli.GenerationError, match='unknown internal lyrics source "bad"'):
        cli.generate_file(media, client=FakeClient(), lyrics_sources=("bad",))


def test_tag_requires_lrclib_source(tmp_path, capsys):
    media = tmp_path / "Artist - Song.mp3"
    make_analysis(media)

    assert cli.run(args(media, tag="Artist Song", lyrics=("lrc",))) == 2
    assert "--tag requires lrclib in --lyrics" in capsys.readouterr().err


def test_external_lrc_supports_romanization(monkeypatch, tmp_path):
    media = tmp_path / "Artist - Thai.mp3"
    make_analysis(media)
    media.with_suffix(".lrc").write_text("[00:00.20]ภาษาไทย", encoding="utf-8")
    monkeypatch.setattr(cli, "romanize_thai", lambda text, *, engine: "phasa thai")

    _, detail = cli.generate_file(
        media,
        client=FakeClient(),
        lyrics_sources=("lrc",),
        romanize=True,
    )

    assert "romanize=thai2rom_onnx" in detail
    assert "{x_chordflask_romanized: phasa thai}" in media.with_suffix(
        ".cho"
    ).read_text(encoding="utf-8")


def test_run_reports_priority_source_and_beat_count(monkeypatch, tmp_path, capsys):
    media = tmp_path / "Artist - Song.mp3"
    make_analysis(media)
    media.with_suffix(".lrc").write_text("[00:00.20]external", encoding="utf-8")

    assert cli.run(args(media), client=FakeClient()) == 0

    output = capsys.readouterr().out
    assert output.count("Lyrics priority: lrc > embedded > lrclib") == 1
    assert "lyrics=lrc (1 timed line); beats=8; wrote Artist - Song.cho" in output


def test_embedded_uslt_is_preferred_without_lrclib_lookup(monkeypatch, tmp_path):
    media = tmp_path / "Artist - Song.mp3"
    make_analysis(media)
    monkeypatch.setattr(cli, "probe_media", lambda path: SongIdentity(duration=8))
    monkeypatch.setattr(
        cli,
        "get_embedded_lyrics",
        lambda path: EmbeddedLyrics("ffprobe:lyrics", "first\nsecond"),
    )
    client = FakeClient(lyrics_record())

    status, detail = cli.generate_file(media, client=client)

    assert status == "written"
    assert "lyrics=embedded:ffprobe:lyrics" in detail
    assert client.calls == []
    parsed = read_chordpro(media.with_suffix(".cho"))
    visible = "".join(
        run["lyric"]
        for block in parsed["blocks"]
        if block["type"] == "line"
        for run in block["runs"]
    )
    assert "first" in visible and "second" in visible


def test_embedded_synced_lyrics_keep_their_timestamps(monkeypatch, tmp_path):
    media = tmp_path / "Artist - Song.mp3"
    make_analysis(media)
    lines = (TimedLyricLine(0.2, "first"), TimedLyricLine(4.2, "second"))
    monkeypatch.setattr(cli, "probe_media", lambda path: SongIdentity(duration=8))
    monkeypatch.setattr(
        cli,
        "get_embedded_lyrics",
        lambda path: EmbeddedLyrics("ffprobe:lyrics", "embedded LRC", lines),
    )
    client = FakeClient(lyrics_record())

    cli.generate_file(media, client=client)

    assert client.calls == []
    parsed = read_chordpro(media.with_suffix(".cho"))
    chord_runs = [
        (run["chord"], run["start_beat"])
        for block in parsed["blocks"]
        if block["type"] == "line"
        for run in block["runs"]
        if run["chord"]
    ]
    assert chord_runs == [("C", 0), ("G", 4)]


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
