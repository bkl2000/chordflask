# Vamp setup for the ChordFlask standalone

ChordFlask starts without Vamp plugins so browsing and media playback remain
available. Chord analysis needs both `nnls-chroma:chordino` and
`qm-vamp-plugins:qm-barbeattracker`.

From the unpacked standalone directory, run:

```bash
./install_vamp.sh
```

The installer needs no `sudo`. It downloads the pinned upstream plugin
archives, enforces their SHA-256 checksums, installs into `~/.vamp`, and asks
the bundled ChordFlask runtime to verify both plugin identifiers.

For another user-writable location:

```bash
./install_vamp.sh --dest /path/to/vamp
export VAMP_PATH=/path/to/vamp
./chordflask.sh
```

To reuse an existing trusted plugin directory without downloading:

```bash
./install_vamp.sh --from /path/to/plugins
```

After manual changes, the bundled runtime can repeat discovery without
starting the web application:

```bash
./chordflask --check-vamp
```

See `THIRD_PARTY_NOTICES.md` for versions, provenance, licences, checksums, and
the public-release boundary. The standalone does not contain plugin `.so`
files.
