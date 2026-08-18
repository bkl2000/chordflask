import json
import subprocess
import wave

import pytest

from chordflask_demucs import audio


def test_probe_audio_preserves_original_stream_timeline(monkeypatch, tmp_path):
    media = tmp_path / "song.mp4"
    media.write_bytes(b"media")
    payload = {
        "streams": [
            {
                "index": 1,
                "codec_name": "aac",
                "start_time": "-0.02322",
                "start_pts": "-1024",
                "time_base": "1/44100",
                "duration": "1.0",
                "duration_ts": "44100",
                "sample_rate": "44100",
                "channels": 2,
            }
        ],
        "format": {"format_name": "mov,mp4", "start_time": "0.0", "duration": "1.0"},
    }
    monkeypatch.setattr(audio, "executable", lambda name: name)
    monkeypatch.setattr(
        audio,
        "_run",
        lambda command, timeout: subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(payload), stderr=""
        ),
    )

    facts = audio.probe_audio(media)
    timeline = audio.probe_source_timeline(media)

    assert facts.sample_count == 44100
    assert facts.start_time == -0.02322
    assert facts.start_pts == -1024
    assert facts.time_base == "1/44100"
    assert timeline == {
        "available": True,
        "audio_stream_index": 1,
        "start_time": -0.02322,
        "start_pts": -1024,
        "time_base": "1/44100",
        "container_start_time": 0.0,
    }


def test_probe_canonical_wav_reads_exact_frame_count(tmp_path):
    path = tmp_path / "source.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(44100)
        handle.writeframes(b"\0\0\0\0" * 441)

    facts = audio.probe_canonical_wav(path)

    assert facts.sample_rate == 44100
    assert facts.channels == 2
    assert facts.sample_count == 441
    assert facts.duration == pytest.approx(0.01)


def test_extract_audio_uses_first_audio_stream_and_fixed_dimensions(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(audio, "executable", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(
        audio,
        "_run",
        lambda command, timeout: (
            calls.append((command, timeout)) or subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        ),
    )

    audio.extract_canonical_audio(tmp_path / "song.mp4", tmp_path / "source.wav")

    command, timeout = calls[0]
    assert "-map" in command
    assert command[command.index("-map") + 1] == "0:a:0"
    assert command[command.index("-ar") + 1] == "44100"
    assert command[command.index("-ac") + 1] == "2"
    assert timeout == 600


def test_convert_to_flac_has_bounded_tail_normalization(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(audio, "executable", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(
        audio,
        "_run",
        lambda command, timeout: (
            calls.append((command, timeout)) or subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        ),
    )

    audio.convert_wav_to_flac(
        tmp_path / "vocals.wav",
        tmp_path / "vocals.flac",
        target_sample_count=88200,
    )

    command, _ = calls[0]
    assert "apad=whole_len=88200,atrim=end_sample=88200" in command
    assert command[command.index("-c:a") + 1] == "flac"
    assert command[command.index("-sample_fmt") + 1] == "s16"
