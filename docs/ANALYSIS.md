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

## Command-line analysis

The command-line analyzer is `scripts/chordflask-analyze`. Chordino is the
built-in, default analyzer, so a plain target uses Chordino:

```bash
scripts/chordflask-analyze song.mp4
scripts/chordflask-analyze /music/videos
```

`--analyzer chordino` is only the explicit spelling of that default.

- **Chordino is the default.** It runs the normal Chordino/QM analysis and is
  the basis of the standalone.
- **`--dry-run`** previews what would happen without changing anything.
- **`--replace`** renews only the chosen analyzer's analysis. For Chordino it
  re-runs Chordino/QM while preserving other tracks (reference, Edited),
  display preferences, and user data. Other existing tracks are never deleted.
- **Directory processing is non-recursive.** Only files directly inside the
  target directory are considered; subdirectories are skipped. Where several
  extensions share one base name, MP4 wins over WebM over MP3.

### Optional BTC analyzer

The optional BTC analyzer is available only after the user has installed its
separate runtime with `make setup-btc` (and `make btc-check` to diagnose it):

```bash
make setup-btc BTC_ACKNOWLEDGE_WEIGHTS=1
make btc-check

scripts/chordflask-analyze --analyzer btc song.mp4
scripts/chordflask-analyze --analyzer btc /music/videos
```

BTC runs a pretrained model in an isolated environment and adds its result as a
separate `btc` chord track to an existing ChordFlask analysis; it never
replaces Chordino. Without the runtime, `--analyzer btc` reports the optional
setup and diagnostic commands while Chordino remains available.
Chordino and BTC are both stored in the analysis file and can be switched in
the browser with the chord-track selector.

### Optional Demucs stems

Demucs is a separate optional batch path, not a chord analyzer and not part of
the normal worker workflow:

```bash
make setup-demucs
make demucs-check
scripts/chordflask-demucs --dry-run /music/videos
scripts/chordflask-demucs /music/videos
```

The command runs the fixed `htdemucs` model serially and stores `bass`,
`drums`, `other`, and `vocals` as one atomic
`audio_tracks["demucs:htdemucs"]` set. `CURRENT` requires all four FLAC files,
their hashes and audio metadata, the current source hash, and the current
pipeline metadata. `TODO` is processed normally; `STALE` is left unchanged
unless `--replace` is used; malformed JSON is never overwritten.

The source is first decoded to a canonical 44.1 kHz stereo reference. Stem
sample counts are checked against it and small bounded tail differences are
recorded if normalized. FFprobe's original container audio-stream start time,
PTS, time base, and container start time are retained in set metadata when
available. They are informational only: no playback offset or video correction
is applied, and the stems are aligned to the decoded canonical source audio.

In the player, a song with a complete set shows a **STEMS** control. The four
stems play as slave audio sources following the original media master
timeline; per-stem mute and a single shared volume slider are provided. See
[docs/DEMUCS.md](DEMUCS.md) for the full workflow and the
`chordflask-maintain stems` maintenance commands.

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
- **Auto** starts the next visible file when the current one ends. If its
  analysis is missing, playback waits and starts after analysis succeeds.
- **Repeat** repeats the current file.
- **A** and **B** mark a loop segment, and **⟳** repeats only that segment.
  Loop, Repeat, and Auto are mutually exclusive.
- **Transpose** changes displayed chord names without changing the audio or
  stored analysis.
- The small **↻** control requests fresh Chordino/QM analysis while playback and
  browsing remain available.

## Stored analysis

Each media directory receives a `.chordflask` subdirectory containing generated
JSON, MusicXML, MIDI, intermediate audio, and optional Demucs FLAC generations.
ChordFlask does not alter the
source media file.

The queue, worker lock, and logs live in `~/.chordflask` in your home
directory — a separate application-state area, not part of any media
directory's `.chordflask`.

A read-only report shows how much space one directory's analysis storage uses
without deleting anything:

```bash
scripts/chordflask-maintain storage report /path/to/music
```

Cleanup is always explicit and limited to one media directory:

```bash
# Remove orphaned analysis/conversion temporary directories (refused while an
# analysis worker is active).
scripts/chordflask-maintain storage cleanup /path/to/music --orphan-temp

# Remove corrupt-analysis backups older than a retention age.
scripts/chordflask-maintain storage cleanup /path/to/music --corrupt-backups --older-than-days 30

# Remove cached audio (.mp3) that is regenerable from a video source. This does
# not delete the stored chord analysis; a later reanalysis may recreate the
# audio cache. Refused while an analysis worker is active.
scripts/chordflask-maintain storage cleanup /path/to/music --cached-audio
```

Valid analysis JSON, source media, and user-edited data are never deleted.
Cleanup stays limited to one media directory; there is no recursive cleanup yet.

The local queue file is written atomically. When the worker restarts, a job left
in `processing` returns to `pending`. Analysis runs in a per-song temporary
directory; orphaned work directories are removed on retry, MP3/MusicXML/MIDI
are replaced atomically, and valid JSON is published last as the completion
marker. A process interruption can therefore delay a job but cannot make a
partial analysis appear complete.

Schema v3 stores independent named analysis tracks and optional grouped audio
track sets:

- Chord tracks contain timestamped chord labels. Built-in analysis produces a
  `chordino` track.
- Rhythm tracks contain tempo, meter, beats, and downbeats. Built-in analysis
  produces a `qm_barbeattracker` track.
- Beat numbers and downbeat positions assume the configured beats-per-bar value
  (normally 4); the meter is not detected from the audio.
- Beat-to-chord alignment is derived from the selected chord/rhythm combination
  and is not persisted.
- Track selectors appear when multiple choices are available.
- Optional Demucs output is one `demucs:htdemucs` audio set containing all four
  aligned FLAC stems (`bass`, `drums`, `other`, `vocals`). The player exposes a
  **STEMS** control for any song with a complete set; the four stems play as
  slave audio following the original media master timeline.

The default chord analysis uses the Vamp Chordino plugin. An older,
experimental `madmom` analyzer path exists in the internal analyzer modules,
but it is not installed by the default or optional dependency sets and is not
part of the normal `chordflask-analyze` workflow.

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
scripts/chordflask --no-metric-chords
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
remain unchanged. The command-line export below writes the same format.

The PDF keeps the Markdown beat text verbatim and uses four framed measures per
row, 15 rows per page, bar numbers, continuation headings, and automatically
fitted monospace chords. A pickup has its own `Auftakt` box before measure 1;
incomplete endings retain a full measure box with empty remaining beat fields.

## Command-line export

The same leadsheet export is available as a command:

```bash
scripts/chordflask-export song.mp4
scripts/chordflask-export /music/videos
scripts/chordflask-export --format markdown song.mp4
scripts/chordflask-export --format pdf song.mp4
scripts/chordflask-export --format both song.mp4
```

The default format is `both` (Markdown and PDF). A directory is processed
non-recursively; a missing analysis is created serially only when needed, and a
second run reuses it. One failing file does not stop later files.

Options:

- `--chord-track auto|original|edited|TRACK_ID` — which chord track to export
  (default `auto` = Edited when present, otherwise Chordino). Use a named track
  ID such as `reference` to export that track.
- `--rhythm-track TRACK_ID` — beat grid source (default `qm_barbeattracker`).
- `--transpose N` — display transposition in semitones (default `0`).
- `--sharps` — spell chord roots with sharps instead of flats.
- `--unicode` — render accidentals as Unicode symbols.
- `--repeat-mode changes|chords` — `changes` writes held beats as `-`,
  `chords` writes every beat (default `changes`).
- `--no-metric-chords` — use the unfiltered nearest-beat display instead of the
  enabled-by-default rhythm-aware smoothing.

Output files land beside the analysis, named
`.chordflask/<name>-chords-<track>.md` and `.pdf`. Existing files are replaced
atomically. The target media must already have an analysis (or ChordFlask
creates one); a requested chord/rhythm track that is not present fails that
file with an error. Exit code 0 means all exports succeeded, 1 means one or
more files failed, and 2 means an invalid invocation.
