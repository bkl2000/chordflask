import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
HELPERS_DIR = REPO_ROOT / "flask" / "helpers"

if str(HELPERS_DIR) not in sys.path:
    sys.path.insert(0, str(HELPERS_DIR))

from convert_chordlabels_to_cnn import ChordLabelConverter


def _write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_convert_v1_format_reads_base_chords(tmp_path):
    in_path = _write_json(tmp_path / "in.json", {
        "base_chords": [
            {"timestamp": 0.0, "chord": "C:maj"},
            {"timestamp": 1.0, "chord": "G:maj"},
        ],
    })
    out_path = tmp_path / "out.json"

    ChordLabelConverter(verbose=False).convert_file(str(in_path), str(out_path))

    result = json.loads(out_path.read_text())
    assert result == [
        {"time": 0.0, "chord": "C:maj"},
        {"time": 1.0, "chord": "G:maj"},
    ]


def test_convert_v3_format_reads_chordino_track(tmp_path):
    in_path = _write_json(tmp_path / "in.json", {
        "schema_version": 3,
        "chord_tracks": {
            "chordino": {
                "chords": [
                    {"timestamp": 0.5, "chord": "Am"},
                    {"timestamp": 2.3, "chord": "F"},
                ],
            },
        },
    })
    out_path = tmp_path / "out.json"

    ChordLabelConverter(verbose=False).convert_file(str(in_path), str(out_path))

    result = json.loads(out_path.read_text())
    assert result == [
        {"time": 0.5, "chord": "Am"},
        {"time": 2.3, "chord": "F"},
    ]


def test_convert_v3_requires_chordino_track(tmp_path):
    in_path = _write_json(tmp_path / "in.json", {
        "schema_version": 3,
        "chord_tracks": {
            "other": {"chords": [{"timestamp": 0.0, "chord": "D"}]},
        },
    })
    out_path = tmp_path / "out.json"

    with pytest.raises(ValueError, match="chordino.chords is required"):
        ChordLabelConverter(verbose=False).convert_file(str(in_path), str(out_path))


def test_convert_invalid_json_propagates_decode_error(tmp_path):
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("", encoding="utf-8")
    out_path = tmp_path / "out.json"
    converter = ChordLabelConverter(verbose=False)
    with pytest.raises(json.JSONDecodeError):
        converter.convert_file(str(invalid_path), str(out_path))


def test_convert_unknown_schema_falls_back_to_data_and_fails_cleanly(tmp_path):
    in_path = _write_json(tmp_path / "in.json", {
        "schema_version": 99,
    })
    out_path = tmp_path / "out.json"

    with pytest.raises(ValueError, match="Unsupported chord schema version 99"):
        ChordLabelConverter(verbose=False).convert_file(str(in_path), str(out_path))
