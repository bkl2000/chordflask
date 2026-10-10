"""Stem Chordino producer: source checks, isolated writes, and timeline mapping."""

import hashlib
from pathlib import Path

import pytest

import chordflask.app as app_mod
import chordflask.stem_chord_analysis as stem_mod
from chordflask.stem_chord_analysis import (
    StemChordAnalysisError,
    analyze_stem_chords,
    resolve_registered_stem,
)
from chordflask_base import (
    ChordData,
    ChordTrackRepository,
    DEMUCS_STEM_NAMES,
    analysis_json_lock,
    preserve_analysis_user_data,
)

SET_ID = "demucs:htdemucs"
MEDIA_BYTES = b"media"
REL_DIR = Path(".chordflask") / "stems" / "demucs" / "htdemucs" / "song" / "gen"


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _stem_bytes(stem):
    return f"flac-{stem}".encode()


def _audio_set(media_sha=None):
    tracks = {}
    for stem in DEMUCS_STEM_NAMES:
        content = _stem_bytes(stem)
        tracks[stem] = {
            "path": str(REL_DIR / f"{stem}.flac"),
            "format": "flac",
            "sample_rate": 44100,
            "channels": 2,
            "sample_count": 44100,
            "duration": 1.0,
            "size": len(content),
            "sha256": _sha(content),
        }
    return {
        "provider": "demucs",
        "model": "htdemucs",
        "tracks": tracks,
        "metadata": {
            "source": {
                "sha256": media_sha or _sha(MEDIA_BYTES),
                "size": len(MEDIA_BYTES),
                "sample_rate": 44100,
                "channels": 2,
                "sample_count": 44100,
                "duration": 1.0,
            },
            "sync": {
                "reference": "canonical_extracted_audio",
                "start_sample": 0,
                "source_sample_count": 44100,
                "stem_sample_count": 44100,
                "max_tail_delta_samples": 2205,
                "tail_adjustment_samples": {stem: 0 for stem in DEMUCS_STEM_NAMES},
            },
            "source_timeline": {"available": False},
        },
    }


def _song(tmp_path, *, with_audio=True, canonical=True, media_sha=None):
    media = tmp_path / "song.mp3"
    media.write_bytes(MEDIA_BYTES)
    for stem in DEMUCS_STEM_NAMES:
        path = tmp_path / REL_DIR / f"{stem}.flac"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_stem_bytes(stem))
    data = ChordData()
    source = {"sha256": _sha(MEDIA_BYTES), "size": len(MEDIA_BYTES)}
    if canonical:
        data.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "C"}],
                             metadata={"source_media": source})
        data.set_rhythm_track(
            "qm_barbeattracker", bpm=120, meter_signature=4,
            beat_times=[0.0, 0.5, 1.0, 1.5, 2.0], beat_numbers=[1, 2, 3, 4, 1],
            metadata={"source_media": source},
        )
        data.create_beat_aligned_track("user_edited", metadata={"display_name": "Edited"})
    data.set_chord_track("btc", [{"timestamp": 0.0, "chord": "Dm"}])
    if with_audio:
        data.set_audio_track(SET_ID, _audio_set(media_sha))
    data.user_data = {"note": "keep"}
    data.transpose(2)
    json_path = tmp_path / ".chordflask" / "song.json"
    data.save_to_file(json_path)
    return media, json_path


class FakeAnalyzer:
    def __init__(self, chords=None, during=None):
        self.paths = []
        self.chords = chords or [{"timestamp": 1.25, "chord": "Am"}]
        self.during = during

    def analyze_chords(self, path):
        self.paths.append(path)
        if self.during is not None:
            self.during()
        return list(self.chords)


def _load(json_path):
    return ChordTrackRepository().load(json_path)


def _snapshot(data, *, skip=()):
    return {
        "chords": {tid: (data.chord_track_chords(tid), data.chord_track_metadata(tid))
                   for tid in data.available_chord_track_ids if tid not in skip},
        "rhythms": {tid: data.rhythm_track_data(tid) for tid in data.available_rhythm_track_ids},
        "audio": {sid: data.audio_track_data(sid) for sid in data.available_audio_track_ids},
        "user_data": data.user_data,
        "transpose": data.transpose_semitones,
    }


def test_writes_only_the_stem_track_and_preserves_everything_else(tmp_path):
    media, json_path = _song(tmp_path)
    before = _snapshot(_load(json_path))
    analyzer = FakeAnalyzer()

    result = analyze_stem_chords(media, "other", analyzer=analyzer)

    assert result == {"track_id": "chordino_stem_other", "chords": 1}
    assert analyzer.paths == [str((tmp_path / REL_DIR / "other.flac").resolve())]
    saved = _load(json_path)
    assert saved.chord_track_chords("chordino_stem_other") == [{"timestamp": 1.25, "chord": "Am"}]
    metadata = saved.chord_track_metadata("chordino_stem_other")
    assert metadata["audio_source"]["stem_sha256"] == _sha(_stem_bytes("other"))
    assert metadata["audio_source"]["set_source_sha256"] == _sha(MEDIA_BYTES)
    assert metadata["source_media"] == {"sha256": _sha(MEDIA_BYTES), "size": len(MEDIA_BYTES)}
    assert metadata["timeline"] == {"reference": "original", "offset_seconds": 0.0}
    assert _snapshot(saved, skip={"chordino_stem_other"}) == before
    assert media.read_bytes() == MEDIA_BYTES


def test_rerun_replaces_only_that_track(tmp_path):
    media, json_path = _song(tmp_path)
    analyze_stem_chords(media, "other", analyzer=FakeAnalyzer())
    analyze_stem_chords(media, "bass", analyzer=FakeAnalyzer([{"timestamp": 0.0, "chord": "E"}]))

    analyze_stem_chords(media, "other", analyzer=FakeAnalyzer([{"timestamp": 0.5, "chord": "G"}]))

    saved = _load(json_path)
    assert saved.chord_track_chords("chordino_stem_other") == [{"timestamp": 0.5, "chord": "G"}]
    assert saved.chord_track_chords("chordino_stem_bass") == [{"timestamp": 0.0, "chord": "E"}]


def _make_symlink(tmp_path):
    target = tmp_path / REL_DIR / "other.flac"
    outside = tmp_path / "outside.flac"
    outside.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(outside)


def _point_outside_root(tmp_path, json_path):
    data = _load(json_path)
    audio = data.audio_track_data(SET_ID)
    (tmp_path / "escape.flac").write_bytes(_stem_bytes("other"))
    audio["tracks"]["other"]["path"] = "escape.flac"
    data.set_audio_track(SET_ID, audio)
    data.save_to_file(json_path)


@pytest.mark.parametrize("case", ["unknown", "unsafe", "no_set", "symlink", "outside", "missing"])
def test_rejects_invalid_stem_sources(tmp_path, case):
    media, json_path = _song(tmp_path, with_audio=case != "no_set")
    stem = {"unknown": "guitar", "unsafe": "../other"}.get(case, "other")
    if case == "symlink":
        _make_symlink(tmp_path)
    elif case == "outside":
        _point_outside_root(tmp_path, json_path)
    elif case == "missing":
        (tmp_path / REL_DIR / "other.flac").unlink()
    before = json_path.read_bytes()
    analyzer = FakeAnalyzer()

    with pytest.raises(StemChordAnalysisError):
        analyze_stem_chords(media, stem, analyzer=analyzer)

    assert analyzer.paths == []
    assert json_path.read_bytes() == before


def test_resolve_registered_stem_returns_file_entry_and_set(tmp_path):
    media, json_path = _song(tmp_path)
    path, entry, set_data = resolve_registered_stem(media, _load(json_path), "vocals")
    assert path == (tmp_path / REL_DIR / "vocals.flac").resolve()
    assert entry["sha256"] == _sha(_stem_bytes("vocals"))
    assert set_data["provider"] == "demucs"


def test_rejects_stem_hash_mismatch(tmp_path):
    media, _ = _song(tmp_path)
    (tmp_path / REL_DIR / "other.flac").write_bytes(b"flac-regenerated")
    with pytest.raises(StemChordAnalysisError, match="stale"):
        analyze_stem_chords(media, "other", analyzer=FakeAnalyzer())


def test_rejects_when_media_differs_from_stem_source(tmp_path):
    media, _ = _song(tmp_path, media_sha="e" * 64)
    with pytest.raises(StemChordAnalysisError, match="stale"):
        analyze_stem_chords(media, "other", analyzer=FakeAnalyzer())


def test_requires_canonical_analysis(tmp_path):
    media, _ = _song(tmp_path, canonical=False)
    with pytest.raises(StemChordAnalysisError, match="Chordino"):
        analyze_stem_chords(media, "other", analyzer=FakeAnalyzer())


def test_requires_existing_analysis(tmp_path):
    media = tmp_path / "song.mp3"
    media.write_bytes(MEDIA_BYTES)
    with pytest.raises(StemChordAnalysisError, match="analysis"):
        analyze_stem_chords(media, "other", analyzer=FakeAnalyzer())


def test_aborts_when_stem_set_changes_during_analysis(tmp_path):
    media, json_path = _song(tmp_path)

    def regenerate_stems():
        with analysis_json_lock(json_path):
            data = _load(json_path)
            audio = data.audio_track_data(SET_ID)
            audio["tracks"]["other"]["sha256"] = "f" * 64
            data.set_audio_track(SET_ID, audio)
            data.save_to_file(json_path)

    with pytest.raises(StemChordAnalysisError, match="changed"):
        analyze_stem_chords(media, "other", analyzer=FakeAnalyzer(during=regenerate_stems))

    saved = _load(json_path)
    assert not saved.has_chord_track("chordino_stem_other")
    assert saved.audio_track_data(SET_ID)["tracks"]["other"]["sha256"] == "f" * 64


def test_canonical_reanalysis_preserves_stem_tracks(tmp_path):
    media, json_path = _song(tmp_path)
    analyze_stem_chords(media, "other", analyzer=FakeAnalyzer())
    current = _load(json_path)
    replacement = ChordData()
    replacement.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "D"}])
    replacement.set_rhythm_track("qm_barbeattracker", bpm=120, meter_signature=4,
                                 beat_times=[0.0, 0.5], beat_numbers=[1, 2])

    preserve_analysis_user_data(current, replacement)

    assert replacement.chord_track_chords("chordino_stem_other") == [{"timestamp": 1.25, "chord": "Am"}]
    assert replacement.chord_track_metadata("chordino_stem_other") == \
        current.chord_track_metadata("chordino_stem_other")


def test_stem_track_renders_on_original_grid(tmp_path):
    media, json_path = _song(tmp_path)
    analyze_stem_chords(media, "other", analyzer=FakeAnalyzer())
    data = _load(json_path)
    data.transpose(0)

    data.select_chord_track("chordino_stem_other")
    data.select_rhythm_track("qm_barbeattracker")

    # Lookup midpoints 0.25, 0.75, 1.25, 1.75, 2.25; the first two precede the 1.25 s chord.
    assert [label for _, label in data.get_chords_per_beat()] == ["N", "N", "Am", "Am", "Am"]


def test_cli_analyze_stem_reports_errors(tmp_path, capsys):
    media, _ = _song(tmp_path, with_audio=False)
    assert stem_mod.cli_analyze_stem("other", str(media)) == 1
    assert "ERROR:" in capsys.readouterr().err


def test_cli_flag_dispatches_without_starting_web_app(monkeypatch):
    calls = []
    monkeypatch.setattr(stem_mod, "cli_analyze_stem", lambda stem, media: calls.append((stem, media)) or 0)

    def no_web_app(*args, **kwargs):
        raise AssertionError("--analyze-stem must not construct the web application")

    monkeypatch.setattr(app_mod, "FlaskMP4App", no_web_app)

    with pytest.raises(SystemExit) as raised:
        app_mod.main(["--analyze-stem", "other", "x.mp3"])

    assert raised.value.code == 0
    assert calls == [("other", "x.mp3")]
