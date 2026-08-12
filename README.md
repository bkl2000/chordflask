# ChordFlask

ChordFlask extracts chords and beat timing from MP4/WebM media and displays
them during browser playback. It is an independent project and is not
affiliated with or endorsed by the Pallets project, which maintains Flask.

## Requirements

ChordFlask currently targets Linux x86_64 with CPython 3.12. Install the
required system tools on Ubuntu, Linux Mint, or Debian:

```bash
sudo apt install ffmpeg pkg-config vamp-plugin-sdk python3-venv python3-dev build-essential libasound2-dev libcairo2-dev
```

The supported platform family is Ubuntu 24.04 or newer, Linux Mint 22 or newer
in the corresponding Ubuntu generation, and Debian 13 or newer. CPython 3.12
is the release-validated Python version. See `docs/COMPATIBILITY.md` for the
compatibility policy and the additional checks required before claiming a new
distribution or Python version as supported.

FFmpeg and these Vamp plugins are external runtime requirements and are not
included in the source release:

- `nnls-chroma:chordino` for chord extraction
- `qm-vamp-plugins:qm-barbeattracker` for beat and downbeat tracking

## Installation

Create the standard virtual environment and install the Python dependencies:

```bash
make setup
source ~/.venvs/chordifier/bin/activate
```

Install the pinned Vamp plugins into `~/.vamp`:

```bash
scripts/install_vamp_plugins.sh
```

The installer verifies the downloaded archives and can install into another
user-writable directory with `--dest`. Set `VAMP_PATH` to that directory before
starting ChordFlask. See `docs/VAMP.md` for versions, checksums, and discovery
details.

Runtime dependencies are listed in `requirements-core.txt`; developer/test and
local standalone-build dependencies are separated into `requirements-dev.txt`
and `requirements-build.txt`. CPython 3.12 uses the reviewed constraints in
`constraints-python312.txt`. Optional audio-playback dependencies can be
installed with:

```bash
CHORDIFIER_OPTIONAL=1 make setup
```

The legacy `madmom` analysis path is optional and is not part of the standard
CPython 3.12 setup.

## Running ChordFlask

Start the web application and its automatically managed analysis worker:

```bash
make run
```

Open `http://localhost:5000`. ChordFlask listens on `127.0.0.1` by default.

The file browser loads MP4 and WebM files. When a file has no analysis yet,
ChordFlask queues it without interrupting current playback. The worker analyzes
one file at a time and stores generated JSON, MusicXML, MIDI, and intermediate
audio in a media-side `.chordflask` directory. The chord header reports whether
analysis is running, waiting, failed, or unavailable because no worker is
active.

With `Continue On`, an unanalyzed next song waits at the end of the current
song and starts automatically when its analysis succeeds. A failure stops
automatic continuation and remains visible in the chord header. The small `↻`
control queues a fresh Chordino/QM analysis of the loaded file while playback
and browsing remain available.

For deliberately separate process management:

```bash
cd flask
python3 chordflask.py --worker
python3 chordflask.py --no-worker
```

The compatibility launcher `scripts/chordflask.sh` starts the normal managed
worker configuration.

## Local security boundary

ChordFlask is a local-first trusted-user application. It has no authentication,
TLS, or CSRF protection. Do not expose it to an untrusted network or the public
internet.

Trusted-LAN use requires an explicit non-loopback listener and one or more
allowed media roots:

```bash
CHORDIFIER_LISTEN=0.0.0.0 \
CHORDIFIER_MEDIA_ROOTS=/path/to/videos:/another/media/root \
make run
```

LAN startup is rejected without configured media roots. On supported Linux
systems the root list uses `:` as its separator. See `SECURITY.md` for the full
deployment boundary and vulnerability-reporting process.

## Analysis tracks and schema v3

ChordFlask stores independent named analysis tracks per media file:

- Chord tracks contain timestamped chord labels. Built-in analysis produces a
  `chordino` track; the optional `madmom` path can provide another track.
- Rhythm tracks contain tempo, meter, beats, and downbeats. Built-in analysis
  produces `qm_barbeattracker`.
- Beat-to-chord alignment is derived from the active chord/rhythm combination
  and is not persisted.
- Track selectors appear in the chord header when multiple choices exist and
  rebuild the grid without reloading the video.
- Schema v1, v2, and unversioned files remain readable; the next normal save
  writes schema v3.

Reanalysis validates a replacement in an isolated directory, preserves
`user_data`, display preferences, and unrelated tracks, then atomically
replaces the JSON only after success. Optional MusicXML and MIDI replacements
are best effort and do not delete a working older file when generation fails.

ChordFlask has no PyTorch dependency or inference model.

## Metric-aware chords

The browser uses rhythm-aware chord display by default. On a sufficiently
regular beat grid it removes only short isolated `A-B-A` detections on weak
beats. This affects display only: raw timestamps, analysis JSON, and exports do
not change.

Use nearest-beat display instead with:

```bash
python3 flask/chordflask.py --no-metric-chords
```

The former explicit `--metric-chords` option remains accepted. A read-only
diagnostic shows rhythm classification and each displayed beat that differs:

```bash
python3 scripts/metric_chords_diff.py path/to/chords.json
```

The chord grid repeats held chords at each two-measure row boundary. Video,
grid, and controls share the available viewport proportionally so the layout
remains usable across different window sizes.

## Development and tests

Run `make` without arguments to list the project commands. The usual workflows
are:

```bash
make setup
make check
make run
```

`make check` runs pytest, Ruff, Python compilation, and `git diff --check`.
Tests cover the Flask API, schema compatibility, queue/worker behavior,
analysis boundaries, playback mapping, and setup scripts. Real FFmpeg and Vamp
checks are available when those external tools are installed.

## Local standalone build

A local Linux x86_64 standalone executable can be built with:

```bash
make standalone
make standalone-run
```

The build deliberately excludes FFmpeg and Vamp plugin binaries. Target
machines must provide system FFmpeg and install the required plugins into
`~/.vamp` or a directory named by `VAMP_PATH`. The v0.5.0 GitHub release is
source-only and does not attach a standalone binary.

## License

ChordFlask-owned source is available under the MIT License. FFmpeg, Vamp
plugins, and Python dependencies retain their own licenses. See `LICENSE` and
`THIRD_PARTY_NOTICES.md`.
