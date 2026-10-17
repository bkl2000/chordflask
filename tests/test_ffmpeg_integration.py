import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


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
    import chordflask.app as chordflask

    def fake_worker_init(*args, **kwargs):
        raise SystemExit(0)

    chordflask.AnalysisWorker = type("FakeWorker", (), {"__init__": fake_worker_init, "run_forever": lambda self: 0})

    chordflask.FlaskMP4App()

    assert "IMAGEIO_FFMPEG_EXE" in os.environ
    assert os.environ["IMAGEIO_FFMPEG_EXE"] == subprocess.run(
        ["which", "ffmpeg"], capture_output=True, text=True
    ).stdout.strip() or os.environ["IMAGEIO_FFMPEG_EXE"]


@pytest.mark.parametrize("frozen", [False, True])
@pytest.mark.parametrize("original", [None, "", "/host/lib"])
def test_ffmpeg_child_environment_preserves_python_runtime(monkeypatch, tmp_path, frozen, original):
    from chordflask.ffmpeg_runtime import require_system_ffmpeg

    probe = tmp_path / "ffmpeg"
    probe.write_text(
        '#!/usr/bin/env bash\n'
        'printf "%s\\n" "${LD_LIBRARY_PATH-unset}" "$PWD" "$@"\n'
        'exit 7\n'
    )
    probe.chmod(0o755)
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("LD_LIBRARY_PATH", "/bundle/lib:/host/lib")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    if original is not None:
        monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", original)
    for name in ("IMAGEIO_FFMPEG_EXE", "FFMPEG_BINARY", "CHORDFLASK_SYSTEM_FFMPEG"):
        monkeypatch.delenv(name, raising=False)

    command = require_system_ffmpeg()
    result = subprocess.run(
        [command, "file with spaces.mp4", "$(literal);argument"],
        cwd=tmp_path, capture_output=True, text=True,
    )

    expected = (original or "unset") if frozen else "/bundle/lib:/host/lib"
    assert result.stdout.splitlines() == [
        expected, str(tmp_path), "file with spaces.mp4", "$(literal);argument",
    ]
    assert result.returncode == 7
    assert os.environ["LD_LIBRARY_PATH"] == "/bundle/lib:/host/lib"
    assert os.environ.get("LD_LIBRARY_PATH_ORIG") == original
    assert os.environ["IMAGEIO_FFMPEG_EXE"] == command
    assert os.environ["FFMPEG_BINARY"] == command


@pytest.mark.parametrize("frozen", [False, True])
def test_system_ffmpeg_is_required_even_with_imageio_override(monkeypatch, tmp_path, frozen):
    from chordflask.ffmpeg_runtime import require_system_ffmpeg

    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("IMAGEIO_FFMPEG_EXE", "/wheel/ffmpeg")

    with pytest.raises(RuntimeError, match="sudo apt install ffmpeg"):
        require_system_ffmpeg()


@pytest.mark.parametrize("entrypoint", ["cli", "worker"])
def test_frozen_analysis_configures_moviepy_before_import_and_cleans_ffmpeg(
    tmp_path, entrypoint,
):
    """Real MoviePy conversion; acoustic analysis/export are stubbed in a fresh interpreter.

    This simulates frozen state and the missing wheel resource, not a built ELF.
    """
    ffmpeg = shutil.which("ffmpeg")
    media = tmp_path / "song with spaces.mp4"
    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i", "color=size=16x16:duration=0.2",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2",
         "-c:v", "mpeg4", "-c:a", "aac", str(media)],
        check=True, capture_output=True,
    )
    # Probe every actual FFmpeg child, including MoviePy's reader and writer.
    probe_dir = tmp_path / "bin"
    probe_dir.mkdir()
    probe = probe_dir / "ffmpeg"
    probe.write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\n'
        'printf "%s\\n" "${LD_LIBRARY_PATH-unset}" >> "$FFMPEG_PROBE_LOG"\n'
        f'exec {shlex.quote(ffmpeg)} "$@"\n'
    )
    probe.chmod(0o755)
    log = tmp_path / "ffmpeg.log"
    script = r'''
import importlib.abc
import os
from pathlib import Path
import sys

class NoBundledFFmpeg(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "imageio_ffmpeg.binaries":
            raise ModuleNotFoundError(fullname)

sys.meta_path.insert(0, NoBundledFFmpeg())
import chordflask.app as app
from chordflask.audio_analyzer import AudioAnalyzer
from chordflask.chord_exporter import ChordExporter
from chordflask import vamp_runtime
from chordflask_base import ChordData, ChordTrackRepository
from chordflask.filerepr import FileRepr

assert "moviepy" not in sys.modules
sys.frozen = True
vamp_runtime.require_vamp_plugins = lambda: None
def analyze(self, path, **kwargs):
    assert Path(path).stat().st_size > 100
    data = ChordData()
    data.set_chord_track("chordino", [{"timestamp": 0.0, "chord": "C"}])
    data.set_rhythm_track("qm_barbeattracker", bpm=120, meter_signature=4,
                         beat_times=[0.0, 0.5], beat_numbers=[1, 2])
    return data
AudioAnalyzer.analyze = analyze
ChordExporter.write_midi_and_musicxml = lambda *args: None
media = Path(sys.argv[2])
if sys.argv[1] == "cli":
    try:
        app.main(["--analyze", str(media)])
    except SystemExit as error:
        assert error.code == 0
else:
    from chordflask.analysis_queue import AnalysisQueue
    from chordflask.analysis_worker import AnalysisWorker
    queue = AnalysisQueue(media.parent / "queue")
    queue.enqueue(str(media))
    assert AnalysisWorker(queue=queue).run_once()
    assert not queue.peek()
file_repr = FileRepr(str(media))
data = ChordTrackRepository().load(file_repr.get("json"))
assert data.available_chord_track_ids == ["chordino"]
assert Path(file_repr.get("mp3")).stat().st_size > 100
from imageio_ffmpeg import get_ffmpeg_exe
from moviepy.config import FFMPEG_BINARY
assert get_ffmpeg_exe() == FFMPEG_BINARY == os.environ["IMAGEIO_FFMPEG_EXE"]
assert os.environ["LD_LIBRARY_PATH"] == "/fake-pyinstaller/lib"
'''
    env = os.environ.copy()
    for name in ("IMAGEIO_FFMPEG_EXE", "FFMPEG_BINARY", "CHORDFLASK_SYSTEM_FFMPEG",
                 "LD_LIBRARY_PATH_ORIG"):
        env.pop(name, None)
    env.update(
        PATH=str(probe_dir) + os.pathsep + env["PATH"],
        LD_LIBRARY_PATH="/fake-pyinstaller/lib",
        FFMPEG_PROBE_LOG=str(log),
        CHORDFLASK_QUEUE_DIR=str(tmp_path / "queue"),
    )
    result = subprocess.run(
        [sys.executable, "-c", script, entrypoint, str(media)],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    paths = log.read_text().splitlines()
    assert len(paths) >= 3
    assert set(paths) == {"unset"}


def test_chordflask_startup_fails_without_ffmpeg(monkeypatch):
    import chordflask.app as chordflask

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
    import chordflask.media_converter as media_converter

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
    import chordflask.media_converter as media_converter
    from chordflask.filerepr import FileRepr

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
    import chordflask.media_converter as media_converter
    from chordflask.filerepr import FileRepr

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
    import chordflask.audio_analyzer as audio_analyzer

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
    assert '--additional-hooks-dir="${SCRIPT_DIR}/pyinstaller_hooks"' in content
    assert "--copy-metadata=imageio-ffmpeg" not in content
    assert "--add-data \"${VAMP_VENDOR_DIR}:vamp_plugins\"" not in content
    assert "pyi-archive-viewer" not in content
    assert "pyi-archive_viewer -l" in content
    assert "prohibited FFmpeg or Vamp executable" in content
    assert "sudo apt install ffmpeg" in content
    assert '--add-data "${PROJECT_ROOT}/chordflask/ffmpeg-system.sh:chordflask"' in content
    assert os.access(REPO_ROOT / "chordflask" / "ffmpeg-system.sh", os.X_OK)

    import tomllib

    package_data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    assert "ffmpeg-system.sh" in package_data["tool"]["setuptools"]["package-data"]["chordflask"]


def test_build_script_excludes_batch_helper_but_keeps_shared_formatter():
    build_script = REPO_ROOT / "flask" / "build_standalone.sh"
    content = build_script.read_text()

    assert "--exclude-module=chordflask.helpers.chordleadsheet_batch" in content
    assert (REPO_ROOT / "chordflask" / "chord_markdown.py").is_file()
    assert (REPO_ROOT / "chordflask" / "chord_sheet_pdf.py").is_file()
    assert (REPO_ROOT / "chordflask" / "helpers" / "chordleadsheet_batch.py").is_file()
    assert (
        '--add-data "${PROJECT_ROOT}/chordflask/assets:chordflask/assets"'
        in content
    )
    assert "--hidden-import=chordflask_btc.predictor" in content
    assert "--exclude-module=chordflask_btc.model" in content
    assert "--exclude-module=chordflask_btc " not in content
    assert "--exclude-module=chordflask_lyrics" in content
    assert "--exclude-module=pythainlp" in content
    assert "--exclude-module=onnxruntime" in content
    assert "--exclude-module=tltk" in content
    assert "--exclude-module=chordflask_demucs" not in content
    assert "check_standalone_runtime.py" in content
    assert "prohibited heavy optional runtime" in content
    assert 'LIBERATION-FONTS-LICENSE.txt' in content
    for pattern in ("Beat | Time (s) | Chord",):
        assert pattern not in (REPO_ROOT / "chordflask" / "chord_markdown.py").read_text()
