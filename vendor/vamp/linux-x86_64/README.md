# Private Vamp Reference Plugins

This directory contains Linux x86_64 Vamp plugin reference binaries used for
private development and compatibility validation:

- `nnls-chroma.so`
- `nnls-chroma.cat`
- `nnls-chroma.n3`
- `qm-vamp-plugins.so`

The `.so` files are excluded from public Git archives and from standalone
artifacts. Target systems install the plugins into `~/.vamp` or point
`VAMP_PATH` at an external installation.

The original license and project files are kept next to the binaries:

- `NNLS-COPYING`, `NNLS-README`, `NNLS-CITATION`
- `QM-COPYING`, `QM-README.md`, `QM-INSTALL.txt`, `QM-CHANGELOG.md`

These binaries are platform-specific and are not a general release payload.
See `THIRD_PARTY_NOTICES.md` and `docs/VAMP.md` for provenance and distribution
gates.
