import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FLASK_DIR = REPO_ROOT / "flask"
HELPERS_DIR = FLASK_DIR / "helpers"

for path in (FLASK_DIR, HELPERS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from batch_core import analyze_file_safe, find_media_files, run_serial
import chordbatch


class FakeAnalyzer:
    calls = []

    def __init__(self, filename):
        self.filename = filename
        self.calls.append(filename)

    def process(self):
        pass


class FailingAnalyzer:
    def __init__(self, filename):
        self.filename = filename

    def process(self):
        raise RuntimeError("analysis failed")


def test_find_media_files_returns_mp4_and_webm_sorted_by_size(tmp_path):
    small = tmp_path / "b.webm"
    large = tmp_path / "a.mp4"
    ignored = tmp_path / "notes.txt"
    small.write_bytes(b"1")
    large.write_bytes(b"12345")
    ignored.write_text("ignored")

    files = find_media_files(tmp_path)

    assert files == [small, large]


def test_analyze_file_safe_returns_success_payload(tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"123")
    FakeAnalyzer.calls = []

    result = analyze_file_safe(media, FakeAnalyzer)

    assert result == {
        "filename": str(media),
        "size_mb": 0,
        "ok": True,
        "error": None,
    }
    assert FakeAnalyzer.calls == [str(media)]


def test_analyze_file_safe_captures_analysis_errors(tmp_path):
    media = tmp_path / "broken.mp4"
    media.write_bytes(b"123")

    result = analyze_file_safe(media, FailingAnalyzer)

    assert result["filename"] == str(media)
    assert result["ok"] is False
    assert result["error"] == "analysis failed"


def test_run_serial_continues_after_failed_file(tmp_path):
    good = tmp_path / "good.mp4"
    bad = tmp_path / "bad.mp4"
    good.write_bytes(b"1")
    bad.write_bytes(b"22")
    messages = []

    def analyzer_factory(filename):
        if filename.endswith("bad.mp4"):
            return FailingAnalyzer(filename)
        return FakeAnalyzer(filename)

    results = run_serial(tmp_path, analyzer_factory, output=messages.append)

    assert [result["ok"] for result in results] == [True, False]
    assert any("Done: 1 ok, 1 failed" in message for message in messages)


def test_chordbatch_main_returns_failure_when_any_file_fails(tmp_path, monkeypatch):
    media = tmp_path / "bad.mp4"
    media.write_bytes(b"1")

    monkeypatch.setattr(chordbatch, "ChordAnalyzer", FailingAnalyzer)

    assert chordbatch.main([str(tmp_path)]) == 1


def test_chordbatch_main_returns_usage_error_for_missing_directory(tmp_path, capsys):
    missing = tmp_path / "missing"

    assert chordbatch.main([str(missing)]) == 2
    assert "Media directory does not exist" in capsys.readouterr().err
