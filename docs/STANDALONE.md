# Standalone bundle

ChordFlask's standalone bundle is useful when you want to build once and copy
the application to another compatible Linux x86_64 machine. A prebuilt
standalone bundle may be attached to a GitHub release, but you can also build it
yourself with the steps below.

The bundle contains ChordFlask and its Python runtime. It deliberately does not
contain FFmpeg or Vamp plugin binaries, so the target machine must provide
those separately.

## Download and prerequisites

The current prebuilt archive is linked from the README's automatically updated
[Download section](../README.md#download). Choose a Linux x86_64 bundle built
for the target distribution family. The Mint 22 build is suitable for Ubuntu
24.04 because Mint 22 is based on that Ubuntu release.

The target needs:

- Linux x86_64 in the supported Ubuntu, Mint, or Debian family;
- system FFmpeg on `PATH`;
- `curl` for the supplied Vamp installer;
- write access to the media directories that will hold `.chordflask` data; and
- a browser for the local HTTP interface.

The target does not need a source checkout, project virtual environment,
compiler, or system Python for ordinary standalone use. See
[COMPATIBILITY.md](COMPATIBILITY.md) for the maintained platform matrix.

## Build the archive

From a ChordFlask source directory on a supported system:

```bash
make setup
make standalone
# Alternatively, build the same bundle plus a Debian package:
make deb
```

The build first runs the complete project checks. It then creates an archive
whose name records the build machine's distro, CPU architecture, Python
version, and ChordFlask version, for example:

```text
flask/dist/chordflask-debian13-x86_64-py3.12-vX.Y.Z.tar.gz
```

Run the freshly built local copy with:

```bash
make standalone-run
```

## Debian package

`make deb` builds the canonical standalone and creates
`flask/dist/<standalone-release-name>.deb` with `dpkg-deb`, without root or
installation. To wrap an already built bundle, use
`make deb STANDALONE_DIR=/path/to/standalone-dir`.

On a compatible Debian / Ubuntu / Mint machine:

```bash
sudo apt install ./<release-package>.deb
/opt/chordflask/install_vamp.sh
chordflask
```

Remove with `sudo apt remove chordflask`. The complete bundle lives in
`/opt/chordflask`; commands are linked into `/usr/bin`. The package has the same
glibc constraints and external Vamp requirement as the archive. It does not
install the optional helper virtual environments.

## Install the portable archive on the target machine

Copy the archive (for example `chordflask-debian13-x86_64-py3.12-vX.Y.Z.tar.gz`)
to the target. Then run:

```bash
sudo apt update
sudo apt install --no-install-recommends ffmpeg curl
tar -xzf chordflask-debian13-x86_64-py3.12-vX.Y.Z.tar.gz
cd chordflask-debian13-x86_64-py3.12-vX.Y.Z
./install_vamp.sh
./chordflask --version
./chordflask.sh
```

Open <http://localhost:5000>. Stop ChordFlask with `Ctrl+C`.

`./chordflask --version` reports the build identity embedded in the executable.
The `VERSION` file is the human-readable copy of that identity for reference;
the executable does not read it at runtime.

The standalone includes the same persistent worker and **Analyze** batch
control as the source run. Its default batch size is 50 (configurable from 1 to
500), and interrupted queue work is retried after the launcher restarts.

`install_vamp.sh` requires no root access. It downloads checksum-pinned
Chordino and QM plugin archives, installs them into `~/.vamp`, and verifies both
plugin identifiers using the bundled ChordFlask runtime.

For a different user-writable plugin directory:

```bash
./install_vamp.sh --dest /path/to/vamp
VAMP_PATH=/path/to/vamp ./chordflask.sh
```

The target machine must belong to the supported Linux family. A binary built on
a newer Linux distribution can require a newer glibc than an older target has;
build on the oldest target family when portability matters.

### Starting from another directory

Keep the extracted directory intact. The recommended `chordflask.sh` launcher
resolves the sibling executable and bundled resources while preserving the
caller's working directory. It can therefore be invoked by absolute path from a
media directory or another unrelated directory:

```bash
cd /tmp
/opt/chordflask/chordflask.sh
```

Do not move only the executable away from its companion files. For LAN use,
pass the normal options to the launcher:

```bash
./chordflask.sh --listen 0.0.0.0 --roots "/home/user/Music"
```

The application has no authentication or TLS; see [SECURITY.md](../SECURITY.md)
before exposing it beyond localhost.

## Source and standalone differences

| Capability | Source / virtualenv | Standalone |
| --- | --- | --- |
| Browser playback, Chordino/QM analysis, batch queue, editing, export download | Included | Included |
| Python runtime | External project venv | Bundled in executable |
| FFmpeg | System installation | System installation |
| Vamp plugins | Installed separately with `make plugins` | Installed separately with `install_vamp.sh` |
| Display existing same-stem `.cho` Lyrics | Included | Included |
| Generate/fetch Lyrics and Thai romanization | Installed helper or optional external Lyrics venv | Optional external Lyrics venv |
| Display romanization already stored in `.cho` | Included | Included |
| BTC model runtime and generation | Optional external BTC venv | Lightweight connector bundled; model runtime remains external |
| Demucs runtime/model | Optional external Demucs venv | Not bundled; an existing compatible external runtime can serve desktop Prepare |
| Maintenance and separate helper commands | Installed console commands | Supplied scripts use configured external virtual environments |

The standalone can use previously generated analysis and `.cho` data that
travel with the media collection. It can also prepare Lyrics or BTC when their
external runtimes have been installed from a source checkout. See
[LYRICS.md](LYRICS.md#standalone-behavior) and the
[BTC runtime guide](../chordflask_btc/model/README.md).

## Optional desktop preparation runtimes

Prepare is shown only on desktop layouts (1024 px and wider), and only usable
actions are listed. Install and check the desired external runtimes from a
source checkout before copying or running the standalone:

```bash
make setup-lyrics
make lyrics-check
make setup-btc BTC_ACKNOWLEDGE_WEIGHTS=1
make btc-check
make setup-demucs
make demucs-check
```

Lyrics defaults to `~/.venvs/chordflask-lyrics` and supports
`CHORDFLASK_LYRICS_VENV`. BTC defaults to `~/.venvs/chordflask-btc` and supports
`CHORDFLASK_BTC_VENV`. These runtimes are self-contained and do not require the
source checkout after setup.

The bundle contains only the small, dependency-free `chordflask_demucs`
producer — no Torch, torchaudio, torchcodec, third-party `demucs`, or model
weights. If the external Demucs runtime (`~/.venvs/chordflask-demucs`, created
with `make setup-demucs` from a source checkout) exists and is usable, the
desktop player (1024 px and wider) offers **Stems** in its compact **Prepare**
menu for the loaded song. CUDA is used when available and CPU otherwise,
exactly like the CLI. Preparation runs in the background without interrupting
playback. Without that external runtime the Prepare control is not offered.
Tablet/mobile layouts never show Prepare.

The bundle excludes the Lyrics generator and its optional language runtimes,
but can invoke the external `chordflask-genlyrics` helper. It bundles the
lightweight BTC connector needed to validate the external runtime, decode
audio, normalize predictions, and publish a BTC track. Torch, BTC predictor
code and weights, PyThaiNLP, ONNX Runtime, Demucs, and all optional model
weights remain outside the executable. If no external runtime is usable, the
complete **Prepare** control stays hidden.

## Compatibility and glibc

A standalone is not a distribution-independent static binary. PyInstaller
bundles ChordFlask and its Python dependencies, but it still uses the target's
glibc and other base system facilities. A bundle generally runs on the same or
newer compatible distribution family than the build host; it may fail on an
older system with a message naming a missing `GLIBC_*` symbol.

For widest compatibility, build on the oldest supported target family. If a
prebuilt bundle reports a glibc error, use a bundle built on a compatible older
base, run from source on the target, or build the standalone on a matching
system. Renaming or copying the executable cannot change its glibc requirement.
The detailed platform and build constraints are in
[COMPATIBILITY.md](COMPATIBILITY.md#pyinstaller-standalone).

FFmpeg and Vamp plugin ABI compatibility are independent of the bundled Python
runtime. ChordFlask intentionally does not ship their binaries. The pinned
plugin installer and diagnostic procedure are documented in
[VAMP.md](VAMP.md).

## Files in the archive

- `chordflask` — application executable
- `chordflask.sh` — recommended launcher
- `install_vamp.sh` — verified plugin installer
- `VERSION` — human-readable copy of the embedded build identity (version, build time, commit)
- `README.md` — this guide
- `THIRD_PARTY_NOTICES.md` — dependency licences and provenance
- `LICENSE` and `LIBERATION-FONTS-LICENSE.txt` — application and bundled font licenses
- `chordflask-analyze`, `chordflask-demucs`, `chordflask-export`,
  `chordflask-maintain`, `chordflask-genlyrics` — the existing helper scripts;
  these select their configured/default external virtual environment, preserve
  the caller's directory and arguments, and report missing runtimes explicitly.
  Copying or installing these scripts does not bundle their external runtimes.

The standalone reads and displays same-stem lowercase `.cho` song sheets in
the Lyrics view, including chord-follow synchronization. It does not include
`chordflask_lyrics`, an LRCLIB client, PyThaiNLP, or ONNX Runtime. With
the external Lyrics runtime installed, desktop Prepare invokes that helper for
LRC, embedded, or LRCLIB generation and whatever romanization engines the
runtime supports. Experimental romanization already stored in a `.cho` still
displays beneath its canonical original Thai lyric. Narrow/mobile layout
remains Grid-only.

## Troubleshooting and diagnostics

- **`ffmpeg` is missing:** install it with `sudo apt install ffmpeg`, verify
  `ffmpeg -version`, and start the launcher again.
- **Chord or beat analysis reports missing Vamp plugins:** rerun
  `./install_vamp.sh`. Use `./chordflask --check-vamp` to verify the two plugin
  identifiers without starting the web UI.
- **The installer cannot download a plugin:** check network access and rerun.
  The installer tries its pinned sources and refuses an archive whose checksums
  do not match; do not bypass that failure with an unverified binary.
- **`GLIBC_* not found`:** the build host was newer than the target. Follow
  [Compatibility and glibc](#compatibility-and-glibc).
- **The browser cannot connect:** confirm the terminal still shows a running
  server, try <http://localhost:5000>, and use `./chordflask.sh --port 5050` if
  port 5000 is occupied.
- **No files appear:** verify `.mp3`, `.mp4`, or `.webm` suffixes and any
  `--roots` restriction.
- **Analysis cannot be saved:** the user needs write access to the media
  directory so `.chordflask` can be created.
- **Lyrics or BTC is absent from Prepare:** run `make lyrics-check` or
  `make btc-check` from a source checkout. The standalone intentionally does
  not contain those heavy runtimes.

For build identity, run `./chordflask --version`. For a complete core dependency
check in a source installation, use `chordflask-maintain doctor`.
