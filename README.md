# ChordFlask

ChordFlask analyzes the chords and beats in MP3, MP4, and WebM files and shows
them in sync while you play the song in the browser. The displayed chords can
be transposed, corrected, compared, and exported as Markdown or PDF. Everything
runs locally; media and analysis data are never uploaded.

ChordFlask supports Linux x86_64 on Ubuntu 24.04+, Linux Mint 22+, and Debian
13+ (CPython 3.12). Native Windows is not supported; Windows users can run
ChordFlask under WSL2 (tested) and open the local web interface from the
Windows browser at localhost.

<!-- standalone-download:start -->
## Download

A prebuilt Linux x86_64 bundle is available for users who do not want to
build ChordFlask themselves:

**[Download chordflask-mint22-x86_64-py3.12-v0.8.2.tar.gz](https://github.com/bkl2000/chordflask/releases/download/v0.8.2/chordflask-mint22-x86_64-py3.12-v0.8.2.tar.gz)**

Built from the same ChordFlask release source as the public release. FFmpeg and
Vamp plugin binaries are not bundled; see the portable bundle guide for
requirements.
<!-- standalone-download:end -->

## Quick start

This is the recommended installation method. On a fresh Debian 13 or WSL2
system the Python interpreter, compiler toolchain, and download tools are not
preinstalled, so install the system packages first:

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

Open <http://localhost:5000> and use **Browse** to select a directory with
MP3, MP4, or WebM files. Stop ChordFlask with `Ctrl+C` in the terminal.

The Make targets use `~/.venvs/chordflask` automatically; you do not need to
activate that environment. If a command fails, see
[Troubleshooting](#troubleshooting).

## Why ChordFlask

ChordFlask is a small local-first tool for working with a music collection you
already have. Its emphasis is the workflow around chord analysis rather than a
claim of uniquely accurate recognition: browse a directory, play any file, and
generate reusable chord data only when it is useful.

This local, on-demand workflow is the main reason ChordFlask exists:

- prepare selected parts of a collection in bounded background batches;
- keep each completed analysis beside the media for later sessions; and
- continue browsing and playing while other files are analyzed.

Automatic chord transcription is approximate, especially with dense mixes or
unusual harmony. The current Chordino-based result is intended as a useful
starting point for orientation and practice, not as an authoritative score.
When the result is close enough, this workflow can avoid repeated manual setup.
When it is not, the original remains intact while an Edited version can be
corrected beat by beat.

## Using ChordFlask

### Command-line tools

The commands below cover the main workflows. Chordino is the built-in, default
analyzer. The scripts are run from the repository root (they are not installed
on your `PATH`).

```bash
# Start the player / web app
scripts/chordflask.sh

# Analyze with the built-in Chordino analyzer
scripts/chordflask-analyze song.mp4
scripts/chordflask-analyze /music/videos

# Preview without changing anything, or replace an existing analysis
scripts/chordflask-analyze --dry-run /music/videos
scripts/chordflask-analyze --replace song.mp4

# Export leadsheets (Markdown and/or PDF)
scripts/chordflask-export song.mp4
scripts/chordflask-export --format markdown song.mp4
scripts/chordflask-export --format pdf song.mp4

# Maintenance
scripts/chordflask-maintain doctor
scripts/chordflask-maintain validate /music/videos
scripts/chordflask-maintain migrate-schema /music/videos
scripts/chordflask-maintain storage report /music/videos
```

Details are in [docs/ANALYSIS.md](docs/ANALYSIS.md) (analysis and export),
[docs/MAINTENANCE.md](docs/MAINTENANCE.md) (maintenance), and
[docs/HELPERS.md](docs/HELPERS.md) (the underlying helper modules).

### Optional BTC analyzer

Chordino is the built-in default analyzer. The optional BTC analyzer runs a
pretrained model in a separate environment and adds its result as an
additional `btc` chord track, without touching the Chordino track. Install and
use it explicitly:

```bash
make setup-btc BTC_ACKNOWLEDGE_WEIGHTS=1   # one-time: environment + model download
make btc-check                             # diagnose the runtime (CPU/CUDA, model)

scripts/chordflask-analyze --analyzer btc song.mp4
```

Chordino and BTC are stored as separate tracks; switch between them with the
track selector next to the chord grid. BTC never replaces Chordino and is not
part of the portable bundle.

### Optional Demucs stems / karaoke & practice

Demucs is an optional, separate runtime that splits a song into four parts —
**Vocals**, **Drums**, **Bass**, and **Other**. ChordFlask works normally
without it, and the normal app and portable bundle stay Demucs/Torch-free.

**Quick start**

```bash
# one-time optional environment setup
make setup-demucs
make demucs-check

# prepare every supported song in one directory (run once)
scripts/chordflask-demucs ~/Music
```

Then start ChordFlask normally and load one of the processed songs. ChordFlask
finds the generated stem data automatically and shows a small **STEMS**
control:

```text
[STEMS]  [Voc | 100] [Drm | 100] [Bass | 100] [Oth | 100]
```

- **STEMS** switches the player to separated audio. The original audio (and
  video) stays the master timeline; the four FLAC stems follow it.
- Click a stem name (**Voc** / **Drm** / **Bass** / **Oth**) to mute or unmute
  it. For example, muting **Voc** leaves a karaoke backing track; muting
  **Bass** is useful for bass practice.
- Click a percentage to open the single shared volume slider for that stem.
- Mixer state is kept while STEMS is switched OFF and ON again for the same
  song; loading a different song resets all four to 100%.

Demucs preparation is **not** run automatically by the player — you normally
run the preparation command once for a music directory. The generated FLAC
stems stay beside that collection under `.chordflask/` and are registered as
one `audio_tracks["demucs:htdemucs"]` (`htdemucs`) set with the four stems
`bass`, `drums`, `other`, and `vocals`; the player just finds and uses them.
Re-running the command reports `CURRENT` for songs that are already prepared
instead of separating them again.

```bash
scripts/chordflask-demucs --dry-run ~/Music   # preview without processing
scripts/chordflask-demucs --replace song.mp3  # regenerate one stale set
```

See [docs/DEMUCS.md](docs/DEMUCS.md) for the complete workflow, storage
layout, and limitations.


### First use

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
   playing the file. Press **A** and **B** to mark a loop segment and **⟳** to
   repeat it.

Responsive layouts for desktop, tablet and smartphone are included. Mobile
support is functional but still undergoing broader real-device testing.

To use ChordFlask from a phone or tablet on the same trusted LAN, start
ChordFlask on the host with an allowed media root and a LAN listener:

```bash
CHORDIFIER_MEDIA_ROOTS=/home/user/Music \
    chordflask --listen 0.0.0.0 --port 5000
```

Then open `http://<host-ip>:5000` on the other device. ChordFlask has no
authentication or TLS, so LAN access should only be enabled on a trusted
network. See [Security](#security) for the media-root restrictions.

Generated JSON, MusicXML, MIDI, cached audio, and optional Demucs FLAC stems are stored in a
`.chordflask` directory beside the media. Your user therefore needs write
permission for the media directory. Existing media files are not modified.

ChordFlask also keeps a small application-state directory, `~/.chordflask`, in
your home folder. It holds the analysis queue, worker lock, and log files — not
your analysis results. The queue survives an application restart; interrupted
work is returned to the queue and incomplete temporary output is discarded on
retry.

### Batch leadsheet export

The `chordflask-export` command turns one media file or every supported media
file in a directory into matching playable Markdown and print-ready A4 PDF
leadsheets. Existing analyses are reused; missing files are analyzed serially
only when needed, so a second run costs no new analysis time.

```bash
scripts/chordflask-export ~/Music
scripts/chordflask-export song.mp4
```

Both files land beside the analysis as `.chordflask/<name>-chords-<track>.md`
and `.pdf`. Defaults are the Edited version when present (otherwise Chordino),
no transpose, Flats spelling, and repeated-chord `changes` mode:

```bash
# Sharps spelling and two semitones up
scripts/chordflask-export ~/Music --sharps --transpose 2

# The unedited Chordino version with every beat written out
scripts/chordflask-export ~/Music --chord-track original --repeat-mode chords

# Write only one format
scripts/chordflask-export ~/Music --format markdown
scripts/chordflask-export ~/Music --format pdf
```

The browser **Save** button downloads one ZIP containing the matching `.md` and
`.pdf` for the single file currently displayed. Full format and option details
are in [docs/ANALYSIS.md](docs/ANALYSIS.md).

### Analysis storage and cleanup

Each analyzed directory owns an independent `.chordflask` subdirectory holding
its analysis JSON, cached audio, and exports. A read-only report shows how much
space one directory uses:

```bash
scripts/chordflask-maintain storage report /path/to/music
```

Cleanup is explicit and non-recursive, limited to one directory. For example,
remove cached audio that ChordFlask can regenerate from video sources:

```bash
scripts/chordflask-maintain storage cleanup /path/to/music --cached-audio
```

Cleanup can also remove orphaned temporary work and corrupt-analysis backups
(using an explicit retention age). Valid analysis JSON, source media, and
user-edited chords are never deleted. See [docs/ANALYSIS.md](docs/ANALYSIS.md)
for the complete storage description.

## Build a portable Linux bundle

A prebuilt bundle is available from [Download](#download) above. This advanced
workflow builds ChordFlask on your machine for use on a compatible Linux x86_64
machine. It is not required for normal use.

```bash
make setup
make standalone
```

The transferable archive is named after the build machine's distro, CPU
architecture, Python version, and ChordFlask version, for example:

```text
flask/dist/chordflask-debian13-x86_64-py3.12-v0.6.3.tar.gz
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
- **Inspect analysis storage:** run
  `scripts/chordflask-maintain storage report /path/to/music` (read-only) to
  see how much space one directory's local `.chordflask` uses.
- **Port 5000 is busy:** start with `CHORDIFIER_PORT=5050 make run` and open
  <http://localhost:5050>.

## Security

ChordFlask has no authentication, TLS, or CSRF protection. Keep the default
`127.0.0.1` listener unless every device on the network is trusted. Read
[SECURITY.md](SECURITY.md) before enabling LAN access.

A LAN listener requires at least one allowed media root. Use `--listen` to
select the bind address/interface and `--port` to select the TCP port:

```bash
CHORDIFIER_MEDIA_ROOTS=/home/user/Music \
    chordflask --listen 0.0.0.0 --port 5000
```

Separate multiple roots with the platform path separator (`:` on
Linux/macOS, `;` on Windows):

```bash
CHORDIFIER_MEDIA_ROOTS="/home/user/Music:/mnt/media/videos" \
    chordflask --listen 0.0.0.0 --port 5000
```

Only media below these roots is served on the network. The home directory or
the whole filesystem is not automatically exposed.

## More documentation

- [Playback, analysis tracks, and chord display](docs/ANALYSIS.md)
- [Maintenance commands](docs/MAINTENANCE.md)
- [Supported command-line helpers](docs/HELPERS.md)
- [Vamp plugin installation and verification](docs/VAMP.md)
- [Portable bundle guide](docs/STANDALONE.md)
- [Platform and Python compatibility](docs/COMPATIBILITY.md)
- [Optional Demucs stems and playback](docs/DEMUCS.md)
- [Development and tests](CONTRIBUTING.md)

## Development transparency

ChordFlask has been and continues to be developed through a maintainer-led,
AI-assisted "vibe coding" workflow. The maintainer defines, leads, and reviews
all changes and retains the testing and release decisions. AI coding tools
assist with development but are not authors, maintainers, partners, or
endorsers of the project.

## License

ChordFlask-owned source is available under the MIT License. FFmpeg, Vamp
plugins, and Python dependencies retain their own licenses. See [LICENSE](LICENSE)
and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

ChordFlask is independent of and not endorsed by the Pallets project, which
maintains Flask.
