# Forward Compatibility

ChordFlask targets Ubuntu 24.04+, Linux Mint 22+, and Debian 13+ as the supported
platform family. Newer compatible releases in the same family are accepted
through capability-based detection, not a hard-coded version allowlist.

This document records the forward-compatibility strategy for each component so
maintainers can assess what must be tested for a new distro or Python release.
It does not turn a synthetic or mocked check into a support claim.

## Setup

The setup script (`scripts/setup_venv.sh`) uses `dpkg-query` on Debian-family
systems to check individual package names. It never reads `/etc/os-release` or
`VERSION_ID`, so a future Ubuntu 26.04, Mint 23, or Debian 14 is accepted as
long as its apt archive provides the same package names (`python3-venv`,
`ffmpeg`, `vamp-plugin-sdk`, etc.). The non-Debian fallback path checks
commands and file presence (`command -v`, `pkg-config --exists`, `Python.h`)
instead of package names.

Tests verify that detection is capability-based, not version-checking, and
that the setup script never invokes `sudo`, `apt`, or `apt-get`.

## Python Version Policy

The setup script permits installation attempts with CPython 3.10–3.13. Python
3.14 produces a warning but proceeds, while Python 3.15 and later are rejected
with a clear message. Permitting an attempt is not the same as release support.

Only CPython 3.12 has a reviewed constraint set (`constraints-python312.txt`)
and release-validation evidence. Other permitted versions use the direct
requirements from `requirements-core.txt` with compatible-version ranges and
*no* pinned constraints. Python 3.13 and 3.14 must not be advertised as
supported until clean CI plus real FFmpeg, Vamp, audio-analysis, and standalone
validation pass.

To add support for a new Python version:

1. Run `make setup` with that version on the supported distro family.
2. Run `make check` and `make standalone`.
3. If all pass, add the version to the setup script's accepted list.
4. Optionally add a `constraints-python314.txt` when the combination has been
   reviewed across a full clean setup.

## System FFmpeg

ChordFlask requires a system `ffmpeg` on `PATH`. At startup, `ffmpeg_runtime.py`
resolves the executable via `shutil.which()` and sets `IMAGEIO_FFMPEG_EXE` for
MoviePy and ImageIO. No FFmpeg binary is bundled in the source release or
standalone build.

The FFmpeg command-line interface is stable across distro versions. Tests verify
that the `moov atom not found` error pattern and basic audio conversion work
with the system `ffmpeg`. The standalone build is checked to exclude any
`imageio_ffmpeg.binaries`.

## External Vamp Plugins

ChordFlask requires two Vamp plugin identifiers at runtime:

- `nnls-chroma:chordino`
- `qm-vamp-plugins:qm-barbeattracker`

The pinned versions are NNLS Chroma 1.1 and QM Vamp Plugins 1.8.0. Plugin
binaries are not supplied in the source release or standalone build. The
standalone ships an installer (`install_vamp.sh`) and complete target guide
(`README.md`).

The Python `vamp==1.1.0` host package has been validated on CPython 3.12.3,
Linux x86_64. Plugin discovery and in-memory analysis are tested with real
plugins via `test_vamp_integration.py`. Missing plugins produce a clear startup
warning; the UI remains usable for browsing and playback without Vamp.

Forward compatibility for Vamp depends on:

- The `vamp` Python package building against the target system's Vamp SDK.
- The pinned plugin `.so` binaries being ABI-compatible with the target system's
  C++ runtime and linker. The current Linux x86_64 ELF binaries are compiled
  against common system libraries (libc, libstdc++, libm) available on all
  supported distro releases.

## PyInstaller Standalone

The standalone build uses PyInstaller 6.21.0 to produce a Linux x86_64 onefile
executable. Forward compatibility concerns:

- **glibc**: The build machine's glibc version determines the minimum required
  glibc on the target. Build on the oldest supported distro (Ubuntu 24.04) for
  maximum target compatibility.
- **PyInstaller upgrades**: New PyInstaller major versions can change
  collection behavior. After upgrading, verify that `pyi-archive_viewer -l`
  shows no `imageio_ffmpeg/binaries` or `vamp_plugins` in the archive, and that
  a missing-system-FFmpeg smoke test exits with the expected apt hint.
- **Python upgrades**: A Python version bump requires rebuilding and smoke-testing
  the standalone on the target family.

## Audio Dependencies

The core audio pipeline uses `librosa` for BPM/meter analysis and `vamp` for
chord/beat extraction from the system Vamp host. The optional `pydub` path
(used by the legacy `mp3player.py` playback module, which no longer runs as a
standalone CLI) relies on Python's `audioop` module, which was removed from the
standard library after Python 3.12.
This path is not part of the default setup and is gated behind
`CHORDIFIER_OPTIONAL=1`. Python 3.13+ users who need optional playback can
either omit the optional group or install a third-party `audioop` backport.

## Testing Compatibility

To evaluate a new distro or Python version without a full VM:

```bash
# Verify capability-based detection with synthetic mocks
make check

# Real integration tests (requires system ffmpeg and vendored Vamp plugins)
CHORDIFIER_REQUIRE_VAMP=1 make test TEST_ARGS="tests/test_ffmpeg_integration.py tests/test_vamp_integration.py"

# Standalone build and smoke-test
make standalone
PATH=/no-such-directory flask/dist/chordflask --help   # must show ffmpeg hint
```

A concrete release is claimed as tested only after two successful `make all`
runs on a clean installation of that release. Test results from mock-based
synthetic tests indicate that detection logic is forward-compatible, but do not
replace real-environment validation.
