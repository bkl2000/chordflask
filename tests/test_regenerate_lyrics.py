import os
from pathlib import Path
import subprocess


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/regenerate-lyrics.sh"


def test_recursively_regenerates_existing_sidecars_and_reports_counts(tmp_path):
    library = tmp_path / "Music"
    nested = library / "Album"
    nested.mkdir(parents=True)
    (library / "good.cho").write_text("old")
    (library / "good.mp3").write_bytes(b"")
    (nested / "bad.cho").write_text("old")
    (nested / "bad.MP4").write_bytes(b"")
    (nested / "orphan.cho").write_text("old")
    (nested / "media-only.webm").write_bytes(b"")

    calls = tmp_path / "calls"
    generator = tmp_path / "chordflask-genlyrics"
    generator.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\0' \"$@\" >> \"$CALLS\"\n"
        "[[ \"${!#}\" != *.MP4 ]]\n"
    )
    generator.chmod(0o755)
    env = {
        **os.environ,
        "CHORDFLASK_GENLYRICS": str(generator),
        "CALLS": str(calls),
    }

    result = subprocess.run(
        [str(SCRIPT), str(library)],
        text=True,
        capture_output=True,
        env=env,
    )

    assert result.returncode == 1
    assert "SKIP: no same-stem media" in result.stdout
    assert "Summary: found=3 regenerated=1 skipped=1 failed=1" in result.stdout
    assert "FAIL:" in result.stderr
    arguments = calls.read_bytes().decode().split("\0")[:-1]
    assert arguments == [
        "--force", "--lyrics", "lrclib:lrc:embedded", str(library / "good.mp3"),
        "--force", "--lyrics", "lrclib:lrc:embedded", str(nested / "bad.MP4"),
    ]
