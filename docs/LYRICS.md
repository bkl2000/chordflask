# Lyrics and synchronized ChordPro sheets

ChordFlask can combine lyrics with an existing chord-and-beat analysis and
write a same-stem ChordPro `.cho` file. The browser reads that file in its
**Lyrics** view while the ordinary analyzed **Grid** remains available.

This page is the complete reference for lyric sources, generation, alignment,
romanization, and limitations. For creating and editing the underlying musical
analysis, see [ANALYSIS.md](ANALYSIS.md).

## Prerequisites and basic workflow

`chordflask-genlyrics` requires a valid ChordFlask analysis with a usable beat
timeline. It deliberately does not start analysis itself.

```bash
chordflask-analyze song.mp3
chordflask-genlyrics song.mp3
chordflask
```

Open the song, then select **Grid | Lyrics**. In a source checkout, use
`scripts/chordflask-analyze`, `scripts/chordflask-genlyrics`, and
`scripts/chordflask` instead.

The source media and analysis JSON are not modified. Generation writes a
sidecar beside the media:

```text
/music/Synthetic Song.mp3
/music/Synthetic Song.cho
```

The suffix must be lowercase `.cho`. The browser displays the sidecar but does
not import it into analysis or treat it as chord truth.

## Grid and Lyrics

**Grid** displays the selected analyzed chord and rhythm tracks. **Lyrics**
displays the external `.cho` with its lyric text and chord markers. The two
views share the existing playback and analyzed beat timeline, but their data
remain separate:

- transposition, accidental spelling, Unicode preference, repeat display, and
  later track selection do not rewrite the `.cho`;
- changing a `.cho` does not alter analyzed or Edited tracks;
- a generated `.cho` is a snapshot of the chord track selected at generation
  time;
- a missing, unreadable, malformed, oversized, or invalid-UTF-8 sidecar causes
  a local Lyrics error without breaking Grid or playback.

Lyrics is available at browser widths of 801 px or greater. Narrow/mobile
layouts remain Grid-only. Hand-written ChordPro sheets display normally, but
precise follow highlighting requires ChordFlask's generated mapping metadata.

## Lyrics sources and priority

The default source order is:

1. synchronized same-stem `.lrc`;
2. lyrics embedded in the media container;
3. LRCLIB.

The first usable source wins. Empty, unreadable, invalid, or unusable input is
skipped and the next configured source is tried. If no source is usable, that
file is reported as failed and no `.cho` is written.

Change the order or restrict lookup with an ordered colon-separated list:

```bash
chordflask-genlyrics --lyrics embedded:lrclib song.mp3
chordflask-genlyrics --lyrics lrc song.mp3
chordflask-genlyrics --lyrics lrclib:lrc song.mp3
```

Valid names are `lrc`, `embedded`, and `lrclib`. Empty, unknown, or repeated
names are rejected.

### Same-stem LRC

For `song.mp3`, the generator looks for `song.lrc` beside it. The file is read
as UTF-8 with an optional byte-order mark and is never modified.

ChordFlask accepts line-synchronized LRC timestamps such as:

```text
[00:12.50]First lyric line
[00:17.20]Second lyric line
```

Each timestamp is interpreted as media seconds. Multiple timestamps on one
line create multiple timed instances. Blank lines, untimed lines, and timestamp
lines without text are ignored. A same-stem `.lrc` containing only plain,
untimed lyrics is therefore not usable and the generator proceeds to the next
configured source.

### Embedded lyrics

Embedded lyrics are read with `ffprobe` from format-level tags. The recognized
case-insensitive names, in priority order, are `syncedlyrics`, `lyrics`, and
`unsyncedlyrics`. This covers MP3 USLT when FFmpeg exposes it as a `lyrics` tag
and compatible lyrics tags in other supported containers.

If an exposed tag contains LRC timestamps, those timestamps are preserved. If
it contains plain text, non-empty lines are distributed in order and at equal
beat-span positions across the existing analyzed beat timeline. This is a
deterministic fallback, not recovered original lyric timing.

There are important container and FFmpeg limits:

- ChordFlask sees only lyrics that `ffprobe -show_entries format_tags` exposes.
- Genuine ID3 SYLT frames are not decoded by this path unless the installed
  FFmpeg happens to expose their content as a recognized format tag.
- Empty text, strings containing null bytes or Unicode replacement characters,
  undecodable output, probe failures, and tags without alphanumeric content are
  treated as unusable.
- Embedded lyrics take priority over LRCLIB by default, including plain USLT
  text, but never take priority over a usable same-stem `.lrc`.

### LRCLIB

LRCLIB lookup occurs only when `chordflask-genlyrics` is explicitly run and the
configured source list reaches `lrclib`. Starting ChordFlask, opening Lyrics,
or using an existing `.cho` performs no LRCLIB request. Media files are never
uploaded; requests contain text metadata and duration only.

For automatic matching, ChordFlask reads Title, Artist, Album, and Duration
from media metadata through `ffprobe`. Missing title or artist values may be
filled from a conventional `Artist - Title` filename, and analysis duration is
used when container duration is unavailable. It first tries LRCLIB's exact
lookup when title and artist exist, then searches by artist and title.

Candidates are checked and ranked rather than trusting service result order:

- when present, title and artist must pass similarity thresholds;
- ordinary automatic matches must be within four seconds or five percent of
  the media duration;
- album and rounded duration are supplied to exact lookup when available;
- synchronized lyrics are preferred by the returned record; usable plain
  lyrics remain a fallback and receive equal beat-span placement.

Use `--tag` to supply a more specific LRCLIB search query for one file:

```bash
chordflask-genlyrics --tag "Artist Song Title Live 2019" song.mp3
```

`--tag` is invalid for a directory and requires `lrclib` in `--lyrics`. Search
results must cover at least half of the query words. With an explicit hint,
duration contributes to ranking and a material duration mismatch is reported,
but it is not an absolute rejection. The exact hint is stored as non-display
provenance in the generated sidecar.

LRCLIB matching does not use audio fingerprints. Live, acoustic, remastered,
extended, or rearranged recordings can match the right song but have
incompatible timing. A more specific `--tag` may help only if LRCLIB contains
the corresponding version. Without a usable synchronized or plain record, the
file fails cleanly.

Requests are sequential, have a ten-second timeout, and are spaced by at least
0.25 seconds in one run. HTTP 404 is treated as no result. Rate limiting (HTTP
429), other HTTP errors, network failures, and malformed service responses are
reported per file; later files in a directory continue.

## Command-line reference

```text
chordflask-genlyrics [--dry-run] [--force] [--tag SEARCH_TEXT]
                     [--lyrics SOURCES] [--track TRACK_ID]
                     [--romanize]
                     [--romanize-engine thai2rom_onnx|tltk|royin]
                     TARGET
```

`TARGET` is one MP3, MP4, or WebM file or one directory. Directory processing
is non-recursive and applies the normal same-stem preference: MP4, then WebM,
then MP3 when several supported files would share one analysis and `.cho`.

- `--lyrics SOURCES` selects and orders `lrc`, `embedded`, and `lrclib`.
- `--tag SEARCH_TEXT` supplies a manual LRCLIB search hint for one file.
- `--track TRACK_ID` selects the chord snapshot; default `auto` prefers
  `user_edited`, otherwise the active/default track, then Chordino as needed.
- `--force` atomically replaces an existing same-stem `.cho`.
- `--dry-run` performs analysis loading, source lookup, alignment, rendering,
  and validation but writes nothing.
- `--romanize` adds Thai romanization presentation metadata.
- `--romanize-engine` selects the romanization engine; it has no effect unless
  `--romanize` encounters Thai text.

Examples:

```bash
chordflask-genlyrics song.mp3
chordflask-genlyrics ~/Music/Album
chordflask-genlyrics --dry-run ~/Music/Album
chordflask-genlyrics --lyrics embedded:lrclib song.mp3
chordflask-genlyrics --track btc song.mp3
chordflask-genlyrics --track user_edited song.mp3
chordflask-genlyrics --force song.mp3
```

An existing `.cho` is skipped before analysis or network lookup unless
`--force` is present. For directory runs, one missing analysis, unavailable
track, unusable lyrics source, network error, or romanization error is reported
as `SKIP`; processing continues and the command exits 1 if any file failed.
Invalid invocation or an unsupported target exits 2. A fully successful run,
including deliberate existing-file skips, exits 0.

## Chord and beat alignment

Generation selects one chord track and one related rhythm track from the valid
analysis. For ordinary analyzer tracks it uses the default QM rhythm track. An
Edited track uses the rhythm source recorded when that Edited version was
created; missing or invalid source metadata is an error rather than an implicit
realignment.

Synchronized LRC or embedded timestamps map each lyric start to the first
analyzed beat that does not precede it. Plain lyric lines have no timestamps,
so they are placed in order at equal spans across the beat list. Lyrics are
grouped around analyzed measures, normally four measures per displayed row and
two when text or chord density is high.

Within a mapped lyric passage, chord markers represent actual analyzed chord
changes. Repeated unchanged beats are suppressed. Each generated marker is
mapped to its analyzed beat range, which lets playback highlight the correct
occurrence even when chord names repeat. A genuine instrumental gap is left
unmapped, so the highlight clears until the next mapped passage. Seek and view
switches use the same player position synchronization as Grid; Lyrics adds no
second playback clock.

Generated files contain ordinary ChordPro markers plus non-display provenance
and synchronization directives:

- `x_chordflask_track` records the selected chord-track snapshot;
- `x_chordflask_beats` maps markers on the next line to analyzed beat indexes;
- `x_chordflask_end` closes the final marker's exclusive beat range;
- `x_lrclib_search` records an explicit LRCLIB hint when used;
- `x_chordflask_romanized` belongs to the immediately following original lyric
  line.

Other ChordPro readers can ignore these unknown directives. Hand editing that
changes the number of chord markers without updating its mapping disables
precise synchronization for that line only; the line still renders. The
analysis JSON always remains authoritative.

## Thai romanization

`--romanize` adds a pronunciation aid below every generated lyric row that
contains Thai script:

```bash
chordflask-genlyrics --romanize song.mp3
```

Conceptually, desktop Lyrics shows:

```text
ฉันรักเธอ แต่เธอไม่รู้
chan rak thoe tae thoe mai ru
```

The original line remains canonical and retains its chords and beat ranges.
Romanization is stored once in the `.cho`, has no independent timestamp, and
is not recomputed by the browser or standalone. Narrow/mobile layouts are
Grid-only and do not show it.

Available engines:

| Engine | Role and availability |
| --- | --- |
| `thai2rom_onnx` | Default PyThaiNLP neural transliteration; installed by source setup with ONNX Runtime and no PyTorch requirement. |
| `tltk` | Alternative transliteration with a different dependency stack; installed on supported Python 3.12 and 3.13 source setups. |
| `royin` | PyThaiNLP's RTGS-oriented alternative; available on supported source setups, including Python 3.14. |

Select one explicitly:

```bash
chordflask-genlyrics --romanize --romanize-engine thai2rom_onnx song.mp3
chordflask-genlyrics --romanize --romanize-engine tltk song.mp3
chordflask-genlyrics --romanize --romanize-engine royin song.mp3
```

There is no silent engine fallback. An unavailable or failing requested engine
reports an error for that file. Python 3.14 does not install TLTK because its
current dependency stack is incompatible; use `thai2rom_onnx` or `royin`.
Details of the supported Python matrix are in
[COMPATIBILITY.md](COMPATIBILITY.md#python-version-policy).

Romanization is experimental pronunciation assistance, not IPA and not an
authoritative representation of Thai tones. Word segmentation, names, loan
words, and unusual vocabulary can produce poor or varying results. Always keep
the original lyric as the reference.

## Standalone behavior

The standalone contains the core `.cho` parser and desktop Lyrics display. It
can display a sidecar generated elsewhere, including stored romanization and
follow metadata. It does not contain `chordflask-genlyrics`, the LRCLIB client,
PyThaiNLP, ONNX Runtime, TLTK, or lyric-generation network functionality. See
[STANDALONE.md](STANDALONE.md) for the complete source/standalone comparison.

## Data, privacy, and copyright

`.lrc` and `.cho` sidecars remain local user files beside the media. ChordFlask
does not ship a lyrics database. Displaying existing lyrics performs no network
request. An explicit LRCLIB generation request sends metadata and duration to
the external LRCLIB service but never uploads the media itself.

Song lyrics may be copyrighted. Users are responsible for obtaining, storing,
and using lyric data lawfully and for complying with LRCLIB's service terms and
the rights applicable to their collection.

## Troubleshooting

- **`valid ChordFlask analysis is missing`:** run `chordflask-analyze` first.
- **`analysis has no beat timeline`:** regenerate or validate the analysis; see
  [ANALYSIS.md](ANALYSIS.md) and [MAINTENANCE.md](MAINTENANCE.md).
- **A same-stem `.lrc` is skipped:** ensure it is UTF-8 and contains usable
  `[mm:ss.xx]` timestamps; plain external LRC is not accepted.
- **Embedded lyrics are skipped:** inspect what the installed `ffprobe` exposes
  as format tags; raw SYLT data may not be available through that interface.
- **The wrong LRCLIB version matches:** use a more specific one-file `--tag`, or
  supply a correctly timed local `.lrc`.
- **The existing `.cho` is not updated:** rerun with `--force` only when replacing
  that user-owned sidecar is intended.
- **Lyrics displays but does not follow playback:** hand-written sheets and
  edited marker counts may lack valid ChordFlask beat-range metadata.
- **A romanization engine fails:** rerun `make setup`, select an engine supported
  by the current Python version, and do not expect an automatic fallback.
