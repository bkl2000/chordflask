from io import BytesIO
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
FLASK_DIR = REPO_ROOT / "flask"

if str(FLASK_DIR) not in sys.path:
    sys.path.insert(0, str(FLASK_DIR))

from chordflask_base import ChordData
from chordflask import CLIENT_COOKIE, FlaskMP4App
from chord_markdown import (
    download_track_slug,
    escape_markdown_cell,
    format_chord_markdown,
    group_beats_into_measures,
    safe_track_slug,
)
from filerepr import FileRepr
from mp4playerflask import MP4PlayerFlask


@pytest.fixture(autouse=True)
def isolate_default_analysis_queue(monkeypatch, tmp_path):
    monkeypatch.setenv("CHORDFLASK_QUEUE_DIR", str(tmp_path / "default-queue"))


# ── pure slug helpers ────────────────────────────────────────────────


def test_download_track_slug_uses_edited_for_user_edited():
    assert download_track_slug("user_edited") == "edited"


def test_download_track_slug_slugifies_other_track_ids():
    assert download_track_slug("chordino") == "chordino"
    assert download_track_slug("pytorch_v2") == "pytorch-v2"
    assert download_track_slug("My Custom.Track") == "my-custom-track"


def test_safe_track_slug_falls_back_when_empty():
    assert safe_track_slug("###") == "chords"
    assert safe_track_slug(None) == "chords"


# ── pure Markdown formatting ─────────────────────────────────────────


def _beats(measures):
    """Flatten measure chord lists into (beat_number, chord) beat tuples."""
    beats = []
    for measure in measures:
        for position, chord in enumerate(measure, 1):
            beats.append((position, chord))
    return beats


def test_group_beats_into_measures_uses_beat_numbers_for_pickups():
    measures = group_beats_into_measures(
        ["C", "G", "C", "G", "G", "C"],
        meter=4,
        beat_numbers=[3, 4, 1, 2, 3, 4],
    )
    assert measures == [["C", "G"], ["C", "G", "G", "C"]]


def test_group_beats_into_measures_falls_back_to_meter_chunks():
    assert group_beats_into_measures(["C", "G", "C", "G", "G", "C"], meter=3, beat_numbers=None) == [
        ["C", "G", "C"],
        ["G", "G", "C"],
    ]


def test_group_beats_into_measures_falls_back_to_four_without_meter():
    assert group_beats_into_measures(["C", "G", "C", "G", "G"], meter=None, beat_numbers=None) == [
        ["C", "G", "C", "G"],
        ["G"],
    ]


def test_group_beats_into_measures_rejects_unusable_beat_numbers():
    measures = group_beats_into_measures(["C", "G", "C", "G"], meter=4, beat_numbers=[1, 1, 1, 1])
    assert measures == [["C", "G", "C", "G"]]


def test_group_beats_into_measures_does_not_truncate_mismatched_beat_numbers():
    measures = group_beats_into_measures(["C", "G", "Am", "F", "C"], meter=4, beat_numbers=[1, 2])
    assert measures == [["C", "G", "Am", "F"], ["C"]]


def test_group_beats_into_measures_empty():
    assert group_beats_into_measures([], meter=4, beat_numbers=[]) == []


def test_format_chord_markdown_exact_playable_row_snapshot():
    markdown = format_chord_markdown(
        title="Example",
        chord_track="Edited",
        rhythm_track="QM Bar/Beat Tracker",
        version="Edited",
        transpose=0,
        spelling="Flats",
        bpm=120,
        meter=4,
        beats=[
            (3, "Gbmaj7"),
            (4, "Gbmaj7"),
            (1, "Db7"),
            (2, "Bbm7b5"),
            (3, "Gb/Db"),
            (4, "G/C"),
            (1, "N"),
            (2, "X"),
            (3, "Cmaj13(#11)"),
            (4, "Cmaj13(#11)"),
        ],
    )

    expected = (
        "# Example\n"
        "\n"
        "**120 BPM · 4/4 · Edited · Flats · Transpose 0**\n"
        "\n"
        "Edited · QM Bar/Beat Tracker\n"
        "\n"
        "```text\n"
        "Auftakt (Zählzeiten 3–4)\n"
        "                        Gbmaj7      -          " "\n"
        "\n"
        "Db7         Bbm7b5      Gb/Db       G/C              "
        "N           X           Cmaj13(#11) -          " "\n"
        "\n"
        "```\n"
    )
    assert markdown == expected


def test_format_chord_markdown_adds_extra_space_after_eight_measures():
    beats = []
    for measure in range(10):
        chord = f"C{measure}"
        beats.extend([(1, chord), (2, chord), (3, chord), (4, chord)])

    markdown = format_chord_markdown(
        title="Blocks",
        chord_track="Chordino",
        rhythm_track="QM",
        version="Original",
        transpose=0,
        spelling="Flats",
        meter=4,
        beats=beats,
    )

    code = markdown.split("```text\n", 1)[1].rsplit("\n```", 1)[0]
    rows = [line for line in code.splitlines() if line]

    assert len(rows) == 5
    assert all("Takt" not in row and "|" not in row for row in rows)
    assert "C0" in rows[0] and "C1" in rows[0]
    assert "C6" in rows[3] and "C7" in rows[3]
    assert "C8" in rows[4] and "C9" in rows[4]
    assert f"{rows[3]}\n\n\n{rows[4]}" in code


def test_format_chord_markdown_pads_odd_and_incomplete_final_measure_with_empty_fields():
    markdown = format_chord_markdown(
        title="Remainder",
        chord_track="Chordino",
        rhythm_track="QM",
        version="Original",
        transpose=0,
        spelling="Flats",
        meter=4,
        repeat_mode="chords",
        beats=_beats([["C"] * 4, ["G"] * 4, ["Am", "F"]]),
    )

    code = markdown.split("```text\n", 1)[1].rsplit("\n```", 1)[0]
    rows = [line for line in code.splitlines() if line]

    assert len(rows) == 2
    assert len(rows[0]) == len(rows[1]) == 92
    assert rows[1].startswith("Am         F")
    assert rows[1][21:] == " " * 71


def test_format_chord_markdown_groups_three_four_and_pickups():
    markdown = format_chord_markdown(
        title="Waltz",
        chord_track="Chordino",
        rhythm_track="QM",
        version="Original",
        transpose=0,
        spelling="Flats",
        meter=3,
        beats=[(3, "C"), (1, "G"), (2, "G"), (3, "Am"), (1, "F")],
    )

    code = markdown.split("```text\n", 1)[1].rsplit("\n```", 1)[0]
    lines = [line for line in code.splitlines() if line]

    assert "**3/4 · Original · Flats · Transpose 0**" in markdown
    assert lines[0] == "Auftakt (Zählzeiten 3)"
    assert lines[1] == "                      C         "
    assert len(lines[2]) == 70
    assert lines[2].startswith("G          -          Am")
    assert lines[2][38:].startswith("F")


def test_format_chord_markdown_chords_mode_writes_every_beat():
    markdown = format_chord_markdown(
        title="Chords",
        chord_track="Chordino",
        rhythm_track="QM",
        version="Original",
        transpose=0,
        spelling="Flats",
        meter=4,
        beats=_beats([["C", "C", "G", "G"]]),
        repeat_mode="chords",
    )

    code = markdown.split("```text\n", 1)[1].rsplit("\n```", 1)[0]
    assert "C          C          G          G" in code
    assert "-" not in code


def test_format_chord_markdown_rejects_unknown_repeat_mode():
    with pytest.raises(ValueError, match="repeat_mode"):
        format_chord_markdown(
            title="Song",
            chord_track="Chordino",
            rhythm_track="QM",
            version="Original",
            transpose=0,
            spelling="Flats",
            beats=[(1, "C")],
            repeat_mode="invalid",
        )


def test_format_chord_markdown_changes_mode_marks_held_measure_start_with_dash():
    markdown = format_chord_markdown(
        title="Held",
        chord_track="Chordino",
        rhythm_track="QM",
        version="Original",
        transpose=0,
        spelling="Flats",
        meter=4,
        beats=[(1, "C"), (2, "C"), (3, "C"), (4, "C"), (1, "C"), (2, "G"), (3, "G"), (4, "G")],
    )

    code = markdown.split("```text\n", 1)[1].rsplit("\n```", 1)[0]
    assert "C          -          -          -               -          G          -          -" in code


def test_format_chord_markdown_never_replaces_n_or_x_with_dash():
    markdown = format_chord_markdown(
        title="Unknowns",
        chord_track="Chordino",
        rhythm_track="QM",
        version="Original",
        transpose=0,
        spelling="Flats",
        meter=4,
        beats=_beats([["N", "N", "X", "X"]]),
    )

    code = markdown.split("```text\n", 1)[1].rsplit("\n```", 1)[0]
    assert "N          N          X          X" in code


def test_format_chord_markdown_missing_meter_falls_back_to_four_beats():
    markdown = format_chord_markdown(
        title="Fallback",
        chord_track="Chordino",
        rhythm_track="QM",
        version="Original",
        transpose=0,
        spelling="Sharps",
        beats=_beats([["C", "D", "E", "F"], ["G"]]),
    )

    assert "**Original · Sharps · Transpose 0**" in markdown
    code = markdown.split("```text\n", 1)[1].rsplit("\n```", 1)[0]
    assert "C          D          E          F               G" in code
    assert "4/4" not in markdown


def test_format_chord_markdown_omits_optional_metadata():
    markdown = format_chord_markdown(
        title="Song",
        chord_track="Chordino",
        rhythm_track="QM",
        version="Original",
        transpose=0,
        spelling="Sharps",
        beats=[(1, "N")],
    )

    assert "BPM" not in markdown
    assert "4/4" not in markdown
    assert "Unicode" not in markdown
    assert "Sharps" in markdown
    assert "```text\nN" in markdown


def test_format_chord_markdown_marks_unicode_symbols():
    markdown = format_chord_markdown(
        title="Song",
        chord_track="Chordino",
        rhythm_track="QM",
        version="Original",
        transpose=0,
        spelling="Flats",
        unicode_symbols=True,
        beats=[(1, "G\u266dm7"), (2, "G\u266dm7")],
    )

    assert "Unicode" in markdown
    assert "G\u266dm7" in markdown
    assert "G\u266dm7       -" in markdown


def test_format_chord_markdown_escapes_pipes_and_newlines():
    markdown = format_chord_markdown(
        title="Song | Part",
        chord_track="Chordino",
        rhythm_track="QM",
        version="Original",
        transpose=0,
        spelling="Flats",
        beats=[(1, "C|D")],
    )

    assert markdown.startswith("# Song \\| Part\n")
    assert "```text\nC|D" in markdown


def test_format_chord_markdown_blank_beat_numbers():
    markdown = format_chord_markdown(
        title="Song",
        chord_track="Chordino",
        rhythm_track="QM",
        version="Original",
        transpose=0,
        spelling="Flats",
        meter=4,
        beats=[("", "C"), ("", "C"), ("", "G"), ("", "G"), ("", "C")],
    )

    code = markdown.split("```text\n", 1)[1].rsplit("\n```", 1)[0]
    assert "C          -          G          -               C" in code


def test_escape_markdown_cell_handles_none_and_backslashes():
    assert escape_markdown_cell(None) == ""
    assert escape_markdown_cell("a\\b") == "a\\\\b"
    assert escape_markdown_cell("a\nb") == "a b"


# ── route helpers and behavior ───────────────────────────────────────


TEST_CLIENT_ID = "test-client"


def _state(app_wrapper):
    return app_wrapper.clients.get_or_create(TEST_CLIENT_ID)


def make_client():
    app_wrapper = FlaskMP4App()
    client = app_wrapper.app.test_client()
    app_wrapper.clients.get_or_create(TEST_CLIENT_ID)
    client.set_cookie(CLIENT_COOKIE, TEST_CLIENT_ID)
    return app_wrapper, client


def _track_data(*, edited=False, empty_beats=False):
    cd = ChordData()
    cd.set_chord_track(
        "chordino",
        [
            {"timestamp": 0.0, "chord": "C"},
            {"timestamp": 1.0, "chord": "G"},
        ],
    )
    beat_times = [] if empty_beats else [0.0, 0.5, 1.0, 1.5]
    beat_numbers = [] if empty_beats else [1, 2, 3, 4]
    cd.set_rhythm_track(
        "qm_barbeattracker",
        bpm=120,
        meter_signature=4,
        beat_times=beat_times,
        beat_numbers=beat_numbers,
    )
    if edited:
        cd.create_beat_aligned_track("user_edited", metadata={"display_name": "Edited"})
        cd.select_chord_track("user_edited")
    return cd


def _activate(app_wrapper, tmp_path, *, name="song.mp4", edited=False, empty_beats=False):
    media = tmp_path / name
    media.write_bytes(b"media")
    file_repr = FileRepr(str(media), datapath=str(tmp_path / ".chordflask"), create=True)
    _track_data(edited=edited, empty_beats=empty_beats).save_to_file(file_repr.get("json"))
    _state(app_wrapper).file_repr = file_repr
    _state(app_wrapper).player = MP4PlayerFlask(file_repr)
    _state(app_wrapper).player.set_prefer_flats(True)
    _state(app_wrapper).player.set_repeat_mode("changes")
    if edited:
        _state(app_wrapper).player.set_chord_version("edited")
    return media


def _payload(tmp_path, name="song.mp4", **extra):
    payload = {"dirname": str(tmp_path), "filename": name}
    payload.update(extra)
    return payload


def _download_archive(response):
    with ZipFile(BytesIO(response.data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _download_markdown(response):
    files = _download_archive(response)
    markdown_name = next(name for name in files if name.endswith(".md"))
    return files[markdown_name].decode("utf-8")


def test_download_chords_returns_markdown_and_pdf_zip(tmp_path):
    app_wrapper, client = make_client()
    _activate(app_wrapper, tmp_path)

    response = client.post("/download_chords", json=_payload(tmp_path))

    assert response.status_code == 200
    assert response.content_type == "application/zip"
    disposition = response.headers["Content-Disposition"]
    assert "song-chords-chordino.zip" in disposition
    files = _download_archive(response)
    assert set(files) == {
        "song-chords-chordino.md",
        "song-chords-chordino.pdf",
    }
    assert files["song-chords-chordino.pdf"].startswith(b"%PDF")
    body = files["song-chords-chordino.md"].decode("utf-8")
    assert body.startswith("# song\n")
    assert "**120 BPM · 4/4 · Original · Flats · Transpose 0**" in body
    assert "Chordino · QM Bar/Beat Tracker" in body
    assert "```text\n" in body
    assert "C          -          G          -" in body
    assert "|" not in body
    assert not list((tmp_path / ".chordflask").glob("song-chords-*"))


def test_download_chords_uses_absolute_beat_numbers(tmp_path):
    app_wrapper, client = make_client()
    _activate(app_wrapper, tmp_path)
    _state(app_wrapper).player.chord_data.set_rhythm_track(
        "qm_barbeattracker",
        bpm=120,
        meter_signature=4,
        beat_times=[index / 2 for index in range(8)],
        beat_numbers=[3, 4, 1, 2, 3, 4, 1, 2],
    )
    response = client.post("/download_chords", json=_payload(tmp_path))

    assert response.status_code == 200
    body = _download_markdown(response)
    assert "Auftakt (Zählzeiten 3–4)" in body
    assert "                      C          -" in body
    assert "G          -          -          -" in body


def test_download_chords_uses_edited_slug_and_version(tmp_path):
    app_wrapper, client = make_client()
    _activate(app_wrapper, tmp_path, edited=True)

    response = client.post("/download_chords", json=_payload(tmp_path))

    assert response.status_code == 200
    assert "song-chords-edited.zip" in response.headers["Content-Disposition"]
    body = _download_markdown(response)
    assert "· Edited ·" in body
    assert "Edited · QM Bar/Beat Tracker" in body


def test_download_chords_rejects_stale_media(tmp_path):
    app_wrapper, client = make_client()
    _activate(app_wrapper, tmp_path)
    (tmp_path / "other.mp4").write_bytes(b"x")

    response = client.post("/download_chords", json=_payload(tmp_path, "other.mp4"))

    assert response.status_code == 409
    assert "not the active file" in response.get_json()["error"]


def test_download_chords_rejects_uninitialized_player(tmp_path):
    _, client = make_client()
    (tmp_path / "song.mp4").write_bytes(b"x")

    response = client.post("/download_chords", json=_payload(tmp_path))

    assert response.status_code == 409
    assert "Player not initialized" in response.get_json()["error"]


def test_download_chords_rejects_empty_beat_grid(tmp_path):
    app_wrapper, client = make_client()
    _activate(app_wrapper, tmp_path, empty_beats=True)

    response = client.post("/download_chords", json=_payload(tmp_path))

    assert response.status_code == 409
    assert "no beat grid" in response.get_json()["error"]


def test_download_chords_rejects_malformed_payload(tmp_path):
    app_wrapper, client = make_client()
    _activate(app_wrapper, tmp_path)

    response = client.post("/download_chords", data="not json")

    assert response.status_code == 400


def test_download_chords_returns_no_partial_zip_when_pdf_rendering_fails(
    tmp_path, monkeypatch
):
    app_wrapper, client = make_client()
    _activate(app_wrapper, tmp_path)

    def fail_render(self, markdown):
        raise OSError("render failed")

    monkeypatch.setattr("chordflask.ChordSheetPdfRenderer.render_markdown", fail_render)

    response = client.post("/download_chords", json=_payload(tmp_path))

    assert response.status_code == 500
    assert response.content_type == "application/json"
    assert response.get_json() == {"error": "Could not render the chord leadsheet PDF."}


def test_download_chords_snapshot_uses_metric_filtered_full_beat_view(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    file_repr = FileRepr(str(media), datapath=str(tmp_path / ".chordflask"), create=True)

    beat_count = 32
    cd = ChordData()
    cd.set_chord_track(
        "chordino",
        [
            {"timestamp": 0.0, "chord": "C"},
            {"timestamp": 0.6, "chord": "D"},
            {"timestamp": 0.8, "chord": "C"},
            {"timestamp": 1.6, "chord": "G"},
        ],
    )
    cd.set_rhythm_track(
        "qm_barbeattracker",
        bpm=120,
        meter_signature=4,
        beat_times=[index * 0.5 for index in range(beat_count)],
        beat_numbers=[index % 4 + 1 for index in range(beat_count)],
    )
    cd.save_to_file(file_repr.get("json"))

    app_wrapper, client = make_client()
    _state(app_wrapper).file_repr = file_repr
    _state(app_wrapper).player = MP4PlayerFlask(file_repr, metric_chords=True)
    _state(app_wrapper).player.set_prefer_flats(True)
    _state(app_wrapper).player.set_repeat_mode("changes")

    response = client.post("/download_chords", json=_payload(tmp_path))

    assert response.status_code == 200
    body = _download_markdown(response)
    assert "C          -          -          G" in body


def test_download_chords_uses_chords_repeat_mode(tmp_path):
    app_wrapper, client = make_client()
    _activate(app_wrapper, tmp_path)
    _state(app_wrapper).player.set_repeat_mode("chords")

    response = client.post("/download_chords", json=_payload(tmp_path))

    assert response.status_code == 200
    body = _download_markdown(response)
    assert "C          C          G          G" in body
    assert "-" not in body.split("```text\n", 1)[1]


def test_download_chords_uses_named_tracks_unicode_slash_chords_and_n_x(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    file_repr = FileRepr(str(media), datapath=str(tmp_path / ".chordflask"), create=True)
    cd = ChordData()
    cd.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "C"}])
    cd.set_chord_track(
        "other",
        [
            {"timestamp": 0.0, "chord": "C#/G#"},
            {"timestamp": 0.5, "chord": "N"},
            {"timestamp": 1.0, "chord": "X"},
            {"timestamp": 1.5, "chord": "F#/C#"},
        ],
        metadata={"display_name": "Neural"},
    )
    cd.set_rhythm_track(
        "qm_barbeattracker",
        bpm=120,
        meter_signature=4,
        beat_times=[0.0, 0.5, 1.0, 1.5],
        beat_numbers=[1, 2, 3, 4],
    )
    cd.set_rhythm_track(
        "other_rhythm",
        bpm=100,
        meter_signature=4,
        beat_times=[0.0, 0.5, 1.0, 1.5],
        beat_numbers=[1, 2, 3, 4],
        metadata={"display_name": "Pulse"},
    )
    cd.save_to_file(file_repr.get("json"))

    app_wrapper, client = make_client()
    _state(app_wrapper).file_repr = file_repr
    _state(app_wrapper).player = MP4PlayerFlask(file_repr, use_unicode=True)
    _state(app_wrapper).player.set_prefer_flats(True)
    _state(app_wrapper).player.set_repeat_mode("chords")
    _state(app_wrapper).player.select_analysis_tracks(chord_track_id="other", rhythm_track_id="other_rhythm")

    response = client.post("/download_chords", json=_payload(tmp_path))

    assert response.status_code == 200
    assert "song-chords-other.zip" in response.headers["Content-Disposition"]
    body = _download_markdown(response)
    assert "**100 BPM · 4/4 · Original · Flats · Transpose 0 · Unicode**" in body
    assert "Neural · Pulse" in body
    assert "D♭/A♭      N          X          G♭/D♭" in body


# ── browser contract ─────────────────────────────────────────────────


def test_index_contains_save_control_and_download_contract():
    _, client = make_client()

    body = client.get("/").get_data(as_text=True)

    assert 'id="saveButton"' in body
    assert 'aria-label="Download chords as Markdown and PDF"' in body
    assert "'chords.zip'" in body
    assert "#saveButton" in body
    assert "fetch('/download_chords'" in body
    assert "function updateSaveButton()" in body
    assert "function downloadChords()" in body
    assert "function filenameFromDisposition(disposition)" in body
    assert "URL.createObjectURL(blob)" in body
    assert "URL.revokeObjectURL(url)" in body
    assert "let saveRequestInFlight = false;" in body
    assert "saveButton.addEventListener('click', downloadChords)" in body


def test_index_save_busy_state_guards_ambiguous_views():
    _, client = make_client()

    body = client.get("/").get_data(as_text=True)

    save_update = body[
        body.index("function updateSaveButton") : body.index("function filenameFromDisposition")
    ]
    assert "loadRequestInFlight" in save_update
    assert "editRequestInFlight" in save_update
    assert "saveRequestInFlight" in save_update
    assert "trackRequestInFlight" in save_update
    assert "queuedAnalysisPaths.has(loadedMediaPath)" in save_update
