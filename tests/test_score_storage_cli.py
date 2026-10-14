import copy
import json
from pathlib import Path
import shutil

import pytest

from chordflask_base import ChordData, ChordTrackRepository, analysis_json_path
from chordflask_score import cli, storage
from chordflask_score.notation import write_notation
from chordflask_score.runtime import code_identity
from chordflask_score.timing import BeatGrid


@pytest.fixture
def song(tmp_path):
    media = tmp_path / "song.mp3"
    media.write_bytes(b"original media")
    data = ChordData()
    data.set_chord_track("chordino", [{"timestamp": 0, "chord": "C"}, {"timestamp": 1, "chord": "F"}])
    data.set_rhythm_track("qm_barbeattracker", bpm=120, meter_signature=3,
                          beat_times=[i*.5 for i in range(7)], beat_numbers=[1, 2, 3, 1, 2, 3, 1])
    data.user_data = {"keep": "this"}
    analysis_json_path(media).parent.mkdir()
    ChordTrackRepository().save(data, analysis_json_path(media))
    return media


@pytest.fixture
def staged(song):
    root = storage.score_root(song)
    root.mkdir(parents=True)
    directory = root / ".staged"
    directory.mkdir()
    inputs = storage.input_snapshot(song, "original")
    payload = {"notes": [{"pitch": 60, "velocity": 80, "start": 0, "end": 2.4}], "controllers": []}
    mapping = write_notation(payload, BeatGrid.from_track(inputs["rhythm"]), directory / "score.musicxml")
    for row in mapping["measures"]:
        row.update({"page": 1, "svg_id": f'right-measure-{row["number"]}'})
    (directory / "measures.json").write_text(json.dumps(mapping))
    (directory / "notes.json").write_text(json.dumps(payload))
    midi = b'MThd\x00\x00\x00\x06\x00\x00\x00\x01\x03\xc0MTrk\x00\x00\x00\x04\x00\xff\x2f\x00'
    (directory / "original.mid").write_bytes(midi)
    shutil.copyfile(Path(__file__).parent / "fixtures/score/verovio.svg", directory / "page-0001.svg")
    return directory


def pipeline():
    return {"code": code_identity(), "device_request": "auto", "runtime": {"cuda": False},
            "quantization": [4, 3], "hand_split": 60}


def finish(song, staged, monkeypatch):
    monkeypatch.setattr(storage, "probe_source_timeline", lambda _: {"available": False})
    return storage.publish(song, staged, storage.input_snapshot(song, "original"), pipeline())


def test_publication_preserves_existing_data_and_original_midi(song, staged, monkeypatch):
    analysis_before = analysis_json_path(song).read_bytes()
    original = (staged / "original.mid").read_bytes()
    assert storage.classify(song).label == "TODO"
    manifest = finish(song, staged, monkeypatch)
    data = storage.read_json(manifest)
    assert (manifest.parent / data["generation"] / "original.mid").read_bytes() == original
    assert storage.classify(song).label == "CURRENT"
    assert analysis_json_path(song).read_bytes() == analysis_before
    assert song.read_bytes() == b"original media"
    assert storage.classify(song, device="cpu").label == "CURRENT"
    assert storage.classify(song, runtime={"cuda": True}).label == "CURRENT"
    assert storage.classify(song, runtime={"cuda": False, "torch": "changed"}).label == "STALE"


@pytest.mark.parametrize(("stored", "requested"), [("cpu", "auto"), ("auto", "cpu"), ("cpu", "cuda")])
def test_device_choice_does_not_replace_valid_score(song, staged, monkeypatch, stored, requested):
    manifest = finish(song, staged, monkeypatch)
    data = storage.read_json(manifest)
    data["pipeline"]["device_request"] = stored
    data["pipeline"]["device"] = "cpu"
    data["pipeline_fingerprint"] = storage.digest(data["pipeline"])
    manifest.write_text(json.dumps(data))
    before = manifest.read_bytes()
    monkeypatch.setattr(cli, "execute", lambda *args: pytest.fail("CURRENT score reran inference"))
    assert cli.process_one(song, audio_source="original", device=requested,
                           replace=False, runtime={"cuda": False}) is None
    assert manifest.read_bytes() == before


def test_render_failure_retains_valid_generation(song, staged, monkeypatch):
    manifest = finish(song, staged, monkeypatch)
    before = manifest.read_bytes()
    monkeypatch.setattr(cli, "prepare_audio", lambda *args: None)
    def fail(*args):
        raise RuntimeError("render failure")
    monkeypatch.setattr(cli, "execute", fail)
    with pytest.raises(RuntimeError, match="render failure"):
        cli.process_one(song, audio_source="original", device="auto", replace=True, runtime={"cuda": False})
    assert manifest.read_bytes() == before
    assert storage.classify(song).label == "CURRENT"


def test_source_and_artifact_changes_are_stale(song, staged, monkeypatch):
    manifest = finish(song, staged, monkeypatch)
    row = storage.read_json(manifest)
    song.write_bytes(b"changed media")
    assert storage.classify(song).label == "STALE"
    song.write_bytes(b"original media")
    (manifest.parent / row["generation"] / "notes.json").unlink()
    assert storage.classify(song).label == "STALE"


def test_changed_media_with_recorded_qm_provenance_requires_reanalysis(song, staged, monkeypatch):
    data = ChordTrackRepository().load(analysis_json_path(song))
    rhythm = data.rhythm_track_data("qm_barbeattracker")
    rhythm["metadata"]["source_media"] = storage.media_source_identity(song)
    data.set_rhythm_track("qm_barbeattracker", **rhythm)
    ChordTrackRepository().save(data, analysis_json_path(song))
    finish(song, staged, monkeypatch)
    song.write_bytes(b"new recording")
    status = storage.classify(song)
    assert status.label == "STALE"
    assert "reanalyze" in status.reason
    with pytest.raises(storage.StaleRhythmError, match="reanalyze"):
        storage.input_snapshot(song, "original")


def test_corrupt_manifest_and_unsafe_artifacts_are_errors(song, staged, monkeypatch):
    manifest = finish(song, staged, monkeypatch)
    row = storage.read_json(manifest)
    unsafe = copy.deepcopy(row)
    unsafe["generation"] = "../outside"
    manifest.write_text(json.dumps(unsafe))
    assert storage.classify(song).label == "ERROR"
    manifest.write_text(json.dumps(row))
    page = manifest.parent / row["generation"] / "page-0001.svg"
    page.unlink()
    page.symlink_to(Path(__file__).parent / "fixtures/score/verovio.svg")
    assert storage.classify(song).label == "ERROR"


def test_invalid_staging_does_not_publish(song, staged, monkeypatch):
    (staged / "page-0001.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>')
    with pytest.raises(ValueError, match="forbidden"):
        finish(song, staged, monkeypatch)
    assert not (storage.score_root(song) / "manifest.json").exists()


def test_invalid_note_times_do_not_replace_published_generation(song, staged, monkeypatch):
    manifest = finish(song, staged, monkeypatch)
    before = manifest.read_bytes()
    row = storage.read_json(manifest)
    replacement = manifest.parent / ".invalid-note-times"
    shutil.copytree(manifest.parent / row["generation"], replacement)
    notes = replacement / "notes.json"
    payload = json.loads(notes.read_text())
    payload["notes"][0]["end"] = payload["notes"][0]["start"]
    notes.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match=r"note\[0\].*require 0 <= start < end"):
        storage.publish(song, replacement, storage.input_snapshot(song, "original"), pipeline())

    assert manifest.read_bytes() == before
    assert storage.classify(song).label == "CURRENT"


def test_failed_manifest_publication_preserves_previous_result(song, staged, monkeypatch):
    manifest = finish(song, staged, monkeypatch)
    before = manifest.read_bytes()
    row = storage.read_json(manifest)
    replacement = manifest.parent / ".replacement"
    shutil.copytree(manifest.parent / row["generation"], replacement)
    notes = replacement / "notes.json"
    notes.write_text(notes.read_text() + "\n")
    def fail(*args):
        raise OSError("publication failed")
    monkeypatch.setattr(storage, "write_atomic", fail)
    with pytest.raises(OSError, match="publication failed"):
        storage.publish(song, replacement, storage.input_snapshot(song, "original"), pipeline())
    assert manifest.read_bytes() == before
    assert storage.classify(song).label == "CURRENT"


def test_qm_changes_during_generation_abort(song, staged, monkeypatch):
    monkeypatch.setattr(storage, "probe_source_timeline", lambda _: {"available": False})
    inputs = storage.input_snapshot(song, "original")
    data = ChordTrackRepository().load(analysis_json_path(song))
    rhythm = data.rhythm_track_data("qm_barbeattracker")
    rhythm["beat_times"][-1] += .1
    data.set_rhythm_track("qm_barbeattracker", **rhythm)
    ChordTrackRepository().save(data, analysis_json_path(song))
    with pytest.raises(RuntimeError, match="changed during"):
        storage.publish(song, staged, inputs, pipeline())


def test_process_lock_and_symlink_storage_fail_closed(song, tmp_path):
    with storage.score_lock(song):
        with pytest.raises(RuntimeError, match="already running"):
            with storage.score_lock(song):
                pass
    other = tmp_path / "other"
    other.mkdir()
    scores = song.parent / ".chordflask/scores"
    root = storage.score_root(song)
    # Only the empty fixture lock exists; move it aside, preserving it.
    root.rename(scores / "saved")
    root.symlink_to(other, target_is_directory=True)
    assert storage.classify(song).label == "ERROR"
    with pytest.raises(ValueError, match="Symlink"):
        storage.score_root(song)


@pytest.mark.parametrize("relative", ["../outside", "/tmp/outside", "a/../../outside"])
def test_path_traversal_rejected(tmp_path, relative):
    with pytest.raises(ValueError, match="Unsafe"):
        storage.safe_path(tmp_path, relative)


def test_cli_dry_run_is_read_only_and_has_no_runtime_requirement(song, monkeypatch, capsys):
    before = sorted(p.relative_to(song.parent) for p in song.parent.rglob("*"))
    monkeypatch.setattr(cli, "require_runtime", lambda: pytest.fail("dry-run probed runtime"))
    assert cli.main([str(song), "--dry-run"]) == 0
    assert "TODO" in capsys.readouterr().out
    assert before == sorted(p.relative_to(song.parent) for p in song.parent.rglob("*"))


def test_batch_continues_and_reports_errors(song, tmp_path, monkeypatch, capsys):
    broken = tmp_path / "a-broken.mp4"
    broken.write_bytes(b"no analysis")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "ignored.mp3").write_bytes(b"nested")
    visited = []
    monkeypatch.setattr(cli, "require_runtime", lambda: {"cuda": False})
    monkeypatch.setattr(cli, "process_one", lambda media, **kwargs: visited.append(media))
    assert cli.main([str(tmp_path)]) == 1
    assert visited == [song]
    assert "a-broken.mp4: ERROR" in capsys.readouterr().err
    assert cli.main([str(tmp_path / "missing")]) == 2
    assert cli.main([str(nested / "ignored.mp3"), "--audio-source", "no-vocals", "--dry-run"]) == 1


def test_batch_prefers_mp4_for_shared_qm_analysis(song, monkeypatch):
    video = song.with_suffix(".mp4")
    video.write_bytes(b"video variant")
    visited = []
    monkeypatch.setattr(cli, "require_runtime", lambda: {"cuda": False})
    monkeypatch.setattr(cli, "process_one", lambda media, **kwargs: visited.append(media))
    assert cli.main([str(song.parent)]) == 0
    assert visited == [video]


def test_explicit_unpreferred_file_has_clear_error(song, capsys):
    video = song.with_suffix(".mp4")
    video.write_bytes(b"video")
    assert cli.main([str(song), "--dry-run"]) == 2
    assert "preferred media song.mp4" in capsys.readouterr().err
    assert cli.discover(video) == [video]


def test_discovery_uses_casefolded_priority_size_order_and_skips_symlinks(tmp_path):
    for name, size in (("Song.mp3", 1), ("song.MP4", 3), ("other.mp3", 2), ("ignored.webm", 1)):
        (tmp_path / name).write_bytes(b"x" * size)
    (tmp_path / "alias.mp3").symlink_to(tmp_path / "other.mp3")
    assert [p.name for p in cli.discover(tmp_path)] == ["other.mp3", "song.MP4"]


def test_cli_replacement_required(song, staged, monkeypatch):
    finish(song, staged, monkeypatch)
    song.write_bytes(b"source changed")
    monkeypatch.setattr(cli, "require_runtime", lambda: pytest.fail("stale processing without replacement"))
    assert cli.main([str(song)]) == 1


def test_missing_no_vocals_stems_have_actionable_error(song):
    status = storage.classify(song, audio_source="no-vocals")
    assert status.label == "ERROR"
    assert "current Demucs stems" in status.reason


def test_no_vocals_current_and_stale_registered_stems(song, monkeypatch):
    from chordflask_demucs import storage as demucs_storage
    from chordflask_demucs.audio import AudioFacts, hash_file
    from chordflask_demucs.constants import AUDIO_SET_ID
    from chordflask_demucs.runtime import RuntimeInfo
    from chordflask_demucs.validation import build_audio_track_set
    facts = AudioFacts("flac", "flac", 44100, 2, 132300, 3.)
    directory = demucs_storage.stems_root(song) / "generation"
    directory.mkdir(parents=True)
    paths = {name: directory / f"{name}.flac" for name in ("other", "bass", "drums", "vocals")}
    for name, path in paths.items():
        path.write_bytes(name.encode())
    data = ChordTrackRepository().load(analysis_json_path(song))
    data.set_audio_track(AUDIO_SET_ID, build_audio_track_set(
        source=AudioFacts("wav", "pcm_s16le", 44100, 2, 132300, 3.),
        source_hash=hash_file(song), source_size=song.stat().st_size, source_timeline={"available": False},
        runtime=RuntimeInfo(Path("/venv"), Path("/venv/bin/python"), "4.0.1", "2.10.0"),
        device="cpu", stem_paths=paths, stem_facts={n: facts for n in paths},
        stem_hashes={n: hash_file(p) for n, p in paths.items()},
        stem_sizes={n: p.stat().st_size for n, p in paths.items()},
        tail_adjustments={n: 0 for n in paths}, relative_to=song.parent))
    ChordTrackRepository().save(data, analysis_json_path(song))
    monkeypatch.setattr(demucs_storage, "probe_audio", lambda _: facts)
    inputs = storage.input_snapshot(song, "no-vocals")
    assert set(inputs["stems"]) == {"other", "bass", "drums"}
    paths["drums"].write_bytes(b"bad")
    status = storage.classify(song, audio_source="no-vocals")
    assert status.label == "ERROR"
    assert "STALE" in status.reason


def test_no_vocals_mix_contains_all_instrumental_stems(song, tmp_path, monkeypatch):
    paths = {}
    for name in ("other", "bass", "drums"):
        path = tmp_path / f"{name}.flac"
        path.write_bytes(name.encode())
        paths[name] = {"path": path.name}
    commands = []
    monkeypatch.setattr(cli, "executable", lambda _: "ffmpeg")
    def run(command, **kwargs):
        commands.append(command)
        return type("Result", (), {"returncode": 0})()
    monkeypatch.setattr(cli.subprocess, "run", run)
    cli.prepare_audio(song, {"audio_source": "no-vocals", "stems": paths}, tmp_path / "mix.wav")
    command = commands[0]
    assert [Path(command[i+1]).stem for i, arg in enumerate(command) if arg == "-i"] == ["other", "bass", "drums"]
    assert "amix=inputs=3" in command[command.index("-filter_complex") + 1]
    assert not any("demucs" in arg for arg in command)
