# ChordFlask

ChordFlask is for exploring your own music collection — audio and video — with
chords. It browses and plays local MP3, MP4, and WebM files, analyzes chords and
beats, and follows the result during browser playback. Completed analyses stay
beside the collection and are reused in later sessions.

Analysis runs locally and media files are not uploaded. Automatic chord
recognition is a practical starting point for orientation and practice, not a
guaranteed transcription; dense mixes and unusual harmony can produce wrong
chords.

![ChordFlask example screenshot](docs/example-screenshot.png)

## What you can do

ChordFlask is designed for exploring a music collection and playing along with whatever catches your interest. Browse your own audio and video directories, open a song, and let ChordFlask analyze it when you need it. You do not have to prepare the whole collection first: analyze one song spontaneously, queue several from the browser, or prepare an entire directory from the command line. Completed analyses stay with the collection and are reused the next time you return.

During playback, the detected chords and beats follow the song in the browser. This makes it easy to pick up an instrument, improvise, or work out a part without first searching for a separate chord sheet. Transpose the displayed chords, set an A/B loop around a difficult passage, or correct individual chords while keeping the original analyzer result available.

Automatic chord recognition is not a perfect transcription, especially with dense arrangements or unusual harmony. It is intended as a practical starting point for playing, orientation, and improvisation. When the analysis is close but not quite right, you can correct it beat by beat instead of starting over.

Optional workflows extend this further. Add synchronized lyrics from local LRC files, embedded lyrics, or LRCLIB; prepare Demucs stems to mute vocals or instruments for practice; and export analyses as Markdown, PDF, or ChordPro. The normal standalone bundle covers the interactive playback and analysis workflow, while additional preparation tools are available from a source installation through the command-line utilities.

<!-- standalone-download:start -->
## Download

A prebuilt Linux x86_64 bundle is available for users who do not want to
build ChordFlask themselves:

**[Download chordflask-mint22-x86_64-py3.12-v0.9.16.tar.gz](https://github.com/bkl2000/chordflask/releases/download/v0.9.16/chordflask-mint22-x86_64-py3.12-v0.9.16.tar.gz)**

The Mint 22 build is also suitable for Ubuntu 24.04, since Linux Mint 22 is based on Ubuntu 24.04.

Built from the same ChordFlask release source as the public release. FFmpeg and
Vamp plugin binaries are not bundled; see the portable bundle guide for
requirements.
<!-- standalone-download:end -->

The bundle targets Linux x86_64 in the supported Ubuntu, Mint, and Debian
family. FFmpeg and the Vamp plugins remain external requirements. See the
[standalone bundle guide](docs/STANDALONE.md) for installation, included and
excluded features, and glibc compatibility.

## Quick start

### Standalone bundle

Download the archive above, then run:

```bash
tar -xzf <release-archive>
cd <standalone-dir>
./install_vamp.sh
./chordflask.sh
```

Open <http://localhost:5000>. Stop the server with `Ctrl+C`. FFmpeg must be
installed on the host; the complete procedure is in
[docs/STANDALONE.md](docs/STANDALONE.md).

### From source

Install the system packages on Debian, Ubuntu, Mint, or WSL2:

```bash
sudo apt update
sudo apt install --no-install-recommends \
  git curl ffmpeg pkg-config vamp-plugin-sdk python3-venv python3-dev \
  build-essential libasound2-dev libcairo2-dev
```

Then install and start ChordFlask:

```bash
git clone https://github.com/bkl2000/chordflask.git
cd chordflask
make setup-runtime
make plugins
scripts/chordflask
```

Open <http://localhost:5000>. The setup uses `~/.venvs/chordflask`; you do not need to
activate that environment for normal use. Stop the server with `Ctrl+C`.

## First use

1. Select **Roots**, then open a directory containing MP3, MP4, or WebM files.
2. Select a file. MP3 uses the compact audio player; MP4 and WebM use the video
   player.
3. If analysis is missing, ChordFlask queues it automatically. The status above
   the grid shows whether it is waiting, running, ready, or failed.
4. Start playback after the analysis finishes. The chord grid then follows the
   current playback position.
5. Use **Previous** and **Next** to move through the visible, filtered file list.
   **Repeat** repeats the current file; **Auto** starts the next file when the
   current one ends.
6. Use **Transpose** to shift displayed chord names without changing the audio
   or stored result.
7. Press **A** at the start and **B** at the end of a difficult passage, then
   use **⟳** to repeat that loop. Loop, Repeat, and Auto are mutually exclusive.
8. To prepare more files, set **Next** to a batch size and select **Analyze**.
   ChordFlask queues that many unanalysed files from the current filtered and
   sorted list. Files already analyzed or queued do not consume the limit.
9. To correct a chord, pause playback, select **Edit**, choose a beat, and enter
   or select the replacement chord. ChordFlask switches to the **Edited** track.
   **Undo** reverses the latest edit; **Reset** discards the Edited version and
   returns to the original analysis.

Previously analyzed songs are loaded from the collection's `.chordflask`
directory. The original analyzer tracks remain intact when an Edited version
is created.

![ChordFlask file browser and analysis view](docs/example-screenshot-2.png)

See [Analysis, tracks, editing and export](docs/ANALYSIS.md) for the complete
playback, queue, track, and persistence behavior.

## Typical workflows

### Play along with a song

1. Open the song and wait for its first analysis if necessary.
2. Start playback and follow the chord grid.
3. Use **Transpose** if a different displayed key is easier to play.
4. Set **A** and **B** around a difficult section and repeat it with **⟳**.
5. Pause and use **Edit** if a detected chord needs correction.

### Prepare an album or directory

In the browser, open the directory, choose a value for **Next**, and select
**Analyze**. For a command-line batch, run:

```bash
chordflask-analyze ~/Music/Album
```

From a source checkout, use the repository launcher:

```bash
scripts/chordflask-analyze ~/Music/Album
```

Directory processing is non-recursive. Existing valid analyses are reused.
Preview the work or deliberately replace the Chordino analysis with:

```bash
chordflask-analyze --dry-run ~/Music/Album
chordflask-analyze --replace song.mp3
```

`--replace` preserves unrelated tracks and user data. See
[docs/ANALYSIS.md](docs/ANALYSIS.md) for lifecycle, batch, replacement, and
recovery details.

### Add synchronized lyrics

`chordflask-genlyrics` requires a valid existing analysis. By default it tries
a same-stem `.lrc`, then embedded lyrics, then LRCLIB:

```bash
chordflask-analyze song.mp3
chordflask-genlyrics song.mp3
chordflask
```

Open the song and select **Grid | Lyrics**. To process a directory or add
experimental Thai romanization:

```bash
chordflask-genlyrics ~/Music/Album
chordflask-genlyrics --romanize song.mp3
```

Desktop Lyrics displays the original line with romanization beneath it:

```text
ฉันรักเธอ แต่เธอไม่รู้
chan rak thoe tae thoe mai ru
```

The original text stays canonical. Romanization is an additional reading aid
on the same timeline, not a separate transcription. Lyrics and chord markers
are joined to the existing chord/beat timeline; an instrumental gap can remain
unhighlighted.

The generator is part of source installations. A standalone bundle can display
an existing `.cho`, including stored romanization, but does not generate or
fetch lyrics. Source priority, embedded-tag limits, LRCLIB matching, all CLI
options, alignment, romanization engines, and copyright considerations are in
[docs/LYRICS.md](docs/LYRICS.md).

### Prepare karaoke or instrument practice

Install the optional Demucs runtime once, check it, and prepare a directory:

```bash
make setup-demucs
make demucs-check
chordflask-demucs ~/Music
```

Then start ChordFlask normally and open a prepared song. Use **STEMS** to switch
to separated playback, mute **Vocals** for karaoke, mute **Bass** for bass
practice, or set the volume of Drums, Bass, Vocals, and Other individually.
Already prepared stem sets are reused.

See [docs/DEMUCS.md](docs/DEMUCS.md) for CPU/CUDA setup, preparation status,
storage, browser behavior, and limitations.

### Export a leadsheet

```bash
chordflask-export song.mp3
chordflask-export --format pdf song.mp3
chordflask-export --format markdown song.mp3
chordflask-export --format chordpro song.mp3
```

- Markdown is an editable leadsheet representation.
- PDF is a printable A4 layout.
- ChordPro is a reusable chord-grid file without lyrics.

The browser **Save** control downloads the current display as a ZIP. Export
options, track selection, naming, and storage locations are documented in
[docs/ANALYSIS.md](docs/ANALYSIS.md#command-line-export).

## Command-line tools

| Command | Purpose |
| --- | --- |
| `chordflask` | Interactive player |
| `chordflask-analyze` | Generate chord/beat analysis |
| `chordflask-demucs` | Generate optional stems |
| `chordflask-export` | Export analysis data |
| `chordflask-genlyrics` | Generate lyric/chord sidecars |
| `chordflask-maintain` | Diagnose and maintain generated data |

Typical calls:

```bash
chordflask-analyze song.mp3
chordflask-analyze ~/Music
chordflask-genlyrics song.mp3
chordflask-export --format pdf song.mp3
chordflask-maintain doctor
```

In a source checkout, prefix the command with `scripts/`, for example
`scripts/chordflask-analyze`. Installed launchers work from any current working
directory. See [docs/HELPERS.md](docs/HELPERS.md) for command ownership and
[docs/ANALYSIS.md](docs/ANALYSIS.md) for analysis and export options.

## Optional features

### Automatic beat-grid correction

Automatic beat-grid correction is disabled by default. It conservatively
replaces small timing variations only when a detected sequence is consistent
with an approximately constant tempo. The original detected rhythm track is
preserved whenever a correction is accepted.

For new analysis requests:

```bash
CHORDFLASK_AUTO_CORRECT_BEAT_GRID=1 chordflask
```

From a source checkout, or to reanalyze an existing song:

```bash
CHORDFLASK_AUTO_CORRECT_BEAT_GRID=1 scripts/chordflask
CHORDFLASK_AUTO_CORRECT_BEAT_GRID=1 \
  scripts/chordflask-analyze --replace song.mp3
```

Existing analysis files are not changed merely by enabling the option. The
exact acceptance criteria, diagnostic fields, preserved tracks, limitations,
and distinction from forced `quantize_beats` are in
[docs/ANALYSIS.md](docs/ANALYSIS.md#optional-automatic-beat-grid-correction).

### BTC analyzer

Chordino remains the default. BTC is an optional pretrained analyzer that adds
a separate `btc` chord track; it does not replace the existing Chordino result.
Its isolated runtime can use CPU or a compatible CUDA setup.

```bash
make setup-btc BTC_ACKNOWLEDGE_WEIGHTS=1
make btc-check
chordflask-analyze --analyzer btc song.mp3
```

Select the resulting BTC track in the browser. The required weights
acknowledgement, runtime matrix, Python/PyTorch/CUDA details, limitations, and
standalone status are in the
[BTC runtime documentation](chordflask_btc/model/README.md).

## LAN, phone, and tablet use

To listen on a trusted LAN and restrict browsing to one media directory:

```bash
chordflask --listen 0.0.0.0 --roots "/home/user/Music"
```

Then open `http://<host-ip>:5000` on the other device. Responsive layouts for
desktop, tablet and smartphone are included. Mobile support is functional but
still undergoing broader real-device testing. Narrow layouts remain Grid-only
and do not show Lyrics or romanization. Multi-stream stem playback is most
reliable in desktop Chromium; see
[docs/DEMUCS.md](docs/DEMUCS.md#known-limitations).

ChordFlask has no authentication or TLS. Use LAN listening only on a trusted
network. `--roots` limits which media directories the server exposes.

## Troubleshooting

### General diagnosis

```bash
chordflask-maintain doctor
```

The command checks the core Python environment, FFmpeg, required Vamp plugins,
and application-state directory without modifying data.

### FFmpeg is missing

```bash
sudo apt install ffmpeg
```

Restart ChordFlask afterward.

### Vamp plugins are missing

From a source checkout:

```bash
make plugins
```

From an unpacked standalone bundle:

```bash
./install_vamp.sh
```

### Port 5000 is already in use

```bash
chordflask --port 5050
```

Then open <http://localhost:5050>.

### No files appear

Check that the selected Root contains files ending in `.mp3`, `.mp4`, or
`.webm`, and that `--roots` permits the directory.

### Analysis cannot write files

The user running ChordFlask needs write permission in the media directory so
ChordFlask can create `.chordflask`. Source media are not modified.

### A standalone reports a `GLIBC_*` error

The bundle was built against a newer glibc than the target provides. Use a
bundle built on an older compatible distribution or build on a system matching
the target. See [docs/STANDALONE.md](docs/STANDALONE.md#compatibility-and-glibc)
and [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).

Storage reports, validation, migration, cleanup, and repair-oriented workflows
are in [docs/MAINTENANCE.md](docs/MAINTENANCE.md).

## Security

The default listener is localhost. ChordFlask has no authentication or TLS, so
only expose it on a trusted LAN and always constrain network access with
`--roots`:

```bash
chordflask --listen 0.0.0.0 --roots "/home/user/Music"
```

See [SECURITY.md](SECURITY.md) for the trust model and filesystem boundaries.

## Build a standalone bundle

This is an advanced workflow for producing a transferable Linux x86_64 bundle:

```bash
make setup
make standalone
```

Build naming, compatibility, external dependencies, transfer, and diagnostics
are documented in [docs/STANDALONE.md](docs/STANDALONE.md).

## More documentation

- [Analysis, tracks, editing, beat-grid correction, and export](docs/ANALYSIS.md)
- [Lyrics, LRC, embedded lyrics, LRCLIB, and romanization](docs/LYRICS.md)
- [Demucs stems and practice workflows](docs/DEMUCS.md)
- [Maintenance and storage](docs/MAINTENANCE.md)
- [Standalone bundle](docs/STANDALONE.md)
- [Platform and Python compatibility](docs/COMPATIBILITY.md)
- [Vamp plugins](docs/VAMP.md)
- [Architecture and developer map](docs/ARCHITECTURE.md)
- [Supported command-line helpers](docs/HELPERS.md)
- [Development and tests](CONTRIBUTING.md)

## Development transparency

ChordFlask has been and continues to be developed through a maintainer-led,
AI-assisted "vibe coding" workflow. The maintainer defines, leads, and reviews
all changes and retains the testing and release decisions. AI coding tools
assist with development but are not authors, maintainers, partners, or
endorsers of the project.

## License

ChordFlask-owned source is available under the MIT License. FFmpeg, Vamp
plugins, and Python dependencies retain their own licenses. See
[LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

ChordFlask is independent of and not endorsed by the Pallets project, which
maintains Flask.
