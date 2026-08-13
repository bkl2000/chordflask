import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FLASK_DIR = REPO_ROOT / "flask"

if str(FLASK_DIR) not in sys.path:
    sys.path.insert(0, str(FLASK_DIR))


def test_ffmpeg_on_path():
    result = subprocess.run(
        ["ffmpeg", "-version"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, "ffmpeg is required for media conversion"
    assert "ffmpeg version" in result.stdout.lower()


def test_ffmpeg_reports_moov_atom_error_for_minimal_mp4(tmp_path):
    mp4 = tmp_path / "test.mp4"
    mp4.write_bytes(
        b"\x00\x00\x00\x1cftypmp42\x00\x00\x00\x00mp42mp41"
        b"\x00\x00\x00\x08free"
    )
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(mp4), "-f", "null", "-"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "moov atom not found" in result.stderr


def test_ffmpeg_can_convert_short_audio_to_wav(tmp_path):
    wav = tmp_path / "out.wav"
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=0.1",
            "-ac", "1", "-ar", "8000",
            str(wav),
        ],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert wav.exists()
    assert wav.stat().st_size > 100


def test_imageio_ffmpeg_exe_set_at_startup(monkeypatch):
    import chordflask

    def fake_worker_init(*args, **kwargs):
        raise SystemExit(0)

    chordflask.AnalysisWorker = type("FakeWorker", (), {"__init__": fake_worker_init, "run_forever": lambda self: 0})

    chordflask.FlaskMP4App()

    assert "IMAGEIO_FFMPEG_EXE" in os.environ
    assert os.environ["IMAGEIO_FFMPEG_EXE"] == subprocess.run(
        ["which", "ffmpeg"], capture_output=True, text=True
    ).stdout.strip() or os.environ["IMAGEIO_FFMPEG_EXE"]


def test_chordflask_startup_fails_without_ffmpeg(monkeypatch):
    import chordflask

    def missing_ffmpeg():
        raise RuntimeError(
            "ffmpeg is required but was not found on PATH. "
            "On Ubuntu/Debian install it with: sudo apt install ffmpeg"
        )

    monkeypatch.setattr(chordflask, "require_system_ffmpeg", missing_ffmpeg)

    try:
        chordflask.FlaskMP4App()
    except SystemExit as err:
        assert err.code == 1
    else:
        raise AssertionError("Should exit when ffmpeg is missing")


def test_media_converter_fails_before_opening_media_without_ffmpeg(monkeypatch, tmp_path):
    import media_converter

    class FakeFileRepr:
        def get(self, variant=None):
            if variant == "mp3":
                return str(tmp_path / "missing.mp3")
            return str(tmp_path / "input.mp4")

    def missing_ffmpeg():
        raise RuntimeError("sudo apt install ffmpeg")

    monkeypatch.setattr(media_converter, "require_system_ffmpeg", missing_ffmpeg)

    try:
        media_converter.MediaConverter().ensure_mp3(FakeFileRepr())
    except RuntimeError as error:
        assert "sudo apt install ffmpeg" in str(error)
    else:
        raise AssertionError("Direct media conversion must require system ffmpeg")


def test_media_converter_uses_source_mp3_without_moviepy_or_copy(monkeypatch, tmp_path):
    import media_converter
    from filerepr import FileRepr

    source = tmp_path / "song.MP3"
    source.write_bytes(b"audio")
    file_repr = FileRepr(str(source), create=True)

    def unexpected_video_open(*args, **kwargs):
        raise AssertionError("source MP3 must not be opened with MoviePy")

    def unexpected_ffmpeg_check():
        raise AssertionError("source MP3 needs no conversion preflight")

    monkeypatch.setattr(media_converter, "VideoFileClip", unexpected_video_open)
    monkeypatch.setattr(media_converter, "require_system_ffmpeg", unexpected_ffmpeg_check)

    result = media_converter.MediaConverter().ensure_mp3(file_repr)

    assert result == str(source)
    assert not Path(file_repr.get("mp3")).exists()


def test_media_converter_does_not_publish_or_leave_partial_mp3(monkeypatch, tmp_path):
    import media_converter
    from filerepr import FileRepr

    source = tmp_path / "song.mp4"
    source.write_bytes(b"video")
    file_repr = FileRepr(str(source), create=True)

    class PartialAudio:
        def write_audiofile(self, output_path):
            Path(output_path).write_bytes(b"partial")
            raise RuntimeError("conversion interrupted")

    class FakeVideo:
        audio = PartialAudio()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(media_converter, "require_system_ffmpeg", lambda: None)
    monkeypatch.setattr(media_converter, "VideoFileClip", lambda path: FakeVideo())

    try:
        media_converter.MediaConverter().ensure_mp3(file_repr)
    except RuntimeError as error:
        assert "conversion interrupted" in str(error)
    else:
        raise AssertionError("interrupted conversion must fail")

    assert not Path(file_repr.get("mp3")).exists()
    assert list(Path(file_repr.datapath).glob(".song.convert-*.mp3")) == []


def test_audio_analyzer_fails_before_loading_audio_without_ffmpeg(monkeypatch):
    import audio_analyzer

    def missing_ffmpeg():
        raise RuntimeError("sudo apt install ffmpeg")

    monkeypatch.setattr(audio_analyzer, "require_system_ffmpeg", missing_ffmpeg)

    try:
        audio_analyzer.AudioAnalyzer().analyze("missing.mp3")
    except RuntimeError as error:
        assert "sudo apt install ffmpeg" in str(error)
    else:
        raise AssertionError("Direct audio analysis must require system ffmpeg")


def test_build_script_excludes_embedded_ffmpeg():
    build_script = REPO_ROOT / "flask" / "build_standalone.sh"
    content = build_script.read_text()

    assert "--exclude-module=imageio_ffmpeg.binaries" in content
    assert "--additional-hooks-dir=pyinstaller_hooks" in content
    assert "--copy-metadata=imageio-ffmpeg" not in content
    assert "--add-data \"${VAMP_VENDOR_DIR}:vamp_plugins\"" not in content
    assert "pyi-archive-viewer" not in content
    assert "pyi-archive_viewer -l" in content
    assert "prohibited FFmpeg or Vamp executable" in content
    assert "sudo apt install ffmpeg" in content


def test_build_script_excludes_batch_helper_but_keeps_shared_formatter():
    build_script = REPO_ROOT / "flask" / "build_standalone.sh"
    content = build_script.read_text()

    assert "--exclude-module=chordleadsheet_batch" in content
    assert (REPO_ROOT / "flask" / "chord_markdown.py").is_file()
    assert (REPO_ROOT / "flask" / "helpers" / "chordleadsheet_batch.py").is_file()
    for pattern in ("Beat | Time (s) | Chord",):
        assert pattern not in (REPO_ROOT / "flask" / "chord_markdown.py").read_text()
