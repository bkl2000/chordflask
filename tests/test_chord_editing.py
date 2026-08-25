import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
FLASK_DIR = REPO_ROOT / "flask"

if str(FLASK_DIR) not in sys.path:
    sys.path.insert(0, str(FLASK_DIR))

import chordutils
from analysis_queue import AnalysisQueue
from analysis_worker import AnalysisWorker
from chordflask_base import (
    USER_EDITED_RHYTHM_TRACK_ID,
    ChordData,
    ChordTrackRepository,
)
from chordflask import CLIENT_COOKIE, FlaskMP4App
from filerepr import FileRepr
from mp4playerflask import MP4PlayerFlask

from chordflask_config import ANALYSIS_DIR_NAME


@pytest.fixture(autouse=True)
def isolate_default_analysis_queue(monkeypatch, tmp_path):
    monkeypatch.setenv("CHORDFLASK_QUEUE_DIR", str(tmp_path / "default-queue"))


# ── pure label / compression helpers ─────────────────────────────────


def test_validate_chord_label_accepts_ascii_accidentals_and_qualities():
    for label in ("C", "Am7", "Bb", "F#m7b5", "Cmaj7", "E/G", "G#sus4",
                  "Ddim", "Aaug", "F7", "G7#9", "C#m7/G#",
                  "Cmmaj7", "F#mmaj7", "Bbmmaj7"):
        assert chordutils.validate_chord_label(label) == label


def test_validate_chord_label_accepts_unicode_accidentals():
    assert chordutils.validate_chord_label("C\u266fm") == "C#m"
    assert chordutils.validate_chord_label("B\u266dmaj7") == "Bbmaj7"


def test_validate_chord_label_accepts_displayed_quality_symbols():
    assert chordutils.validate_chord_label("C+") == "Caug"
    assert chordutils.validate_chord_label("D\u00b0") == "Ddim"
    assert chordutils.validate_chord_label("E\u00b07") == "Edim7"
    assert chordutils.validate_chord_label("F\u00f87") == "Fm7b5"


def test_validate_chord_label_accepts_n_and_x_case_insensitive():
    assert chordutils.validate_chord_label("N") == "N"
    assert chordutils.validate_chord_label("n") == "N"
    assert chordutils.validate_chord_label("X") == "X"
    assert chordutils.validate_chord_label("x") == "X"


@pytest.mark.parametrize("label", ["", "  ", "H", "C##", "Cmaj13", "C/",
                                   "C/D#E", "C7sus", "N/C", "7", "m"])
def test_validate_chord_label_rejects_invalid_without_turning_into_n(label):
    with pytest.raises(ValueError):
        chordutils.validate_chord_label(label)


def test_validate_chord_label_rejects_non_string():
    with pytest.raises(ValueError):
        chordutils.validate_chord_label(7)


def test_rle_and_expand_roundtrip():
    compressed = chordutils.rle_chord_labels([
        (0.0, "C"), (0.5, "C"), (1.0, "G"), (1.5, "G"), (2.0, "G"),
    ])
    assert compressed == [
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 1.0, "chord": "G"},
    ]
    assert chordutils.expand_chord_labels(compressed, [0.0, 0.5, 1.0, 1.5, 2.0]) == [
        "C", "C", "G", "G", "G",
    ]


# ── ChordData operations ─────────────────────────────────────────────


def _editable_data():
    cd = ChordData()
    cd.set_chord_track("chordino", [
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 1.0, "chord": "G"},
        {"timestamp": 2.0, "chord": "Am"},
    ])
    cd.set_rhythm_track(
        "qm_barbeattracker", bpm=120, meter_signature=4,
        beat_times=[0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
        beat_numbers=[1, 2, 3, 4, 1, 2, 3, 4],
    )
    return cd


def test_create_beat_aligned_track_samples_and_compresses():
    cd = _editable_data()
    cd.create_beat_aligned_track("user_edited", metadata={"display_name": "Edited"})

    assert cd.chord_track_chords("user_edited") == [
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 1.0, "chord": "G"},
        {"timestamp": 2.0, "chord": "Am"},
    ]


def test_create_beat_aligned_track_records_sources_and_keeps_chordino():
    cd = _editable_data()
    before = cd.chord_track_chords("chordino")
    cd.create_beat_aligned_track("user_edited")

    assert cd.chord_track_metadata("user_edited")["sources"] == {
        "chord": "chordino",
        "rhythm": "qm_barbeattracker",
    }
    assert cd.chord_track_chords("chordino") == before


def test_edit_chord_track_beat_changes_one_beat_and_recompresses():
    cd = _editable_data()
    cd.create_beat_aligned_track("user_edited")

    cd.edit_chord_track_beat("user_edited", 1, "F")

    assert cd.chord_track_chords("user_edited") == [
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 0.5, "chord": "F"},
        {"timestamp": 1.0, "chord": "G"},
        {"timestamp": 2.0, "chord": "Am"},
    ]
    assert cd.chord_track_chords("chordino")[0]["chord"] == "C"


def test_edit_chord_track_beat_rejects_out_of_range_beat():
    cd = _editable_data()
    cd.create_beat_aligned_track("user_edited")

    with pytest.raises(ValueError, match="out of range"):
        cd.edit_chord_track_beat("user_edited", 8, "C")
    with pytest.raises(ValueError, match="out of range"):
        cd.edit_chord_track_beat("user_edited", -1, "C")
    with pytest.raises(ValueError, match="must be an integer"):
        cd.edit_chord_track_beat("user_edited", "0", "C")


def test_edit_chord_track_beat_rejects_invalid_label():
    cd = _editable_data()
    cd.create_beat_aligned_track("user_edited")

    with pytest.raises(ValueError, match="invalid chord label"):
        cd.edit_chord_track_beat("user_edited", 0, "H7")


def test_remove_chord_track_restores_default_view():
    cd = _editable_data()
    cd.create_beat_aligned_track("user_edited")
    cd.select_chord_track("user_edited")

    cd.remove_chord_track("user_edited")

    assert not cd.has_chord_track("user_edited")
    assert cd.active_chord_track_id == "chordino"


def test_remove_missing_chord_track_raises():
    cd = _editable_data()
    with pytest.raises(ValueError, match="not available"):
        cd.remove_chord_track("user_edited")


def test_edited_track_roundtrip_persists(tmp_path):
    cd = _editable_data()
    cd.create_beat_aligned_track("user_edited")
    cd.select_chord_track("user_edited")
    path = str(tmp_path / "out.json")

    ChordTrackRepository().save(cd, path)
    loaded = ChordTrackRepository().load(path)

    assert loaded.has_chord_track("user_edited")
    assert loaded.chord_track_chords("user_edited") == cd.chord_track_chords("user_edited")
    assert loaded.chord_track_metadata("user_edited")["sources"] == {
        "chord": "chordino",
        "rhythm": "qm_barbeattracker",
    }
    assert loaded.chord_track_chords("chordino") == cd.chord_track_chords("chordino")


# ── MP4PlayerFlask editing operations ────────────────────────────────


def _make_player(tmp_path, semitones=0, metric_chords=False, with_madmom=False):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    file_repr = FileRepr(str(media), datapath=str(tmp_path / ".chordflask"), create=True)
    data = _editable_data()
    if with_madmom:
        data.set_rhythm_track(
            "madmom", bpm=120, meter_signature=4,
            beat_times=[0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
            beat_numbers=[1, 2, 3, 4, 1, 2, 3, 4],
        )
    data.save_to_file(file_repr.get("json"))
    player = MP4PlayerFlask(file_repr, semitones=semitones, metric_chords=metric_chords)
    player.set_prefer_flats(True)
    player.set_repeat_mode("changes")
    return media, file_repr, player


def test_player_start_editing_creates_and_selects_edited(tmp_path):
    _, _, player = _make_player(tmp_path)

    assert player.has_edited_chords() is False

    state = player.start_chord_editing()

    assert state["has_edited"] is True
    assert state["active_chord_version"] == "edited"
    assert state["active_chord_track_id"] == "user_edited"
    assert any(
        t["id"] == "user_edited" and t["display_name"] == "Own modification"
        for t in state["available_chord_tracks"]
    )


def test_player_edited_shown_as_own_modification(tmp_path):
    _, _, player = _make_player(tmp_path)
    player.start_chord_editing()

    state = player.analysis_track_state()

    tracks = {t["id"]: t["display_name"] for t in state["available_chord_tracks"]}
    assert tracks["chordino"] == "Chordino"
    assert tracks["user_edited"] == "Own modification"


def test_player_set_chord_version_toggles(tmp_path):
    _, _, player = _make_player(tmp_path)
    player.start_chord_editing()

    player.set_chord_version("original")
    assert player.active_chord_version() == "original"
    assert player.chord_data.active_chord_track_id == "chordino"

    player.set_chord_version("edited")
    assert player.active_chord_version() == "edited"


def test_player_set_chord_version_rejects_unknown(tmp_path):
    _, _, player = _make_player(tmp_path)
    with pytest.raises(ValueError, match="version must be"):
        player.set_chord_version("sideways")


def test_player_set_edited_version_requires_edited(tmp_path):
    _, _, player = _make_player(tmp_path)
    with pytest.raises(ValueError, match="No edited"):
        player.set_chord_version("edited")


def test_player_reset_removes_edited_and_selects_original(tmp_path):
    _, _, player = _make_player(tmp_path)
    player.start_chord_editing()

    player.reset_edited_chords()

    assert player.has_edited_chords() is False
    assert player.active_chord_version() == "original"


def test_player_reset_removes_edited_rhythm_snapshot(tmp_path):
    _, _, player = _make_player(tmp_path)
    rhythm = player.chord_data.rhythm_track_data("qm_barbeattracker")
    player.chord_data.set_rhythm_track(USER_EDITED_RHYTHM_TRACK_ID, **rhythm)
    player.chord_data.create_beat_aligned_track(
        "user_edited",
        source_rhythm_track_id=USER_EDITED_RHYTHM_TRACK_ID,
    )
    player.select_analysis_tracks(chord_track_id="user_edited")

    player.reset_edited_chords()

    assert not player.chord_data.has_chord_track("user_edited")
    assert not player.chord_data.has_rhythm_track(USER_EDITED_RHYTHM_TRACK_ID)
    assert player.chord_data.active_rhythm_track_id == "qm_barbeattracker"


def test_player_edit_reverse_transposes_input(tmp_path):
    _, _, player = _make_player(tmp_path, semitones=2)
    player.start_chord_editing()

    player.edit_chord(0, "D")  # displayed D = canonical C transposed +2

    stored = player.chord_data.chord_track_chords("user_edited")
    assert any(entry["chord"] == "C" for entry in stored)


def test_player_edit_rejects_invalid_label(tmp_path):
    _, _, player = _make_player(tmp_path)

    with pytest.raises(ValueError):
        player.edit_chord(0, "H7")

    assert player.has_edited_chords() is False
    assert player.chord_data.active_chord_track_id == "chordino"


def test_player_edit_rejects_invalid_beat_without_creating_edited(tmp_path):
    _, _, player = _make_player(tmp_path)

    with pytest.raises(ValueError, match="out of range"):
        player.edit_chord(99, "F")

    assert player.has_edited_chords() is False
    assert player.chord_data.active_chord_track_id == "chordino"


def test_player_edit_grid_structure(tmp_path):
    _, _, player = _make_player(tmp_path)
    player.start_chord_editing()

    grid = player.edit_grid(0.0)

    assert grid["beat_count"] == 8
    assert grid["beats_per_row"] == 8
    assert grid["active_beat_index"] == 0
    assert len(grid["rows"]) == 16

    flat = [cell for row in grid["rows"] for cell in row]
    real = {cell["beat_index"]: cell for cell in flat if cell["chord"]}
    assert set(real) == set(range(8))
    assert real[0]["chord"] == "C"
    assert real[0]["active"] is True
    assert real[1]["repeat"] is True
    assert real[2]["repeat"] is False
    assert real[2]["chord"] == "G"


def test_player_edit_grid_identical_with_and_without_metric_mode(tmp_path):
    _, _, plain = _make_player(tmp_path, metric_chords=False)
    _, _, metric = _make_player(tmp_path, metric_chords=True)
    plain.start_chord_editing()
    metric.start_chord_editing()

    assert plain.edit_grid(0.5) == metric.edit_grid(0.5)


def test_player_start_editing_selects_qm_rhythm(tmp_path):
    _, _, player = _make_player(tmp_path, with_madmom=True)
    player.select_rhythm_track("madmom")
    assert player.chord_data.active_rhythm_track_id == "madmom"

    player.start_chord_editing()

    assert player.chord_data.active_rhythm_track_id == "qm_barbeattracker"


def test_player_selecting_edited_forces_qm_rhythm(tmp_path):
    _, _, player = _make_player(tmp_path, with_madmom=True)
    player.select_rhythm_track("madmom")
    player.start_chord_editing()

    assert player.chord_data.active_chord_track_id == "user_edited"
    assert player.chord_data.active_rhythm_track_id == "qm_barbeattracker"


def test_player_rejects_rhythm_switch_while_edited_active(tmp_path):
    _, _, player = _make_player(tmp_path, with_madmom=True)
    player.start_chord_editing()

    with pytest.raises(ValueError, match="Rhythm source is fixed"):
        player.select_analysis_tracks(rhythm_track_id="madmom")


def test_player_set_original_allows_other_rhythm(tmp_path):
    _, _, player = _make_player(tmp_path, with_madmom=True)
    player.start_chord_editing()

    player.set_chord_version("original")
    player.select_analysis_tracks(rhythm_track_id="madmom")

    assert player.chord_data.active_chord_track_id == "chordino"
    assert player.chord_data.active_rhythm_track_id == "madmom"


def test_player_reset_selects_chordino_when_other_producer_active(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    file_repr = FileRepr(str(media), datapath=str(tmp_path / ".chordflask"), create=True)
    data = _editable_data()
    data.set_chord_track("pytorch", [{"timestamp": 0.0, "chord": "C"}])
    data.save_to_file(file_repr.get("json"))
    player = MP4PlayerFlask(file_repr)
    player.set_prefer_flats(True)
    player.set_repeat_mode("changes")

    player.start_chord_editing()
    player.select_chord_track("pytorch")
    assert player.chord_data.active_chord_track_id == "pytorch"

    player.reset_edited_chords()

    assert player.has_edited_chords() is False
    assert player.chord_data.active_chord_track_id == "chordino"


def test_player_start_editing_rejects_qm_without_beat_times(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    file_repr = FileRepr(str(media), datapath=str(tmp_path / ".chordflask"), create=True)
    cd = ChordData()
    cd.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "C"}])
    cd.set_rhythm_track(
        "qm_barbeattracker", bpm=120, meter_signature=4,
        beat_times=[], beat_numbers=[],
    )
    cd.save_to_file(file_repr.get("json"))
    player = MP4PlayerFlask(file_repr)

    with pytest.raises(ValueError, match="no beat times"):
        player.start_chord_editing()


# ── worker discard semantics ─────────────────────────────────────────


def _save_analysis(file_repr, *, chord="C", bpm=120, edited=False):
    track = ChordData()
    track.set_chord_track("chordino", [{"timestamp": 0.0, "chord": chord}])
    track.set_rhythm_track("qm_barbeattracker", bpm=bpm, beat_times=[0.0])
    if edited:
        track.create_beat_aligned_track("user_edited")
        track.select_chord_track("user_edited")
    track.save_to_file(file_repr.get("json"))


def _edited_worker_setup(tmp_path, *, discard_edits):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    analysis_dir = tmp_path / ANALYSIS_DIR_NAME
    analysis_dir.mkdir()
    current_repr = FileRepr(str(media), datapath=str(analysis_dir))
    _save_analysis(current_repr, edited=True)

    class FreshAnalyzer:
        def __init__(self, media_path, output_dir):
            self.file_repr = FileRepr(media_path, datapath=output_dir)

        def process(self):
            _save_analysis(self.file_repr, chord="G", bpm=130)

    worker = AnalysisWorker(queue=AnalysisQueue(tmp_path / "queue"), analyzer_cls=FreshAnalyzer)
    worker._analyze(str(media), force=True, discard_edits=discard_edits)
    return current_repr


def test_forced_reanalysis_preserves_user_edited_by_default(tmp_path):
    current_repr = _edited_worker_setup(tmp_path, discard_edits=False)

    loaded = ChordData(current_repr.get("json"))
    assert loaded.has_chord_track("user_edited") is True
    assert loaded.chord_track_chords("chordino") == [{"timestamp": 0.0, "chord": "G"}]


@pytest.mark.parametrize(
    "new_beat_times,new_beat_numbers",
    [
        ([0.0, 0.55, 1.1, 1.65], [1, 2, 3, 1]),
        ([0.0, 0.75], [1, 2]),
    ],
    ids=("timestamps-change", "beat-count-changes"),
)
def test_reanalysis_preserves_edited_chords_with_their_original_rhythm_grid(
    tmp_path, new_beat_times, new_beat_numbers
):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    analysis_dir = tmp_path / ANALYSIS_DIR_NAME
    analysis_dir.mkdir()
    current_repr = FileRepr(str(media), datapath=str(analysis_dir))

    current = ChordData()
    current.set_chord_track(
        "chordino",
        [
            {"timestamp": 0.0, "chord": "C"},
            {"timestamp": 1.0, "chord": "G"},
        ],
    )
    old_rhythm = {
        "bpm": 120,
        "meter_signature": 4,
        "beat_times": [0.0, 0.5, 1.0, 1.5],
        "beat_numbers": [1, 2, 3, 4],
        "metadata": {"engine": "old-qm"},
    }
    current.set_rhythm_track("qm_barbeattracker", **old_rhythm)
    current.create_beat_aligned_track("user_edited")
    current.edit_chord_track_beat("user_edited", 1, "F")
    current.edit_chord_track_beat("user_edited", 3, "Am")
    edited_before = current.chord_track_chords("user_edited")
    current.save_to_file(current_repr.get("json"))

    class FreshAnalyzer:
        def __init__(self, media_path, output_dir):
            self.file_repr = FileRepr(media_path, datapath=output_dir)

        def process(self):
            replacement = ChordData()
            replacement.set_chord_track(
                "chordino", [{"timestamp": 0.0, "chord": "D"}]
            )
            replacement.set_rhythm_track(
                "qm_barbeattracker",
                bpm=100,
                meter_signature=3,
                beat_times=new_beat_times,
                beat_numbers=new_beat_numbers,
                metadata={"engine": "new-qm"},
            )
            replacement.save_to_file(self.file_repr.get("json"))

    worker = AnalysisWorker(
        queue=AnalysisQueue(tmp_path / "queue"), analyzer_cls=FreshAnalyzer
    )
    worker._analyze(str(media), force=True)

    loaded = ChordData(current_repr.get("json"))
    assert loaded.chord_track_chords("user_edited") == edited_before
    assert loaded.chord_track_chords("chordino") == [
        {"timestamp": 0.0, "chord": "D"}
    ]
    assert loaded.rhythm_track_data("qm_barbeattracker")["beat_times"] == new_beat_times
    snapshot = loaded.rhythm_track_data(USER_EDITED_RHYTHM_TRACK_ID)
    assert snapshot["beat_times"] == old_rhythm["beat_times"]
    assert snapshot["beat_numbers"] == old_rhythm["beat_numbers"]
    assert snapshot["meter_signature"] == old_rhythm["meter_signature"]
    assert loaded.chord_track_metadata("user_edited")["sources"]["rhythm"] == (
        USER_EDITED_RHYTHM_TRACK_ID
    )

    player = MP4PlayerFlask(current_repr)
    player.set_chord_version("edited")
    assert player.chord_data.active_rhythm_track_id == USER_EDITED_RHYTHM_TRACK_ID
    assert player.playback_view.full_beat_view() == ["C", "F", "G", "Am"]


def test_reanalysis_fails_safely_when_edited_rhythm_dependency_is_invalid(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    analysis_dir = tmp_path / ANALYSIS_DIR_NAME
    analysis_dir.mkdir()
    current_repr = FileRepr(str(media), datapath=str(analysis_dir))
    current = _editable_data()
    current.set_chord_track(
        "user_edited",
        [{"timestamp": 0.0, "chord": "F"}],
        metadata={"display_name": "Edited"},
    )
    current.save_to_file(current_repr.get("json"))
    original = Path(current_repr.get("json")).read_bytes()

    class FreshAnalyzer:
        def __init__(self, media_path, output_dir):
            self.file_repr = FileRepr(media_path, datapath=output_dir)

        def process(self):
            _save_analysis(self.file_repr, chord="G", bpm=130)

    worker = AnalysisWorker(
        queue=AnalysisQueue(tmp_path / "queue"), analyzer_cls=FreshAnalyzer
    )
    with pytest.raises(RuntimeError, match="Cannot safely preserve Edited chords"):
        worker._analyze(str(media), force=True)

    assert Path(current_repr.get("json")).read_bytes() == original
    assert ChordData(current_repr.get("json")).has_chord_track("user_edited")


def test_forced_reanalysis_drops_user_edited_when_discard_authorized(tmp_path):
    current_repr = _edited_worker_setup(tmp_path, discard_edits=True)

    loaded = ChordData(current_repr.get("json"))
    assert loaded.has_chord_track("user_edited") is False
    assert loaded.active_chord_track_id == "chordino"
    assert loaded.chord_track_chords("chordino") == [{"timestamp": 0.0, "chord": "G"}]


def test_explicit_discard_removes_edited_rhythm_snapshot(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    analysis_dir = tmp_path / ANALYSIS_DIR_NAME
    analysis_dir.mkdir()
    current_repr = FileRepr(str(media), datapath=str(analysis_dir))
    current = _editable_data()
    current.set_rhythm_track(
        USER_EDITED_RHYTHM_TRACK_ID,
        **current.rhythm_track_data("qm_barbeattracker"),
    )
    current.create_beat_aligned_track(
        "user_edited",
        source_rhythm_track_id=USER_EDITED_RHYTHM_TRACK_ID,
    )
    current.save_to_file(current_repr.get("json"))

    class FreshAnalyzer:
        def __init__(self, media_path, output_dir):
            self.file_repr = FileRepr(media_path, datapath=output_dir)

        def process(self):
            _save_analysis(self.file_repr, chord="G", bpm=130)

    worker = AnalysisWorker(
        queue=AnalysisQueue(tmp_path / "queue"), analyzer_cls=FreshAnalyzer
    )
    worker._analyze(str(media), force=True, discard_edits=True)

    loaded = ChordData(current_repr.get("json"))
    assert not loaded.has_chord_track("user_edited")
    assert not loaded.has_rhythm_track(USER_EDITED_RHYTHM_TRACK_ID)


def test_failed_discard_reanalysis_preserves_edited_json(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    analysis_dir = tmp_path / ANALYSIS_DIR_NAME
    analysis_dir.mkdir()
    current_repr = FileRepr(str(media), datapath=str(analysis_dir))
    _save_analysis(current_repr, edited=True)
    original = Path(current_repr.get("json")).read_bytes()

    class InvalidAnalyzer:
        def __init__(self, media_path, output_dir):
            self.file_repr = FileRepr(media_path, datapath=output_dir)

        def process(self):
            Path(self.file_repr.get("json")).write_text(
                '{"schema_version": 3, "chord_tracks": []}', encoding="utf-8"
            )

    worker = AnalysisWorker(queue=AnalysisQueue(tmp_path / "queue"), analyzer_cls=InvalidAnalyzer)

    with pytest.raises(RuntimeError):
        worker._analyze(str(media), force=True, discard_edits=True)

    assert Path(current_repr.get("json")).read_bytes() == original
    assert ChordData(current_repr.get("json")).has_chord_track("user_edited")


# ── queue discard_edits flag ─────────────────────────────────────────


def test_enqueue_records_discard_edits(tmp_path):
    queue = AnalysisQueue(tmp_path / "queue")
    media = tmp_path / "song.mp4"
    media.write_bytes(b"x")

    queue.enqueue(media, force=True, discard_edits=True)

    assert queue.status()["pending"][0]["discard_edits"] is True


def test_enqueue_rejects_non_bool_discard_edits(tmp_path):
    queue = AnalysisQueue(tmp_path / "queue")
    media = tmp_path / "song.mp4"
    media.write_bytes(b"x")

    with pytest.raises(TypeError):
        queue.enqueue(media, discard_edits="yes")


def test_migrate_items_defaults_discard_edits(tmp_path):
    queue = AnalysisQueue(tmp_path / "queue")
    queue_file = queue.queue_file
    queue.queue_dir.mkdir(parents=True, exist_ok=True)
    queue_file.write_text(json.dumps({
        "pending": [{"path": "/tmp/x.mp4", "status": "pending"}],
        "failed": [],
    }), encoding="utf-8")

    data = queue._load()

    assert data["pending"][0]["discard_edits"] is False


def test_enqueue_does_not_add_discard_edits_to_processing_item(tmp_path):
    queue = AnalysisQueue(tmp_path / "queue")
    media = tmp_path / "song.mp4"
    media.write_bytes(b"x")

    queue.enqueue(media)
    queue.peek()

    result = queue.enqueue(media, force=True, discard_edits=True)

    assert result == "already_queued"
    pending = queue.status()["pending"]
    assert len(pending) == 1
    assert pending[0]["status"] == "processing"
    assert pending[0]["discard_edits"] is False


def test_enqueue_sets_discard_edits_on_pending_item(tmp_path):
    queue = AnalysisQueue(tmp_path / "queue")
    media = tmp_path / "song.mp4"
    media.write_bytes(b"x")

    queue.enqueue(media)
    result = queue.enqueue(media, discard_edits=True)

    assert result == "already_queued"
    pending = queue.status()["pending"]
    assert pending[0]["status"] == "pending"
    assert pending[0]["discard_edits"] is True


# ── Flask routes ─────────────────────────────────────────────────────


TEST_CLIENT_ID = "test-client"


def _state(app_wrapper):
    return app_wrapper.clients.get_or_create(TEST_CLIENT_ID)


def make_client():
    app_wrapper = FlaskMP4App()
    client = app_wrapper.app.test_client()
    app_wrapper.clients.get_or_create(TEST_CLIENT_ID)
    client.set_cookie(CLIENT_COOKIE, TEST_CLIENT_ID)
    return app_wrapper, client


def _activate_editable(app_wrapper, tmp_path, name="song.mp4"):
    media = tmp_path / name
    media.write_bytes(b"media")
    file_repr = FileRepr(str(media), datapath=str(tmp_path / ".chordflask"), create=True)
    _editable_data().save_to_file(file_repr.get("json"))
    _state(app_wrapper).file_repr = file_repr
    _state(app_wrapper).player = MP4PlayerFlask(file_repr)
    _state(app_wrapper).player.set_prefer_flats(True)
    _state(app_wrapper).player.set_repeat_mode("changes")
    return media


def _payload(tmp_path, name="song.mp4", **extra):
    payload = {"dirname": str(tmp_path), "filename": name}
    payload.update(extra)
    return payload


def test_start_chord_editing_route_success(tmp_path):
    app_wrapper, client = make_client()
    _activate_editable(app_wrapper, tmp_path)

    response = client.post("/start_chord_editing", json=_payload(tmp_path))

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["has_edited"] is True
    assert payload["active_chord_version"] == "edited"
    assert payload["grid"]["beat_count"] == 8
    assert ChordData(_state(app_wrapper).file_repr.get("json")).has_chord_track("user_edited")


def test_start_chord_editing_requires_active_media(tmp_path):
    app_wrapper, client = make_client()
    _activate_editable(app_wrapper, tmp_path)
    (tmp_path / "other.mp4").write_bytes(b"x")

    response = client.post("/start_chord_editing", json=_payload(tmp_path, "other.mp4"))

    assert response.status_code == 409
    assert "not the active file" in response.get_json()["error"]


def _write_v3_json(path, chord_tracks, rhythm_tracks):
    data = {
        "schema_version": 3,
        "prefer_flats": True,
        "transpose": 0,
        "user_data": {},
        "chord_tracks": chord_tracks,
        "rhythm_tracks": rhythm_tracks,
    }
    Path(path).write_text(json.dumps(data), encoding="utf-8")


def _activate_manual_analysis(app_wrapper, tmp_path, name="song.mp4",
                              chord_tracks=None, rhythm_tracks=None):
    media = tmp_path / name
    media.write_bytes(b"media")
    file_repr = FileRepr(str(media), datapath=str(tmp_path / ".chordflask"), create=True)
    _write_v3_json(file_repr.get("json"), chord_tracks, rhythm_tracks)
    _state(app_wrapper).file_repr = file_repr
    _state(app_wrapper).player = MP4PlayerFlask(file_repr)
    _state(app_wrapper).player.set_prefer_flats(True)
    _state(app_wrapper).player.set_repeat_mode("changes")
    return media


def test_start_chord_editing_requires_chordino(tmp_path):
    app_wrapper, client = make_client()
    _activate_manual_analysis(
        app_wrapper, tmp_path,
        chord_tracks={"pytorch": {"chords": [{"timestamp": 0.0, "chord": "C"}], "metadata": {}}},
        rhythm_tracks={"qm_barbeattracker": {
            "bpm": 120, "meter_signature": 4,
            "beat_times": [0.0], "beat_numbers": [1], "metadata": {},
        }},
    )

    response = client.post("/start_chord_editing", json=_payload(tmp_path))

    assert response.status_code == 400
    assert "Chordino analysis" in response.get_json()["error"]


def test_start_chord_editing_requires_rhythm_track(tmp_path):
    app_wrapper, client = make_client()
    _activate_manual_analysis(
        app_wrapper, tmp_path,
        chord_tracks={"chordino": {"chords": [{"timestamp": 0.0, "chord": "C"}], "metadata": {}}},
        rhythm_tracks={},
    )

    response = client.post("/start_chord_editing", json=_payload(tmp_path))

    assert response.status_code == 400
    assert "QM beat track" in response.get_json()["error"]


def test_edit_route_rejects_queued_media(tmp_path):
    app_wrapper, client = make_client()
    media = _activate_editable(app_wrapper, tmp_path)
    app_wrapper.analysis_queue.enqueue(str(media))

    response = client.post("/edit_chord", json=_payload(
        tmp_path, beat_index=0, chord="F"
    ))

    assert response.status_code == 409
    assert "queued analysis work" in response.get_json()["error"]


def test_edit_route_rejects_invalid_beat_and_chord(tmp_path):
    app_wrapper, client = make_client()
    _activate_editable(app_wrapper, tmp_path)
    client.post("/start_chord_editing", json=_payload(tmp_path))

    bad_beat = client.post("/edit_chord", json=_payload(tmp_path, beat_index=99, chord="F"))
    bad_chord = client.post("/edit_chord", json=_payload(tmp_path, beat_index=0, chord="H7"))

    assert bad_beat.status_code == 400
    assert bad_chord.status_code == 400
    assert "out of range" in bad_beat.get_json()["error"]
    assert "invalid chord label" in bad_chord.get_json()["error"]


def test_edit_route_success_updates_and_persists(tmp_path):
    app_wrapper, client = make_client()
    _activate_editable(app_wrapper, tmp_path)
    client.post("/start_chord_editing", json=_payload(tmp_path))

    response = client.post("/edit_chord", json=_payload(tmp_path, beat_index=1, chord="F"))

    assert response.status_code == 200
    assert response.get_json()["success"] is True
    stored = ChordData(_state(app_wrapper).file_repr.get("json")).chord_track_chords("user_edited")
    assert any(entry["chord"] == "F" for entry in stored)


def test_start_route_save_failure_restores_player_and_disk(tmp_path, monkeypatch):
    app_wrapper, client = make_client()
    _activate_editable(app_wrapper, tmp_path)
    _state(app_wrapper).player.chord_data.set_chord_track(
        "pytorch", [{"timestamp": 0.0, "chord": "F"}]
    )
    _state(app_wrapper).player.chord_data.set_rhythm_track(
        "madmom", bpm=110, meter_signature=4,
        beat_times=[0.0, 0.5], beat_numbers=[1, 2],
    )
    json_path = _state(app_wrapper).file_repr.get("json")
    _state(app_wrapper).player.chord_data.save_to_file(json_path)
    _state(app_wrapper).player.select_analysis_tracks(
        chord_track_id="pytorch", rhythm_track_id="madmom"
    )
    original_bytes = Path(json_path).read_bytes()

    def fail_save(file_path):
        raise OSError("simulated save failure")

    monkeypatch.setattr(_state(app_wrapper).player.chord_data, "save_to_file", fail_save)

    response = client.post("/start_chord_editing", json=_payload(tmp_path))

    assert response.status_code == 500
    assert "Could not save chord data" in response.get_json()["error"]
    assert Path(json_path).read_bytes() == original_bytes
    assert _state(app_wrapper).player.chord_data.has_chord_track("user_edited") is False
    assert _state(app_wrapper).player.active_chord_version() == "original"
    assert _state(app_wrapper).player.chord_data.active_chord_track_id == "pytorch"
    assert _state(app_wrapper).player.chord_data.active_rhythm_track_id == "madmom"
    assert _state(app_wrapper).player.playback_view.repeat_mode == "changes"


def test_edit_route_save_failure_restores_player_and_disk(tmp_path, monkeypatch):
    app_wrapper, client = make_client()
    _activate_editable(app_wrapper, tmp_path)
    client.post("/start_chord_editing", json=_payload(tmp_path))
    json_path = _state(app_wrapper).file_repr.get("json")
    original_bytes = Path(json_path).read_bytes()
    original_chords = _state(app_wrapper).player.chord_data.chord_track_chords("user_edited")

    def fail_save(file_path):
        raise OSError("simulated save failure")

    monkeypatch.setattr(_state(app_wrapper).player.chord_data, "save_to_file", fail_save)

    response = client.post("/edit_chord", json=_payload(tmp_path, beat_index=1, chord="F"))

    assert response.status_code == 500
    assert "Could not save chord data" in response.get_json()["error"]
    assert Path(json_path).read_bytes() == original_bytes
    assert _state(app_wrapper).player.chord_data.chord_track_chords("user_edited") == original_chords
    assert _state(app_wrapper).player.chord_data.active_chord_track_id == "user_edited"
    assert _state(app_wrapper).player.chord_data.active_rhythm_track_id == "qm_barbeattracker"
    assert _state(app_wrapper).player.playback_view.repeat_mode == "changes"


def test_reset_route_save_failure_restores_player_and_disk(tmp_path, monkeypatch):
    app_wrapper, client = make_client()
    _activate_editable(app_wrapper, tmp_path)
    client.post("/start_chord_editing", json=_payload(tmp_path))
    json_path = _state(app_wrapper).file_repr.get("json")
    original_bytes = Path(json_path).read_bytes()

    def fail_save(file_path):
        raise OSError("simulated save failure")

    monkeypatch.setattr(_state(app_wrapper).player.chord_data, "save_to_file", fail_save)

    response = client.post("/reset_edited_chords", json=_payload(tmp_path))

    assert response.status_code == 500
    assert "Could not save chord data" in response.get_json()["error"]
    assert Path(json_path).read_bytes() == original_bytes
    assert _state(app_wrapper).player.chord_data.has_chord_track("user_edited") is True
    assert _state(app_wrapper).player.chord_data.active_chord_track_id == "user_edited"
    assert _state(app_wrapper).player.chord_data.active_rhythm_track_id == "qm_barbeattracker"
    assert _state(app_wrapper).player.playback_view.repeat_mode == "changes"


def test_set_chord_version_route(tmp_path):
    app_wrapper, client = make_client()
    _activate_editable(app_wrapper, tmp_path)
    client.post("/start_chord_editing", json=_payload(tmp_path))

    original = client.post("/set_chord_version", json=_payload(tmp_path, version="original"))

    assert original.status_code == 200
    assert original.get_json()["active_chord_version"] == "original"

    edited = client.post("/set_chord_version", json=_payload(tmp_path, version="edited"))
    assert edited.get_json()["active_chord_version"] == "edited"

    invalid = client.post("/set_chord_version", json=_payload(tmp_path, version="nope"))
    assert invalid.status_code == 400


def test_reset_edited_chords_route(tmp_path):
    app_wrapper, client = make_client()
    _activate_editable(app_wrapper, tmp_path)
    client.post("/start_chord_editing", json=_payload(tmp_path))

    response = client.post("/reset_edited_chords", json=_payload(tmp_path))

    assert response.status_code == 200
    assert response.get_json()["has_edited"] is False
    assert not ChordData(_state(app_wrapper).file_repr.get("json")).has_chord_track("user_edited")


def test_reanalyze_preserves_edited_by_default(tmp_path):
    app_wrapper, client = make_client()
    _activate_editable(app_wrapper, tmp_path)
    client.post("/start_chord_editing", json=_payload(tmp_path))
    app_wrapper.analysis_queue = AnalysisQueue(tmp_path / "queue")

    response = client.post("/reanalyze", json=_payload(tmp_path))

    assert response.status_code == 200
    pending = app_wrapper.analysis_queue.status()["pending"]
    assert pending[0]["force"] is True
    assert pending[0]["discard_edits"] is False


def test_reanalyze_accepts_discard_and_persists_flag(tmp_path):
    app_wrapper, client = make_client()
    _activate_editable(app_wrapper, tmp_path)
    client.post("/start_chord_editing", json=_payload(tmp_path))
    app_wrapper.analysis_queue = AnalysisQueue(tmp_path / "queue")

    response = client.post("/reanalyze", json=_payload(tmp_path, discard_edits=True))

    assert response.status_code == 200
    pending = app_wrapper.analysis_queue.status()["pending"]
    assert pending[0]["discard_edits"] is True
    assert pending[0]["force"] is True


def test_reanalyze_rejects_non_bool_discard_edits(tmp_path):
    app_wrapper, client = make_client()
    _activate_editable(app_wrapper, tmp_path)

    response = client.post("/reanalyze", json=_payload(tmp_path, discard_edits="yes"))

    assert response.status_code == 400


def test_reanalyze_rejects_media_with_pending_work(tmp_path):
    app_wrapper, client = make_client()
    _activate_editable(app_wrapper, tmp_path)
    client.post("/start_chord_editing", json=_payload(tmp_path))
    app_wrapper.analysis_queue = AnalysisQueue(tmp_path / "queue")
    app_wrapper.analysis_queue.enqueue(str(_state(app_wrapper).file_repr.get()))

    response = client.post("/reanalyze", json=_payload(tmp_path, discard_edits=True))

    assert response.status_code == 409
    assert "already has queued analysis work" in response.get_json()["error"]


def test_reanalyze_rejects_media_with_processing_work(tmp_path):
    app_wrapper, client = make_client()
    _activate_editable(app_wrapper, tmp_path)
    client.post("/start_chord_editing", json=_payload(tmp_path))
    app_wrapper.analysis_queue = AnalysisQueue(tmp_path / "queue")
    app_wrapper.analysis_queue.enqueue(str(_state(app_wrapper).file_repr.get()))
    app_wrapper.analysis_queue.peek()

    response = client.post("/reanalyze", json=_payload(tmp_path, discard_edits=True))

    assert response.status_code == 409
    assert "already has queued analysis work" in response.get_json()["error"]


def test_reanalyze_accepts_unedited_media_without_discard(tmp_path):
    app_wrapper, client = make_client()
    _activate_editable(app_wrapper, tmp_path)
    app_wrapper.analysis_queue = AnalysisQueue(tmp_path / "queue")

    response = client.post("/reanalyze", json=_payload(tmp_path))

    assert response.status_code == 200
    pending = app_wrapper.analysis_queue.status()["pending"]
    assert pending[0]["force"] is True
    assert pending[0]["discard_edits"] is False


def test_load_file_defaults_to_edited_when_present(tmp_path):
    app_wrapper, client = make_client()
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    file_repr = FileRepr(str(media), datapath=str(tmp_path / ".chordflask"), create=True)
    track = _editable_data()
    track.create_beat_aligned_track("user_edited")
    track.save_to_file(file_repr.get("json"))

    response = client.post("/load_file", json={
        "dirname": str(tmp_path), "filename": "song.mp4",
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["active_chord_track_id"] == "user_edited"
    assert payload["has_edited"] is True
    assert payload["active_chord_version"] == "edited"


def test_load_file_without_edited_behaves_as_before(tmp_path):
    app_wrapper, client = make_client()
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    file_repr = FileRepr(str(media), datapath=str(tmp_path / ".chordflask"), create=True)
    _editable_data().save_to_file(file_repr.get("json"))

    response = client.post("/load_file", json={
        "dirname": str(tmp_path), "filename": "song.mp4",
    })

    payload = response.get_json()
    assert payload["active_chord_track_id"] == "chordino"
    assert payload["has_edited"] is False
    assert payload["active_chord_version"] == "original"


def test_load_file_explicit_chordino_stays_chordino(tmp_path):
    app_wrapper, client = make_client()
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    file_repr = FileRepr(str(media), datapath=str(tmp_path / ".chordflask"), create=True)
    track = _editable_data()
    track.create_beat_aligned_track("user_edited")
    track.save_to_file(file_repr.get("json"))

    response = client.post("/load_file", json={
        "dirname": str(tmp_path), "filename": "song.mp4", "chord_track_id": "chordino",
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["active_chord_track_id"] == "chordino"
    assert payload["active_chord_version"] == "original"
    assert payload["has_edited"] is True


def test_load_file_default_edited_selects_qm_rhythm(tmp_path):
    app_wrapper, client = make_client()
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    file_repr = FileRepr(str(media), datapath=str(tmp_path / ".chordflask"), create=True)
    track = _editable_data()
    track.set_rhythm_track(
        "madmom", bpm=120, meter_signature=4,
        beat_times=[0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
        beat_numbers=[1, 2, 3, 4, 1, 2, 3, 4],
    )
    track.create_beat_aligned_track("user_edited")
    track.save_to_file(file_repr.get("json"))

    response = client.post("/load_file", json={
        "dirname": str(tmp_path), "filename": "song.mp4",
    })

    payload = response.get_json()
    assert payload["active_chord_track_id"] == "user_edited"
    assert payload["active_rhythm_track_id"] == "qm_barbeattracker"


# ── set_position edit grid ───────────────────────────────────────────


def test_set_position_returns_edit_grid_when_requested(tmp_path):
    app_wrapper, client = make_client()
    _activate_editable(app_wrapper, tmp_path)
    client.post("/start_chord_editing", json=_payload(tmp_path))

    response = client.post("/set_position", json={
        "position": 0.5, "include_edit_grid": True,
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["edit_grid"]["beat_count"] == 8


def test_set_position_same_position_still_returns_edit_grid(tmp_path):
    app_wrapper, client = make_client()
    _activate_editable(app_wrapper, tmp_path)
    client.post("/start_chord_editing", json=_payload(tmp_path))
    client.post("/set_position", json={"position": 0.5, "include_edit_grid": True})

    response = client.post("/set_position", json={
        "position": 0.5, "include_edit_grid": True,
    })

    payload = response.get_json()
    assert payload["success"] is True
    assert "edit_grid" in payload
    assert payload["edit_grid"]["beat_count"] == 8


def test_set_position_omits_edit_grid_unless_requested(tmp_path):
    app_wrapper, client = make_client()
    _activate_editable(app_wrapper, tmp_path)
    client.post("/start_chord_editing", json=_payload(tmp_path))

    response = client.post("/set_position", json={"position": 0.5})

    assert response.status_code == 200
    assert "edit_grid" not in response.get_json()


def test_set_position_rejects_non_bool_include_edit_grid(tmp_path):
    app_wrapper, client = make_client()
    _activate_editable(app_wrapper, tmp_path)

    response = client.post("/set_position", json={
        "position": 0.5, "include_edit_grid": "yes",
    })

    assert response.status_code == 400


def test_start_chord_editing_rejects_qm_without_beat_times(tmp_path):
    app_wrapper, client = make_client()
    _activate_manual_analysis(
        app_wrapper, tmp_path,
        chord_tracks={"chordino": {"chords": [{"timestamp": 0.0, "chord": "C"}], "metadata": {}}},
        rhythm_tracks={"qm_barbeattracker": {
            "bpm": 120, "meter_signature": 4,
            "beat_times": [], "beat_numbers": [], "metadata": {},
        }},
    )

    response = client.post("/start_chord_editing", json=_payload(tmp_path))

    assert response.status_code == 400
    assert "no beat times" in response.get_json()["error"]


def test_update_analysis_tracks_rejects_rhythm_switch_while_edited(tmp_path):
    app_wrapper, client = make_client()
    _activate_manual_analysis(
        app_wrapper, tmp_path,
        chord_tracks={"chordino": {"chords": [{"timestamp": 0.0, "chord": "C"}], "metadata": {}}},
        rhythm_tracks={
            "qm_barbeattracker": {
                "bpm": 120, "meter_signature": 4,
                "beat_times": [0.0, 0.5], "beat_numbers": [1, 2], "metadata": {},
            },
            "madmom": {
                "bpm": 120, "meter_signature": 4,
                "beat_times": [0.0, 0.5], "beat_numbers": [1, 2], "metadata": {},
            },
        },
    )
    client.post("/start_chord_editing", json=_payload(tmp_path))

    response = client.post("/update_analysis_tracks", json={"rhythm_track_id": "madmom"})

    assert response.status_code == 400
    assert "Rhythm source is fixed" in response.get_json()["error"]


# ── browser contract ─────────────────────────────────────────────────


def test_index_contains_chord_editing_controls():
    _, client = make_client()

    body = client.get("/").get_data(as_text=True)

    assert 'id="editButton"' in body
    assert 'aria-label="Edit chords"' in body
    assert 'id="editGridContainer" hidden' in body
    assert 'id="editGrid"' in body
    assert 'id="editTools" hidden' in body
    assert 'id="undoEditButton"' in body
    assert 'id="resetEditButton"' in body
    assert 'id="editChordDialog"' in body
    assert 'id="editChordInput"' in body
    assert 'id="editSuggestions"' in body


def test_index_contains_editing_fetch_and_flow_contract():
    _, client = make_client()

    body = client.get("/").get_data(as_text=True)

    assert "fetch('/start_chord_editing'" in body
    assert "fetch('/edit_chord'" in body
    assert "fetch('/reset_edited_chords'" in body
    assert "function updateEditControls()" in body
    assert "function exitEditMode()" in body
    assert "function startChordEditing()" in body
    assert "function openEditDialog(cell)" in body
    assert "function undoLastEdit()" in body
    assert "function resetEditedChords()" in body
    assert "discard_edits: discardEdits" not in body
    assert "Your Edited chords will be preserved" in body
    assert "Permanently discard all Edited chords" in body
    assert "has_edited" in body


def test_index_uses_unified_chord_selector():
    _, client = make_client()

    body = client.get("/").get_data(as_text=True)

    assert 'id="chordTrackSelect"' in body
    assert "activeChord === 'user_edited' ? 'chordino' : activeChord" not in body
    assert "chord_track_id: desiredChordTrackId || undefined" in body


def test_index_contains_editing_session_state_contract():
    _, client = make_client()

    body = client.get("/").get_data(as_text=True)

    assert "function clearEditUndo()" in body
    assert "rhythmTrackSelect.disabled = activeChord === 'user_edited'" in body
    assert "editUndoStack[editUndoStack.length - 1]" in body
    assert "let reanalysisQueuedPath = null" in body
    assert "function refreshLoadedAnalysis()" in body
    assert "include_edit_grid: editMode" in body
    assert "dataDict.edit_grid" in body
    assert "reanalysisQueuedPath = data.mp4_file" in body
    assert "addEventListener('close', closeEditDialog)" in body


def test_index_edit_and_version_guard_duplicate_requests():
    _, client = make_client()

    body = client.get("/").get_data(as_text=True)

    assert "function submitEdit(beatIndex, chord, recordUndo = true, onSuccess = null)" in body
    assert "if (editRequestInFlight || !currentEditCell)" in body
