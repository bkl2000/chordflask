# Third-Party Notices

ChordFlask includes or depends on the following third-party components. Each
component retains its own license. ChordFlask-owned source code is MIT.

## Vamp Audio Analysis Plugins

### NNLS Chroma / Chordino v1.1

- **License:** GNU General Public License v2 (or later)
- **Authors/implementation:** Matthias Mauch and Chris Cannam
- **Research citation:** Matthias Mauch and Simon Dixon, Queen Mary University
  of London (see the BibTeX entry below)
- **Upstream:** https://isophonics.net/nnls-chroma.html
- **Source:** https://code.soundsoftware.ac.uk/projects/nnls-chroma
- **Archive:** `nnls-chroma-linux64-v1.1.tar.bz2`
  - MD5 published upstream: `1c06fb30913a02ec203019b1d290b022`
  - SHA-256 independently verified from the matching archived upstream file: `877964bce86027d1c73c9210fcb3446b1da10dc40bba36b1bf04a61a60ad1d7f`
- **Corresponding-source archive:** https://code.soundsoftware.ac.uk/attachments/download/1691/nnls-chroma-1.1.tar.gz
- **Reference binary (not supplied):** NNLS Chroma Linux x86_64 (ELF 64-bit LSB x86-64)
  - SHA-256: `022f18b7a0b922161bba5f292b916482fd04d9bad4c875292d25c141f98c7d99`
  - ELF build ID: `062d29d5571e46ee31ae4a0b200459ef5ef1fa1d`
  - RDF descriptor: `nnls-chroma.cat`, `nnls-chroma.n3`
- **Academic citation (BibTeX):**
  ```
  @inproceedings{matthias2010a,
   author = {Matthias Mauch and Simon Dixon},
   title = {Approximate Note Transcription for the Improved Identification of
            Difficult Chords},
   booktitle = {Proceedings of the 11th International Society for Music
                Information Retrieval Conference (ISMIR 2010)},
   year = {2010}
  }
  ```
- **Attribution:** "If you make use of this software for any public or
  commercial purpose, we ask you to kindly mention the authors and Queen Mary,
  University of London in your user-visible documentation."

### QM Vamp Plugins v1.8.0

- **License:** GNU General Public License v2 (or later)
- **Copyright:** Queen Mary University of London, Centre for Digital Music
- **Upstream:** https://code.soundsoftware.ac.uk/projects/qm-vamp-plugins/files
- **Archive:** `qm-vamp-plugins-1.8.0-linux64.tar.gz`
  - MD5 published upstream: `79747c514aca3c6b34aa5012584157dd`
  - SHA-256 independently verified from the matching archived upstream file: `53f9e0e24d938507c01cb368e098cb321346b91594695aa877e7f67f17841ffa`
- **Corresponding-source archive:** https://code.soundsoftware.ac.uk/attachments/download/2624/qm-vamp-plugins-1.8.0.tar.gz
- **Reference binary (not supplied):** QM Vamp Plugins Linux x86_64 (ELF 64-bit LSB x86-64)
  - SHA-256: `efdfac327da08d20f030ef833e2427d8f67f0228e2f9db802f200627fd35ca27`
  - ELF build ID: `40f7532098f1493b145fa0730df37e98dd63da2c`

### Binary provenance and native libraries

The reference files were extracted from the pinned upstream Linux
x86_64 binary archives. A local source rebuild has not been reproduced, so the
exact upstream compiler and build flags remain unverified. On the reviewed
Ubuntu 24.04-family host, `ldd` reports these runtime interfaces:

- NNLS Chroma: `libstdc++.so.6`, `libm.so.6`, `libgcc_s.so.1`, `libc.so.6`,
  and the GNU/Linux dynamic loader.
- QM Vamp Plugins: the same libraries plus `libpthread.so.0`.

These are target-system libraries, not copied into ChordFlask. The source
release contains notices, installer source, and plugin descriptors, but no
plugin executable. Any future bundled plugin release needs a qualified license
and corresponding-source review first.

## License Texts

Full GPLv2 license texts are included even though the plugin executables are
not supplied:
- `vendor/vamp/linux-x86_64/NNLS-COPYING`
- `vendor/vamp/linux-x86_64/QM-COPYING`

## FFmpeg

ChordFlask requires FFmpeg as an external system dependency. FFmpeg is not bundled
with ChordFlask. Users must install FFmpeg through their system package manager:

```bash
sudo apt install ffmpeg
```

Official reference: https://ffmpeg.org/legal.html

## Python Dependencies

Python runtime dependencies are listed in `requirements-core.txt` and
`requirements.txt`. Each Python package carries its own license. Key
audio-processing dependencies include:

- **Flask** (BSD-3-Clause) — web application framework
- **librosa** (ISC) — audio analysis
- **vamp** (MIT) — Python Vamp host
- **music21** (BSD) — MusicXML/MIDI export
- **moviepy** (MIT) — media conversion (via ImageIO/FFmpeg)
- **numba** (BSD) — JIT compilation
- **scikit-learn** (BSD) — optional post-processing

ChordFlask is an independent project and is not affiliated with or endorsed by
the Pallets project.
