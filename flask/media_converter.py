import os

from moviepy.video.io.VideoFileClip import VideoFileClip

from ffmpeg_runtime import require_system_ffmpeg


class MediaConverter:
    def ensure_mp3(self, file_repr):
        if os.path.exists(file_repr.get("mp3")):
            print(f"MP3 file already exists: {file_repr.get('mp3')}")
            return file_repr.get("mp3")

        require_system_ffmpeg()
        with VideoFileClip(file_repr.get()) as video:
            if video.audio is None:
                raise ValueError(f"Media file has no audio stream: {file_repr.get()}")
            video.audio.write_audiofile(file_repr.get("mp3"))
        print(f"MP3 file saved: {file_repr.get('mp3')}")
        return file_repr.get("mp3")
