"""Canonical media-byte provenance independent of validity and completion."""

import hashlib
import os
from pathlib import Path

import pytest

from chordflask.canonical_analysis import analyze_media
from chordflask.filerepr import FileRepr
from chordflask.helpers import analyze_cli
from chordflask_base import (
    ChordData, canonical_source_status, is_canonical_analysis_complete,
    media_source_identity, record_canonical_source,
)


def complete():
    data = ChordData()
    data.set_chord_track("chordino", [{"timestamp": 0., "chord": "C"}], metadata={"engine": "keep"})
    data.set_rhythm_track("qm_barbeattracker", bpm=60, meter_signature=4,
                          beat_times=[0., 1.], beat_numbers=[1, 2], metadata={"engine": "keep"})
    return data


class FakeAnalyzer:
    calls = []

    def __init__(self, media, directory):
        self.file = FileRepr(media, directory)

    def process(self):
        self.calls.append(Path(self.file.get()).read_bytes())
        complete().save_to_file(self.file.get("json"))


@pytest.fixture
def song(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDFLASK_QUEUE_DIR", str(tmp_path / "queue"))
    FakeAnalyzer.calls = []
    media = tmp_path / "song.mp3"
    media.write_bytes(b"source A")
    return media, FileRepr(media, create=True)


def test_new_analysis_records_both_track_identities_and_preserves_metadata(song):
    media, fr = song
    result = analyze_media(media, analyzer_cls=FakeAnalyzer)
    identity = {"sha256": hashlib.sha256(media.read_bytes()).hexdigest(), "size": media.stat().st_size}
    for metadata in [result.chord_track_metadata("chordino"), result.rhythm_track_metadata("qm_barbeattracker")]:
        assert metadata["source_media"] == identity
        assert metadata["engine"] == "keep"
    assert canonical_source_status(ChordData(fr.get("json")), media) == "current"
    analyze_media(media, analyzer_cls=FakeAnalyzer)
    assert FakeAnalyzer.calls == [b"source A"]


@pytest.mark.parametrize("replacement", [b"source B", b"source B is larger"])
def test_same_name_changed_bytes_stale_and_normal_analysis_refreshes(song, replacement):
    media, fr = song
    analyze_media(media, analyzer_cls=FakeAnalyzer)
    old = ChordData(fr.get("json"))
    timestamp = media.stat().st_mtime_ns
    media.write_bytes(replacement)
    os.utime(media, ns=(timestamp, timestamp))
    assert is_canonical_analysis_complete(old)
    assert canonical_source_status(old, media) == "stale"
    assert analyze_cli._chordino_status(media) == "stale"
    result = analyze_media(media, analyzer_cls=FakeAnalyzer)
    assert FakeAnalyzer.calls[-1] == replacement
    assert canonical_source_status(result, media) == "current"


def test_legacy_is_readable_complete_and_skipped_without_mass_reanalysis(song, capsys):
    media, fr = song
    complete().save_to_file(fr.get("json"))
    prior = Path(fr.get("json")).read_bytes()
    legacy = analyze_media(media, analyzer_cls=FakeAnalyzer)
    assert is_canonical_analysis_complete(legacy)
    assert canonical_source_status(legacy, media) == "legacy"
    assert FakeAnalyzer.calls == []
    with pytest.raises(SystemExit) as result:
        analyze_cli.main(["--dry-run", str(media)])
    assert result.value.code == 0
    assert "LEGACY" in capsys.readouterr().out
    assert Path(fr.get("json")).read_bytes() == prior


@pytest.mark.parametrize("source", [None, {}, {"sha256": "bad", "size": 8},
                                    {"sha256": "a" * 64, "size": True}])
def test_unverifiable_metadata_does_not_change_schema_or_completeness(song, source):
    media, fr = song
    data = complete()
    data.set_chord_track("chordino", data.chord_track_chords("chordino"),
                         metadata={"source_media": source})
    data.save_to_file(fr.get("json"))
    loaded = ChordData(fr.get("json"))
    assert is_canonical_analysis_complete(loaded)
    assert canonical_source_status(loaded, media) == "legacy"


@pytest.mark.parametrize("replace", [False, True])
def test_cli_reports_current_stale_and_replacement_refreshes(song, monkeypatch, capsys, replace):
    media, fr = song
    analyze_media(media, analyzer_cls=FakeAnalyzer)
    with pytest.raises(SystemExit):
        analyze_cli.main(["--dry-run", str(media)])
    assert "CURRENT" in capsys.readouterr().out
    media.write_bytes(b"source B")
    with pytest.raises(SystemExit):
        analyze_cli.main(["--dry-run", str(media)])
    assert "STALE" in capsys.readouterr().out
    monkeypatch.setattr("chordflask.canonical_analysis.analyze_media",
                        lambda path, force=False: analyze_media(path, force=force, analyzer_cls=FakeAnalyzer))
    with pytest.raises(SystemExit) as result:
        analyze_cli.main((["--replace"] if replace else []) + [str(media)])
    assert result.value.code == 0
    assert canonical_source_status(ChordData(fr.get("json")), media) == "current"


def test_source_change_during_analysis_cannot_publish_false_provenance(song):
    media, fr = song
    analyze_media(media, analyzer_cls=FakeAnalyzer)
    prior = Path(fr.get("json")).read_bytes()

    class ChangingAnalyzer(FakeAnalyzer):
        def process(self):
            super().process()
            media.write_bytes(b"changed during analysis")
    with pytest.raises(RuntimeError, match="Media changed during canonical analysis"):
        analyze_media(media, force=True, analyzer_cls=ChangingAnalyzer)
    assert Path(fr.get("json")).read_bytes() == prior
    assert not list(Path(fr.datapath).glob(".song.reanalyze-*"))
    analyze_media(media, analyzer_cls=FakeAnalyzer)
    assert canonical_source_status(ChordData(fr.get("json")), media) == "current"


def test_hash_uses_bytes_not_filename_or_mtime(song):
    media, _ = song
    identity = media_source_identity(media)
    media.touch()
    assert media_source_identity(media) == identity
    another = media.with_name("other.mp3")
    another.write_bytes(media.read_bytes())
    assert media_source_identity(another) == identity


def test_gui_load_indicates_stale_and_reanalyze_refreshes(song):
    from chordflask.app import FlaskMP4App
    from chordflask.analysis_worker import AnalysisWorker

    media, fr = song
    analyze_media(media, analyzer_cls=FakeAnalyzer)
    wrapper = FlaskMP4App()
    client = wrapper.app.test_client()
    request = {"dirname": str(media.parent), "filename": media.name}
    current = client.post("/load_file", json=request).get_json()
    assert current["analysis_source_status"] == "current"
    media.write_bytes(b"source B")
    stale = client.post("/load_file", json=request).get_json()
    assert stale["status"] == "ready" and stale["analysis_source_status"] == "stale"
    assert client.post("/reanalyze", json=request).get_json()["status"] == "queued"
    assert AnalysisWorker(queue=wrapper.analysis_queue, analyzer_cls=FakeAnalyzer).run_once()
    assert client.post("/load_file", json=request).get_json()["analysis_source_status"] == "current"
    assert canonical_source_status(ChordData(fr.get("json")), media) == "current"


def test_optional_tracks_keep_their_own_provenance_on_canonical_refresh(song):
    media, fr = song
    data = complete()
    record_canonical_source(data, media_source_identity(media))
    for track in ("btc", "chordflask_v3"):
        data.set_chord_track(track, [{"timestamp": 0., "chord": "G"}], metadata={"media_sha256": "old optional"})
    data.save_to_file(fr.get("json"))
    media.write_bytes(b"source B")
    refreshed = analyze_media(media, analyzer_cls=FakeAnalyzer)
    for track in ("btc", "chordflask_v3"):
        assert refreshed.chord_track_metadata(track) == {"media_sha256": "old optional"}
    assert canonical_source_status(refreshed, media) == "current"


def test_preservation_reread_happens_after_final_media_hash(song, monkeypatch):
    import chordflask.canonical_analysis as executor

    media, fr = song
    old = ChordData()
    old.set_chord_track("btc", [{"timestamp": 0., "chord": "G"}])
    old.save_to_file(fr.get("json"))
    calls = []
    original = executor.media_source_identity

    def hash_with_optional_update(path):
        identity = original(path)
        calls.append(path)
        if len(calls) == 2:
            current = ChordData(fr.get("json"))
            current.set_chord_track("late_optional", [{"timestamp": 0., "chord": "Am"}])
            current.save_to_file(fr.get("json"))
        return identity
    monkeypatch.setattr(executor, "media_source_identity", hash_with_optional_update)
    result = analyze_media(media, analyzer_cls=FakeAnalyzer)
    assert len(calls) == 2
    assert result.has_chord_track("late_optional")
    assert canonical_source_status(result, media) == "current"


def test_gui_batch_queues_stale_but_leaves_legacy_usable(song):
    from chordflask.app import FlaskMP4App

    media, fr = song
    complete().save_to_file(fr.get("json"))
    wrapper = FlaskMP4App()
    client = wrapper.app.test_client()
    load = {"dirname": str(media.parent), "filename": media.name}
    legacy = client.post("/load_file", json=load).get_json()
    assert legacy["status"] == "ready" and legacy["analysis_source_status"] == "legacy"
    assert wrapper.analysis_queue.status()["pending"] == []
    analyze_media(media, force=True, analyzer_cls=FakeAnalyzer)
    media.write_bytes(b"source B")
    response = client.post("/enqueue_batch", json={
        "dirname": str(media.parent), "filenames": [media.name], "limit": 1,
    })
    assert response.status_code == 200
    assert len(wrapper.analysis_queue.status()["pending"]) == 1
