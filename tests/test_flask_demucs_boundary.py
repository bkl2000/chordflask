import os
import subprocess
import sys
import textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

# The lightweight chordflask_demucs producer is intentionally importable from
# the application (and bundled in the standalone); the heavy third-party
# runtime must never be imported by the Flask process.
HEAVY_RUNTIME_TOKENS = (
    "import torch",
    "import torchaudio",
    "import torchcodec",
    "import demucs",
    "from demucs",
    "demucs.separate",
)


def test_flask_python_sources_do_not_import_heavy_runtime():
    offenders = []
    for path in (REPO_ROOT / "chordflask").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in HEAVY_RUNTIME_TOKENS:
            if token in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {token}")
    assert offenders == []


def test_flask_app_import_is_producer_lazy():
    script = textwrap.dedent(
        """
        import importlib.abc
        import sys

        class BlockHeavy(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname in {"torch", "demucs"} or fullname.startswith(("torch.", "demucs.")):
                    raise ModuleNotFoundError("blocked heavy runtime")
                return None

        sys.meta_path.insert(0, BlockHeavy())
        from chordflask.app import FlaskMP4App

        leaked = [
            name for name in ("torch", "demucs", "chordflask_demucs")
            if name in sys.modules
        ]
        assert leaked == [], leaked
        assert FlaskMP4App is not None
        """
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_flask_loads_plain_and_audio_track_v3_json_without_demucs_import(tmp_path):
    script = textwrap.dedent(
        """
        import importlib.abc
        import os
        import tempfile
        from pathlib import Path
        import sys

        class BlockDemucs(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "chordflask_demucs" or fullname.startswith("chordflask_demucs."):
                    raise ModuleNotFoundError("blocked optional Demucs package")
                return None

        sys.meta_path.insert(0, BlockDemucs())
        from chordflask.app import FlaskMP4App
        from chordflask_base import ChordData

        def audio_set():
            tracks = {}
            for index, stem in enumerate(("bass", "drums", "other", "vocals")):
                tracks[stem] = {
                    "path": f".chordflask/stems/demucs/htdemucs/song/generation/{stem}.flac",
                    "format": "flac",
                    "sample_rate": 44100,
                    "channels": 2,
                    "sample_count": 44100,
                    "duration": 1.0,
                    "size": index + 1,
                    "sha256": f"{index + 1:064x}",
                }
            return {
                "provider": "demucs",
                "model": "htdemucs",
                "tracks": tracks,
                "metadata": {
                    "source": {
                        "sha256": "a" * 64,
                        "size": 1,
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

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, with_audio in (("plain.mp3", False), ("with-audio.mp3", True)):
                media = root / name
                media.write_bytes(b"not decoded by this route")
                analysis_dir = root / ".chordflask"
                analysis_dir.mkdir(exist_ok=True)
                data = ChordData()
                if with_audio:
                    data.set_audio_track("demucs:htdemucs", audio_set())
                data.save_to_file(analysis_dir / f"{media.stem}.json")

            os.environ["CHORDFLASK_QUEUE_DIR"] = str(root / "queue")
            app = FlaskMP4App()
            client = app.app.test_client()
            for name in ("plain.mp3", "with-audio.mp3"):
                response = client.post(
                    "/load_file",
                    json={"dirname": str(root), "filename": name},
                )
                assert response.status_code == 200, response.get_data(as_text=True)
                assert response.get_json()["status"] == "ready"
        """
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
