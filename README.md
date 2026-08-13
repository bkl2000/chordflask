# ChordFlask

ChordFlask analyzes chords and beats in MP3 audio and MP4/WebM video files and
shows them alongside browser playback. MP3 files play in the built-in audio
player and are analyzed directly without video conversion. Everything runs
locally; media and analysis data are not uploaded.

ChordFlask supports Linux x86_64 on Ubuntu 24.04+, Linux Mint 22+, and Debian
13+. CPython 3.12 is the release-tested Python version. GitHub releases contain
source code only, not a ready-made executable.

## Motivation

ChordFlask is a small local-first tool for working with a music collection you
already have. Its emphasis is the workflow around chord analysis rather than a
claim of uniquely accurate recognition: browse a directory, play any file, and
generate reusable chord data only when it is useful.

This local, on-demand workflow is the main reason ChordFlask exists:

- prepare selected parts of a collection in bounded background batches;
- keep each completed analysis beside the media for later sessions;
- continue browsing and playing while other files are analyzed;
- transpose, respell, compare, and correct the displayed chords; and
- download the accepted beat-level result as Markdown.

Automatic chord transcription is approximate, especially with dense mixes or
unusual harmony. The current Chordino-based result is intended as a useful
starting point for orientation and practice, not as an authoritative score.
When the result is close enough, this workflow can avoid repeated manual setup.
When it is not, the original remains intact while an Edited version can be
corrected beat by beat.

## Quick start from source

This is the recommended installation method. Install the system packages:

```bash
sudo apt update
sudo apt install --no-install-recommends \
  git curl ffmpeg pkg-config vamp-plugin-sdk python3-venv python3-dev \
  build-essential libasound2-dev libcairo2-dev
```

Download ChordFlask, create its private Python environment, install the two
required audio-analysis plugins, and start it:

```bash
git clone https://github.com/bkl2000/chordflask.git
cd chordflask
make setup-runtime
make plugins
make run
```

Open <http://localhost:5000>. Stop ChordFlask with `Ctrl+C` in the terminal.
The Make targets use `~/.venvs/chordifier` automatically; you do not need to
activate that environment.

## First use

1. Select **Browse** and navigate to a directory containing MP3, MP4, or WebM
   files. You can still enter an absolute path directly.
2. Select a file from the list. MP3 files use the compact audio player; videos
   use the video player.
3. ChordFlask queues missing analysis automatically. The status above the chord
   grid shows whether analysis is running, waiting, or failed.
4. To prepare several files, set **Next** to the desired batch size (50 by
   default) and select **Queue next**. Each click adds that many new,
   unanalysed files from the currently filtered and sorted list; files already
   analysed or queued do not consume the limit.
5. Use **Previous**, **Next**, **Repeat**, **Continue**, and **Transpose** while
   playing the file.

Generated JSON, MusicXML, MIDI, and temporary audio are stored in a
`.chordflask` directory beside the media. Your user therefore needs write
permission for the media directory. Existing media files are not modified.
The queue survives an application restart; interrupted work is returned to the
queue and incomplete temporary output is discarded on retry.

## Batch leadsheet export

A non-recursive helper turns every supported media file in a directory into a playable
Markdown leadsheet with title, tempo/meter metadata, the chord source, and
measure tables of eight measures per block. Existing analyses are reused;
missing files are analyzed serially only when needed, so a second run costs no
new analysis time.

```bash
~/.venvs/chordifier/bin/python flask/helpers/chordleadsheet_batch.py ~/Music
```

Each exported file lands beside its analysis as
`.chordflask/<name>-chords-<track>.md` and is updated atomically. Defaults are
the Edited version when present (otherwise Chordino), QM Bar/Beat Tracker
rhythm, no transpose, Flats spelling, ASCII symbols, repeated-chord `changes`
mode, and rhythm-aware smoothing. Examples:

```bash
# Sharps spelling and two semitones up
~/.venvs/chordifier/bin/python flask/helpers/chordleadsheet_batch.py ~/Music --sharps --transpose 2

# The unedited Chordino version with every beat written out
~/.venvs/chordifier/bin/python flask/helpers/chordleadsheet_batch.py ~/Music --chord-track original --repeat-mode chords
```

The browser **Save** button downloads the same leadsheet format for the single
file currently displayed, including its active track selection, spelling, and
transpose state.

## Build a portable Linux bundle

This advanced workflow builds ChordFlask on your machine for use on a compatible
Linux x86_64 machine. It is not required for normal use.

```bash
make setup
make standalone
```

The transferable archive is:

```text
flask/dist/chordflask-linux-x86_64.tar.gz
```

Test the unpackaged build locally with `make standalone-run`. The archive does
not contain FFmpeg or Vamp plugin binaries. After copying it to the target
machine, follow [the complete standalone guide](docs/STANDALONE.md). The same
guide is included as `README.md` inside the archive.

## Troubleshooting

- **`ffmpeg` was not found:** run `sudo apt install ffmpeg` and restart.
- **Vamp plugins are missing:** run `make plugins` from the source directory and
  restart. In an unpacked portable bundle, run `./install_vamp.sh` instead.
- **No files appear:** load an existing directory and check that its files end
  in `.mp3`, `.mp4`, or `.webm`.
- **Analysis cannot write files:** give your user write permission for the media
  directory so ChordFlask can create `.chordflask`.
- **Port 5000 is busy:** start with `CHORDIFIER_PORT=5050 make run` and open
  <http://localhost:5050>.

## Security

ChordFlask has no authentication, TLS, or CSRF protection. Keep the default
`127.0.0.1` listener unless every device on the network is trusted. Read
[SECURITY.md](SECURITY.md) before enabling LAN access.

## More documentation

- [Playback, analysis tracks, and chord display](docs/ANALYSIS.md)
- [Supported command-line helpers](docs/HELPERS.md)
- [Vamp plugin installation and verification](docs/VAMP.md)
- [Portable bundle guide](docs/STANDALONE.md)
- [Platform and Python compatibility](docs/COMPATIBILITY.md)
- [Development and tests](CONTRIBUTING.md)

## License

ChordFlask-owned source is available under the MIT License. FFmpeg, Vamp
plugins, and Python dependencies retain their own licenses. See [LICENSE](LICENSE)
and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

ChordFlask is independent of and not endorsed by the Pallets project, which
maintains Flask.
