# Playback and analysis

ChordFlask plays MP4 and WebM files while showing chords aligned to detected
beats. Selecting an unanalyzed file adds it to a local queue. The managed worker
processes one file at a time and the browser reports whether the file is
running, waiting, failed, or ready.

## Playback controls

- **Previous** and **Next** follow the visible, filtered, and sorted file list.
  They stop at the first and last file rather than wrapping.
- **Continue** starts the next visible file when the current one ends. If its
  analysis is missing, playback waits and starts after analysis succeeds.
- **Repeat** repeats the current file.
- **Transpose** changes displayed chord names without changing the audio or
  stored analysis.
- The small **↻** control requests fresh Chordino/QM analysis while playback and
  browsing remain available.

## Stored analysis

Each media directory receives a `.chordflask` subdirectory containing generated
JSON, MusicXML, MIDI, and intermediate audio. ChordFlask does not alter the
source media file.

Schema v3 stores independent named analysis tracks:

- Chord tracks contain timestamped chord labels. Built-in analysis produces a
  `chordino` track.
- Rhythm tracks contain tempo, meter, beats, and downbeats. Built-in analysis
  produces a `qm_barbeattracker` track.
- Beat-to-chord alignment is derived from the selected chord/rhythm combination
  and is not persisted.
- Track selectors appear when multiple choices are available.

Schema v1, v2, and unversioned files remain readable. The next normal save
writes schema v3. Reanalysis validates replacement data before atomically
replacing the JSON and preserves user data, display preferences, and unrelated
tracks.

## Rhythm-aware chord display

The browser uses rhythm-aware display by default. On a sufficiently regular
beat grid it removes only short isolated `A-B-A` detections on weak beats. This
changes the display only; raw timestamps, analysis JSON, and exports stay
unchanged.

Start with nearest-beat display instead:

```bash
~/.venvs/chordifier/bin/python flask/chordflask.py --no-metric-chords
```

A read-only diagnostic reports rhythm classification and displayed beats that
differ:

```bash
~/.venvs/chordifier/bin/python scripts/metric_chords_diff.py path/to/chords.json
```
