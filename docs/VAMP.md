# Vamp Plugin Installation

ChordFlask uses Vamp plugins for chord and beat extraction. Plugin binaries are
not supplied in the source release or standalone build; target systems install
them separately.

## Required plugins

- `nnls-chroma:chordino` — chord extraction
- `qm-vamp-plugins:qm-barbeattracker` — beat and downbeat tracking

ChordFlask decodes mono audio at 44.1 kHz for both plugins. Chordino uses NNLS,
a 0.02% bass-noise threshold, and local tuning. The local-tuning value is `1`,
the highest value accepted by the version-1.1 runtime descriptor.

## Pinned versions

The installer pins versions because plugin changes can alter analysis results:

| Plugin | Version | Archive SHA-256 |
| --- | --- | --- |
| NNLS Chroma/Chordino | **1.1** | `877964bce86027d1c73c9210fcb3446b1da10dc40bba36b1bf04a61a60ad1d7f` |
| QM Vamp Plugins | **1.8.0** | `53f9e0e24d938507c01cb368e098cb321346b91594695aa877e7f67f17841ffa` |

These values are defined by the installer behind `make plugins` and packaged as
`install_vamp.sh` with the portable bundle. The installer also checks the legacy
MD5 values published by the upstream projects and never upgrades automatically.

## Installation

Install into the standard user plugin directory:

```bash
make plugins
```

The expected files are:

```text
~/.vamp/nnls-chroma.so
~/.vamp/qm-vamp-plugins.so
```

To use another user-writable directory:

```bash
flask/install_vamp.sh --dest /path/to/vamp/plugins
export VAMP_PATH=/path/to/vamp/plugins
make run
```

The script uses a temporary download directory, verifies the archives, and
installs only into the selected destination. ChordFlask never copies plugin
binaries at application startup.

## Downloads and overrides

Upstream project pages:

- NNLS Chroma/Chordino: https://isophonics.net/nnls-chroma.html
- QM Vamp Plugins: https://code.soundsoftware.ac.uk/projects/qm-vamp-plugins/files

The installer tries upstream downloads first and checksum-matched Internet
Archive captures if an old upstream host is unavailable. Explicit URL overrides
are supported:

```bash
NNLS_URL=https://example.invalid/nnls.tar.bz2 \
QM_URL=https://example.invalid/qm.tar.gz \
flask/install_vamp.sh
```

## Validation

The reviewed environment is Linux x86_64 with CPython 3.12.3, `vamp==1.1.0`,
NNLS Chroma 1.1, and QM Vamp Plugins 1.8.0. The integration test discovers both
plugins in memory, checks Chordino with a synthetic C-major triad, and checks QM
beat spacing with a synthetic 120-BPM click track. No media file is written.

Normal test runs skip this integration test if the native dependencies are
unavailable. To require both plugins:

```bash
CHORDIFIER_REQUIRE_VAMP=1 scripts/run_tests.sh tests/test_vamp_integration.py -v
```

Existing chord JSON files remain valid and are not reanalyzed automatically
when a plugin installation changes.

## Standalone builds

`flask/build_standalone.sh` rejects embedded Vamp and FFmpeg executables. Install
the two required plugins into `~/.vamp`, or set `VAMP_PATH`, before starting a
local standalone build.

The generated directory includes `install_vamp.sh`, `README.md`, and
`THIRD_PARTY_NOTICES.md`. The installer verifies discovery through the bundled
`chordflask --check-vamp` command, so the target needs no separate Python
environment. See [STANDALONE.md](STANDALONE.md) for the complete workflow.
