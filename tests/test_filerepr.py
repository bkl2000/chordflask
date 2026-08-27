import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FLASK_DIR = REPO_ROOT / "flask"

if str(FLASK_DIR) not in sys.path:
    sys.path.insert(0, str(FLASK_DIR))

from chordflask.filerepr import FileRepr


def test_default_data_directory_is_chordflask(tmp_path):
    media = tmp_path / "song.mp4"

    file_repr = FileRepr(str(media))

    assert file_repr.json_path == str(tmp_path / ".chordflask" / "song.json")


def test_original_and_generated_paths_are_stable(tmp_path):
    media = tmp_path / "song.video.mp4"
    data_dir = tmp_path / "data"

    file_repr = FileRepr(str(media), datapath=str(data_dir))

    assert file_repr.basename == "song.video"
    assert file_repr.get() == str(media)
    assert file_repr.get("json") == str(data_dir / "song.video.json")
    assert file_repr.get("mp3") == str(data_dir / "song.video.mp3")
    assert file_repr.get("xml") == str(data_dir / "song.video.xml")
    assert file_repr.get("mid") == str(data_dir / "song.video.mid")
    assert file_repr.get("song_data") == str(data_dir / "song.video.song")
    assert file_repr.get("png") == str(data_dir / "song.video.png")

    assert file_repr.media_path == str(media)
    assert file_repr.json_path == str(data_dir / "song.video.json")
    assert file_repr.mp3_path == str(data_dir / "song.video.mp3")
    assert file_repr.xml_path == str(data_dir / "song.video.xml")
    assert file_repr.midi_path == str(data_dir / "song.video.mid")
    assert file_repr.song_path == str(data_dir / "song.video.song")


def test_create_makes_data_directory(tmp_path):
    data_dir = tmp_path / "created-data"

    FileRepr(str(tmp_path / "song.mp4"), datapath=str(data_dir), create=True)

    assert data_dir.is_dir()


def test_default_data_directory_migrates_legacy_analysis(tmp_path):
    media = tmp_path / "song.mp4"
    legacy_dir = tmp_path / ".chordy"
    legacy_dir.mkdir()
    (legacy_dir / "song.json").write_text('{"user_data": {"transpose": 2}}')

    file_repr = FileRepr(str(media), create=True)

    assert file_repr.json_path == str(tmp_path / ".chordflask" / "song.json")
    assert Path(file_repr.json_path).read_text() == '{"user_data": {"transpose": 2}}'
    assert not legacy_dir.exists()


def test_default_data_directory_reads_legacy_analysis_without_mutating(tmp_path):
    media = tmp_path / "song.mp4"
    legacy_dir = tmp_path / ".chordy"
    legacy_dir.mkdir()

    file_repr = FileRepr(str(media))

    assert file_repr.json_path == str(legacy_dir / "song.json")
    assert legacy_dir.is_dir()
