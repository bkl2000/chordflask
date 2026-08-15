# Playback and analysis

ChordFlask plays MP3, MP4, and WebM files while showing chords aligned to
detected beats. MP3 sources are analyzed directly without making another audio
copy. Selecting an unanalyzed file adds it to a local queue. The managed worker
processes one file at a time and the browser reports whether the file is
running, waiting, failed, or ready.

Use **Browse** to start at the local user's home directory. When allowed media
roots are configured, Browse shows only those roots and does not offer parent
navigation outside them. The path field and stored-directory selector remain
available for direct access. Browser file uploads are deliberately not used.

If files with the same base name have different supported extensions, only one
appears because they would share an analysis sidecar. The deterministic order
is MP4, then WebM, then MP3; source files are never removed.

## Batch queue

**Queue next** adds up to N new analyses from the current visible file list.
N defaults to 50, accepts 1–500, and is remembered by the browser. The current
filter and Name/Size/Modified ordering determine which files are next. Valid
analyses and jobs already pending or processing are skipped without consuming
N, so another click queues the following N files. Failed jobs are eligible for
retry. Only the displayed directory is considered; subdirectories are not
scanned recursively.

## Playback controls

- **Previous** and **Next** follow the visible, filtered, and sorted file list.
  MP3 and video files share this list. Navigation stops at the first and last
  file rather than wrapping.
- **Continue** starts the next visible file when the current one ends. If its
  analysis is missing, playback waits and starts after analysis succeeds.
- **Repeat** repeats the current file.
- **A** and **B** mark a loop segment, and **⟳** repeats only that segment.
  Loop, Repeat, and Continue are mutually exclusive.
- **Transpose** changes displayed chord names without changing the audio or
  stored analysis.
- The small **↻** control requests fresh Chordino/QM analysis while playback and
  browsing remain available.

## Stored analysis

Each media directory receives a `.chordflask` subdirectory containing generated
JSON, MusicXML, MIDI, and intermediate audio. ChordFlask does not alter the
source media file.

The local queue file is written atomically. When the worker restarts, a job left
in `processing` returns to `pending`. Analysis runs in a per-song temporary
directory; orphaned work directories are removed on retry, MP3/MusicXML/MIDI
are replaced atomically, and valid JSON is published last as the completion
marker. A process interruption can therefore delay a job but cannot make a
partial analysis appear complete.

Schema v3 stores independent named analysis tracks:

- Chord tracks contain timestamped chord labels. Built-in analysis produces a
  `chordino` track.
- Rhythm tracks contain tempo, meter, beats, and downbeats. Built-in analysis
  produces a `qm_barbeattracker` track.
- Beat numbers and downbeat positions assume the configured beats-per-bar value
  (normally 4); the meter is not detected from the audio.
- Beat-to-chord alignment is derived from the selected chord/rhythm combination
  and is not persisted.
- Track selectors appear when multiple choices are available.

The default chord analysis uses the Vamp Chordino plugin. The command-line
analyzer additionally accepts an optional `madmom` mode, but `madmom` is not
installed by the default or optional dependency sets; it must be installed
separately to use that path.

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
~/.venvs/chordflask/bin/python flask/chordflask.py --no-metric-chords
```

A read-only diagnostic reports rhythm classification and displayed beats that
differ:

```bash
~/.venvs/chordflask/bin/python scripts/metric_chords_diff.py path/to/chords.json
```

## Saving a leadsheet

The **Save** control downloads the exact active display as one ZIP containing
matching playable Markdown and print-ready A4 PDF leadsheets; the server
creates no export file. The Markdown document contains the media title, one
compact metadata line (`**120 BPM · 4/4 · Edited · Flats · Transpose 0**`), the
chord/rhythm track source line, and a `text` code block without tables,
barlines, or measure labels. Each row contains two complete measures: eight
aligned beat fields in 4/4 or six in 3/4. Beat fields are at least ten
characters wide, expand together for longer symbols, and the space between the
two measures is wider. Blank lines separate rows, with extra space after each
eight-measure group.

The export always reflects the accepted screen state: the selected
Original/Edited or named chord track, the active rhythm track, transpose,
Flats/Sharps spelling, Unicode mode, the repeat mode, and the same
rhythm-aware smoothing as the grid. In the default `changes` mode a held chord
becomes `-`; the `chords` mode writes every beat chord. A pickup is placed on a
separate, count-aligned row marked once as `Auftakt (Zählzeiten …)`. Incomplete
final measures and an unpaired last measure contain only empty remainder
fields. Analyses without usable beat numbers fall back to the meter (or four
beats per measure). Chord qualities, extensions, slash basses, `N`, and `X`
remain unchanged. The batch helper documented in the README writes the same
format.

The PDF keeps the Markdown beat text verbatim and uses four framed measures per
row, 15 rows per page, bar numbers, continuation headings, and automatically
fitted monospace chords. A pickup has its own `Auftakt` box before measure 1;
incomplete endings retain a full measure box with empty remaining beat fields.
