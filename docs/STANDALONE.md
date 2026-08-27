# Portable Linux bundle

ChordFlask's portable bundle is useful when you want to build once and copy the
application to another compatible Linux x86_64 machine. A prebuilt Linux x86_64
bundle may be attached to a GitHub release, but you can also build it yourself
with the steps below.

The bundle contains ChordFlask and its Python runtime. It deliberately does not
contain FFmpeg or Vamp plugin binaries, so the target machine must provide
those separately.

## Build the archive

From a ChordFlask source directory on a supported system:

```bash
make setup
make standalone
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

## Install on the target machine

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

The standalone includes the same persistent worker and **Queue next** batch
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

## Files in the archive

- `chordflask` — application executable
- `chordflask.sh` — recommended launcher
- `install_vamp.sh` — verified plugin installer
- `VERSION` — application version and build identity
- `README.md` — this guide
- `THIRD_PARTY_NOTICES.md` — dependency licences and provenance
