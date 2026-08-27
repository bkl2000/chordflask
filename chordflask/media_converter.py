import os
import tempfile
from pathlib import Path

from moviepy.video.io.VideoFileClip import VideoFileClip

from .ffmpeg_runtime import require_system_ffmpeg


class MediaConverter:
    def ensure_mp3(self, file_repr):
        source_path = file_repr.get()
        if Path(source_path).suffix.lower() == ".mp3":
            return source_path

        if os.path.exists(file_repr.get("mp3")):
            print(f"MP3 file already exists: {file_repr.get('mp3')}")
            return file_repr.get("mp3")

        require_system_ffmpeg()
        destination = Path(file_repr.get("mp3"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.stem}.convert-",
            suffix=destination.suffix,
            dir=destination.parent,
        )
        os.close(descriptor)
        os.unlink(temporary_name)
        try:
            with VideoFileClip(source_path) as video:
                if video.audio is None:
                    raise ValueError(f"Media file has no audio stream: {file_repr.get()}")
                video.audio.write_audiofile(temporary_name)
            os.replace(temporary_name, destination)
            temporary_name = None
        finally:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass
        print(f"MP3 file saved: {destination}")
        return str(destination)
