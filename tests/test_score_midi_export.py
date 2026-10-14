"""Score MIDI shares the runtime-free active-generation reader in GUI and CLI."""

from io import BytesIO
import json
import shutil
from zipfile import ZipFile

import pytest

from chordflask.helpers import chordleadsheet_batch, export_cli
from chordflask.score import read_score_midi
from chordflask_base import ChordTrackRepository, analysis_json_path
from chordflask_score import storage
from test_score_display import display as score_display, song as score_song, staged as score_staged


display = score_display
song = score_song
staged = score_staged


def payload(song, format):
    return {"dirname": str(song.parent), "filename": song.name, "format": format}


def run_cli(target, format):
    with pytest.raises(SystemExit) as result:
        export_cli.main(["--format", format, str(target)])
    return result.value.code


def original(path):
    manifest = storage.read_json(path)
    return path.parent / manifest["generation"] / "original.mid"


@pytest.mark.parametrize("frozen", [False, True])
def test_separate_exports_and_all_without_runtime(display, song, monkeypatch, frozen):
    _, client, state, path = display
    content = original(path).read_bytes()
    monkeypatch.setenv("CHORDFLASK_SCORE_VENV", "/missing/runtime")
    monkeypatch.setattr("sys.frozen", frozen, raising=False)
    monkeypatch.setattr(storage, "code_identity", lambda: pytest.fail("producer freshness requires source files"))
    monkeypatch.setattr(chordleadsheet_batch, "_analyze_media", lambda _: pytest.fail("analysis attempted"))
    before = analysis_json_path(song).read_bytes()

    assert run_cli(song, "score-midi") == 0
    assert (song.parent / ".chordflask/song-score.mid").read_bytes() == content
    response = client.post("/download_chords", json=payload(song, "score-midi"))
    assert response.status_code == 200
    assert response.data == content
    assert response.mimetype == "audio/midi"
    assert "song-score.mid" in response.headers["Content-Disposition"]
    assert client.get("/score", query_string={"media": str(song)}).get_json()["score_midi_available"]

    assert run_cli(song, "midi") == 0
    chords = (song.parent / ".chordflask/song-chords-chordino.mid").read_bytes()
    assert chords != content
    assert client.post("/download_chords", json=payload(song, "midi")).data == chords
    assert run_cli(song, "all") == 0
    response = client.post("/download_chords", json=payload(song, "all"))
    assert response.status_code == 200
    with ZipFile(BytesIO(response.data)) as archive:
        assert set(archive.namelist()) == {
            "song-score.mid", "song-chords-chordino.mid", "song-chords-chordino.md",
            "song-chords-chordino.pdf", "song-chords-chordino.cho",
        }
        assert archive.read("song-score.mid") == content
        assert archive.read("song-chords-chordino.mid") == chords
    assert analysis_json_path(song).read_bytes() == before

    # The score export does not require a displayed chord beat grid or snapshot.
    monkeypatch.setattr(state.player, "chord_download_snapshot", lambda: pytest.fail("chord snapshot requested"))
    assert client.post("/download_chords", json=payload(song, "score-midi")).data == content


@pytest.mark.parametrize("damage", [
    "absent", "missing-midi", "hash", "source", "rhythm", "manifest", "symlink",
    "midi-structure", "fingerprint", "unsafe-generation",
])
def test_invalid_score_is_optional_for_all_and_error_for_explicit_export(display, song, monkeypatch, damage, capsys):
    _, client, _, path = display
    midi = original(path)
    if damage == "absent":
        path.unlink()
    elif damage == "missing-midi":
        midi.unlink()
    elif damage == "hash":
        midi.write_bytes(midi.read_bytes() + b"bad")
    elif damage == "source":
        song.write_bytes(b"changed media")
    elif damage == "rhythm":
        repository = ChordTrackRepository()
        data = repository.load(analysis_json_path(song))
        rhythm = data.rhythm_track_data("qm_barbeattracker")
        rhythm["beat_times"][-1] += .1
        data.set_rhythm_track("qm_barbeattracker", **rhythm)
        repository.save(data, analysis_json_path(song))
    elif damage == "manifest":
        path.write_text("{}")
    elif damage == "midi-structure":
        midi.write_bytes(b"invalid MIDI")
        manifest = storage.read_json(path)
        manifest["artifacts"]["original.mid"] = {"size": midi.stat().st_size, "sha256": storage.hash_file(midi)}
        path.write_text(json.dumps(manifest))
    elif damage in ("fingerprint", "unsafe-generation"):
        manifest = storage.read_json(path)
        manifest["pipeline_fingerprint" if damage == "fingerprint" else "generation"] = "../invalid"
        path.write_text(json.dumps(manifest))
    else:
        content = midi.read_bytes()
        midi.unlink()
        outside = song.parent / "outside.mid"
        outside.write_bytes(content)
        midi.symlink_to(outside)
    monkeypatch.setattr(chordleadsheet_batch, "_analyze_media", lambda _: pytest.fail("analysis attempted"))
    assert read_score_midi(song) is None
    assert run_cli(song, "score-midi") == 1
    assert "Score MIDI is missing, stale or invalid" in capsys.readouterr().err
    assert client.post("/download_chords", json=payload(song, "score-midi")).status_code == 404
    assert not (song.parent / ".chordflask/song-score.mid").exists()
    assert run_cli(song, "all") == 0
    response = client.post("/download_chords", json=payload(song, "all"))
    assert response.status_code == 200
    with ZipFile(BytesIO(response.data)) as archive:
        assert len(archive.namelist()) == 4
        assert "song-score.mid" not in archive.namelist()
    assert client.get("/score", query_string={"media": str(song)}).status_code == 404


def test_manifest_selects_active_generation_and_never_falls_back(display, song):
    _, client, _, path = display
    manifest = storage.read_json(path)
    content = original(path).read_bytes()
    other = path.parent / ("f" * 24)
    shutil.copytree(original(path).parent, other)
    # A valid, newer directory with different MIDI must be ignored.
    (other / "original.mid").write_bytes(content.replace(b"\x03\xc0", b"\x01\xe0"))
    assert read_score_midi(song) == content
    manifest["generation"] = other.name
    manifest["artifacts"], _ = storage.validate_artifacts(other)
    path.write_text(json.dumps(manifest))
    assert read_score_midi(song) == (other / "original.mid").read_bytes()
    assert client.post("/download_chords", json=payload(song, "score-midi")).data == read_score_midi(song)
    (other / "original.mid").unlink()
    assert read_score_midi(song) is None


def test_directory_mixed_score_availability_and_explicit_no_analysis(display, song, monkeypatch, capsys):
    missing = song.parent / "missing.mp3"
    missing.write_bytes(b"other media")
    shutil.copyfile(analysis_json_path(song), analysis_json_path(missing))
    monkeypatch.setattr(chordleadsheet_batch, "_analyze_media", lambda _: pytest.fail("analysis attempted"))
    assert run_cli(song.parent, "all") == 0
    assert (song.parent / ".chordflask/song-score.mid").exists()
    assert not (song.parent / ".chordflask/missing-score.mid").exists()
    assert (song.parent / ".chordflask/missing-chords-chordino.mid").exists()
    assert run_cli(song.parent, "score-midi") == 1
    assert "Done: 2 files, 1 failed" in capsys.readouterr().out
    analysis_json_path(missing).unlink()
    assert run_cli(missing, "score-midi") == 1
    assert not analysis_json_path(missing).exists()


@pytest.mark.parametrize("change", ["midi", "manifest"])
def test_reader_rechecks_exported_bytes_and_manifest(display, song, monkeypatch, change):
    from chordflask import score
    _, _, _, path = display
    validate = score.read_score
    def raced(media):
        result = validate(media)
        if change == "midi":
            original(path).write_bytes(b"changed after validation")
        else:
            manifest = storage.read_json(path)
            manifest["generation"] = "a" * 24
            path.write_text(json.dumps(manifest))
        return result
    monkeypatch.setattr(score, "read_score", raced)
    assert read_score_midi(song) is None
