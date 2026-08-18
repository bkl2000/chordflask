"""Tests for the ``chordflask-maintain stems`` report and cleanup."""

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]

from chordflask_base import ChordData, DEMUCS_STEM_NAMES  # noqa: E402

from chordflask_maintain import stems as stems_mod  # noqa: E402
from chordflask_maintain.stems import (  # noqa: E402
    DEMUCS_AUDIO_SET_ID,
    cleanup_orphan_stems,
    inspect_stems,
)

STEMS_REL = Path(".chordflask") / "stems" / "demucs" / "htdemucs" / "key" / "gen"


@pytest.fixture(autouse=True)
def isolate_queue_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("CHORDFLASK_QUEUE_DIR", str(tmp_path / "queue"))


def _audio_set(rel_dir: Path):
    tracks = {}
    for index, stem in enumerate(DEMUCS_STEM_NAMES):
        tracks[stem] = {
            "path": str(rel_dir / f"{stem}.flac"),
            "format": "flac",
            "sample_rate": 44100,
            "channels": 2,
            "sample_count": 44100,
            "duration": 1.0,
            "size": 100 + index,
            "sha256": f"{index + 1:064x}",
        }
    return {
        "provider": "demucs",
        "model": "htdemucs",
        "tracks": tracks,
        "metadata": {
            "source": {
                "sha256": "a" * 64,
                "size": 1000,
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
                "tail_adjustment_samples": {
                    "bass": 0, "drums": 0, "other": 0, "vocals": 0,
                },
            },
            "source_timeline": {"available": False},
        },
    }


def _write_flac(media_root: Path, rel_dir: Path, stem: str, content=b"flac"):
    path = media_root / rel_dir / f"{stem}.flac"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _write_song_with_set(media_root: Path, *, name="song.mp3", rel_dir=None, set_data=None):
    media = media_root / name
    media.write_bytes(b"not decoded by this module")
    analysis_dir = media_root / ".chordflask"
    analysis_dir.mkdir(exist_ok=True)
    data = ChordData()
    data.set_audio_track(DEMUCS_AUDIO_SET_ID, set_data or _audio_set(rel_dir or STEMS_REL))
    data.save_to_file(analysis_dir / f"{media.stem}.json")
    return media


def _write_full_song(media_root: Path, *, name="song.mp3", rel_dir=None):
    rel = rel_dir or STEMS_REL
    _write_song_with_set(media_root, name=name, rel_dir=rel)
    for stem in DEMUCS_STEM_NAMES:
        _write_flac(media_root, rel, stem)
    return media_root / name


# ── report ────────────────────────────────────────────────────────────


def test_report_no_stem_storage(tmp_path):
    report = inspect_stems(tmp_path)
    assert report.exists is False
    text = stems_mod.format_stems_report(report)
    assert "no Demucs stem storage" in text


def test_report_complete_set(tmp_path):
    _write_full_song(tmp_path)

    report = inspect_stems(tmp_path)

    assert report.exists is True
    assert len(report.records) == 1
    assert report.records[0].status == "complete"
    assert report.records[0].media_stem == "song"
    assert report.total_bytes == 4 * 4  # four "flac" bytes
    assert report.orphans == []
    text = stems_mod.format_stems_report(report)
    assert "song: complete" in text
    assert "orphan generations: 0" in text


def test_report_incomplete_set_missing_file(tmp_path):
    _write_full_song(tmp_path)
    (tmp_path / STEMS_REL / "vocals.flac").unlink()

    report = inspect_stems(tmp_path)

    assert report.records[0].status == "incomplete"
    assert report.records[0].missing_files == ["vocals"]
    text = stems_mod.format_stems_report(report)
    assert "missing: vocals" in text


def test_report_orphan_generation(tmp_path):
    _write_full_song(tmp_path)
    orphan = tmp_path / ".chordflask" / "stems" / "demucs" / "htdemucs" / "old-key" / "old-gen"
    (orphan / "orphan.flac").parent.mkdir(parents=True, exist_ok=True)
    (orphan / "orphan.flac").write_bytes(b"xxxxxx")

    report = inspect_stems(tmp_path)

    assert len(report.orphans) == 1
    assert report.orphans[0][1] == 6
    assert report.records[0].status == "complete"
    text = stems_mod.format_stems_report(report)
    assert "orphan generations: 1" in text


def test_report_ignores_non_analysis_json(tmp_path):
    _write_full_song(tmp_path)
    (tmp_path / ".chordflask" / "song.training.json").write_text(
        '{"some": "training data"}', encoding="utf-8"
    )

    report = inspect_stems(tmp_path)

    assert report.invalid == []
    assert len(report.records) == 1


def test_report_invalid_analysis_json(tmp_path):
    _write_full_song(tmp_path)
    (tmp_path / ".chordflask" / "broken.json").write_text("{not json", encoding="utf-8")

    report = inspect_stems(tmp_path)

    assert len(report.invalid) == 1
    text = stems_mod.format_stems_report(report)
    assert "invalid JSON" in text


# ── cleanup ───────────────────────────────────────────────────────────


def test_cleanup_removes_only_orphans(tmp_path):
    _write_full_song(tmp_path)
    orphan = tmp_path / ".chordflask" / "stems" / "demucs" / "htdemucs" / "old-key" / "old-gen"
    (orphan / "orphan.flac").parent.mkdir(parents=True, exist_ok=True)
    (orphan / "orphan.flac").write_bytes(b"xxxxxx")
    json_before = (tmp_path / ".chordflask" / "song.json").read_bytes()

    result = cleanup_orphan_stems(tmp_path)

    assert not result.refused
    assert len(result.removed) == 1
    assert not orphan.exists()
    # referenced generation survives
    assert (tmp_path / STEMS_REL / "vocals.flac").exists()
    # analysis JSON is byte-for-byte unchanged
    assert (tmp_path / ".chordflask" / "song.json").read_bytes() == json_before


def test_cleanup_dry_run_has_no_side_effects(tmp_path):
    _write_full_song(tmp_path)
    orphan = tmp_path / ".chordflask" / "stems" / "demucs" / "htdemucs" / "old-key" / "old-gen"
    (orphan / "orphan.flac").parent.mkdir(parents=True, exist_ok=True)
    (orphan / "orphan.flac").write_bytes(b"xxxxxx")

    result = cleanup_orphan_stems(tmp_path, dry_run=True)

    assert len(result.removed) == 1
    assert orphan.exists()


def test_cleanup_refuses_on_invalid_analysis_json(tmp_path):
    _write_full_song(tmp_path)
    orphan = tmp_path / ".chordflask" / "stems" / "demucs" / "htdemucs" / "old-key" / "old-gen"
    (orphan / "orphan.flac").parent.mkdir(parents=True, exist_ok=True)
    (orphan / "orphan.flac").write_bytes(b"xxxxxx")
    (tmp_path / ".chordflask" / "broken.json").write_text("{not json", encoding="utf-8")

    result = cleanup_orphan_stems(tmp_path)

    assert result.refused is True
    assert orphan.exists()


def test_cleanup_skips_symlink_generation(tmp_path):
    _write_full_song(tmp_path)
    outside = tmp_path / "outside.flac"
    outside.write_bytes(b"escape")
    link_parent = tmp_path / ".chordflask" / "stems" / "demucs" / "htdemucs" / "link-key"
    link_parent.mkdir(parents=True, exist_ok=True)
    link = link_parent / "link-gen"
    link.symlink_to(tmp_path)

    cleanup_orphan_stems(tmp_path)

    assert outside.exists()
    assert link.is_symlink()


def test_cleanup_never_deletes_outside_stems_root(tmp_path):
    _write_full_song(tmp_path)
    # A stray directory directly under .chordflask (not under stems/) must be untouched.
    stray = tmp_path / ".chordflask" / "not-stems"
    stray.mkdir()
    (stray / "keep.txt").write_text("keep")

    result = cleanup_orphan_stems(tmp_path)

    assert (stray / "keep.txt").exists()
    assert result.removed == []


def test_cleanup_requires_orphans_flag(tmp_path):
    from chordflask_maintain import cli

    with pytest.raises(SystemExit) as exc:
        cli.main(["stems", "cleanup", str(tmp_path)])
    assert exc.value.code == 2


# ── CLI dispatch ──────────────────────────────────────────────────────


def test_stems_subcommand_is_listed_in_help(capsys):
    from chordflask_maintain import cli

    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    assert "stems" in capsys.readouterr().out


def test_stems_report_dispatches(capsys, tmp_path):
    from chordflask_maintain import cli

    with pytest.raises(SystemExit) as exc:
        cli.main(["stems", "report", str(tmp_path)])
    assert exc.value.code == 0
    assert "no Demucs stem storage" in capsys.readouterr().out


# ── framework-free boundary ───────────────────────────────────────────


def test_stems_module_has_no_demucs_or_torch_import():
    source = (REPO_ROOT / "chordflask_maintain" / "stems.py").read_text(encoding="utf-8")
    for forbidden in (
        "import torch",
        "import demucs",
        "from chordflask_demucs",
        "import chordflask_demucs",
        "import librosa",
    ):
        assert forbidden not in source
