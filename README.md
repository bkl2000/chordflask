# ChordFlask

ChordFlask analyzes chords and beats in MP4/WebM files and shows them alongside
browser playback. It runs locally; media and analysis data are not uploaded.

ChordFlask supports Linux x86_64 on Ubuntu 24.04+, Linux Mint 22+, and Debian
13+. CPython 3.12 is the release-tested Python version. GitHub releases contain
source code only, not a ready-made executable.

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

1. Enter the absolute path to a directory containing MP4 or WebM files.
2. Select **Load**, then select a file from the list.
3. ChordFlask queues missing analysis automatically. The status above the chord
   grid shows whether analysis is running, waiting, or failed.
4. Use **Previous**, **Next**, **Repeat**, **Continue**, and **Transpose** while
   playing the file.

Generated JSON, MusicXML, MIDI, and temporary audio are stored in a
`.chordflask` directory beside the media. Your user therefore needs write
permission for the media directory. Existing media files are not modified.

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
  in `.mp4` or `.webm`.
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
