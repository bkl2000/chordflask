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

Desktop ChordFlask (1024 px and wider) shows **Prepare: Lyrics** for the
currently loaded song when a usable Lyrics helper is available. Set up the
standard external runtime with `make setup-lyrics`; diagnose it with
`make lyrics-check`. The default location is `~/.venvs/chordflask-lyrics`,
overridable with `CHORDFLASK_LYRICS_VENV`. The application runs its helper in the
background with its normal `.lrc` → embedded → LRCLIB defaults and makes the
new `.cho` available without restarting ChordFlask. Directory generation
remains a command-line workflow. Source installations also accept the helper
beside their current Python interpreter for compatibility. Frozen builds use
only the external runtime. Tablet/phone layouts show no Prepare control.

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

## Local Lyrics V2 (Qwen3)

V1 uses the existing LRC / embedded / LRCLIB workflow and writes `song.cho`.
V2 recognizes audio locally with official **Qwen3-ASR-1.7B**, then synchronizes
that recognized text using **Qwen3-ForcedAligner-0.6B**, and writes
`song.v2.cho`. Both remain independently editable, normal ChordPro files beside
the original media. The shared `chordflask.lyrics_paths.lyrics_path` function
owns these paths. No original media or analysis JSON is changed.

```bash
make setup-qwen3-asr
make qwen3-asr-check
chordflask-genlyrics --analyzer qwen3 song.mp3
chordflask-genlyrics --analyzer qwen3 --replace song.mp3
chordflask-genlyrics --analyzer qwen3 --dry-run --track chordino song.mp3
chordflask-genlyrics --analyzer qwen3 --recursive ~/Music
chordflask-genlyrics --retry-failed ~/Music
```

The generator must be installed from the current source (`make setup`, or
`make setup-lyrics` for the external Lyrics helper). Qwen setup installs only
the isolated inference runtime; it does not modify the other runtimes. An
external Lyrics helper can invoke its installed V2 CLI directly with
`~/.venvs/chordflask-lyrics/bin/chordflask-genlyrics --analyzer qwen3 song.mp3`.

**Python compatibility**

Lyrics V2 currently supports Python 3.10–3.13 (Python 3.12 recommended).
Python 3.14, the default on Ubuntu 26.04, is not yet supported by this optional
setup.

For a compatible interpreter, see
[optional Python 3.12 installation with uv](COMPATIBILITY.md#optional-python-312-with-uv),
including interpreter selection and existing runtime venvs.

The default venv is `~/.venvs/chordflask-qwen3-asr`, configurable with
`CHORDFLASK_QWEN3_VENV`. Setup defaults to Python 3.12. It installs `qwen-asr==0.0.6`
(the reviewed API, requiring Transformers 4.57.6), PyTorch and two model
snapshots under that venv's `models/`. Repeat setup reuses the venv and
Hugging Face downloads. Installation needs internet access and sufficient
free disk space. Inference uses local model paths and forces Hugging Face /
Transformers offline mode. No API service, URL audio input or upload is used.

On a compatible CUDA GPU/wheel, inference uses FP16 CUDA. Otherwise it uses
FP32 CPU. No FlashAttention or vLLM is required. To force a CPU test:

```bash
CUDA_VISIBLE_DEVICES='' chordflask-genlyrics --analyzer qwen3 song.mp3
```

For CPU-only PyTorch wheels, set
`CHORDFLASK_QWEN3_TORCH_INDEX=https://download.pytorch.org/whl/cpu` during setup.
The same override can select an appropriate official CUDA wheel index for the
installed driver. Existing runtime wheels are reused; choose a fresh venv if
changing the wheel family. CPU inference can be slow and memory intensive.
ASR and aligner models are loaded sequentially to avoid retaining both models
at once. Check reports Python/package versions, model weights and CPU/CUDA
selection; it performs no downloads, installations or model inference.
Missing runtime/weights, incompatible APIs, decoding errors, memory failures,
empty results and invalid synchronization fail without publishing a sidecar.

ASR detects language independently for each 30-second audio chunk and prints
it in diagnostics. A separate alignment-language check requires both official
support and the installed model's advertised support. Current supported
alignment languages are Chinese, English, Cantonese, French, German, Italian,
Japanese, Korean, Portuguese, Russian and Spanish. ASR supports more languages;
**Thai cannot currently produce V2**. Unsupported or unrecognized languages
abort the whole song without a fallback or partial V2 file.

Text recognition (`recognize_text`) and synchronization (`align_text`) are
separate, small processing steps. Audio is decoded temporarily to mono 16 kHz
PCM; both steps use identical sample ranges. Chunk offsets derive from sample
positions in the source, not beats. The aligner supplies word/character starts
and ends. The official Qwen3 timestamp correction is used unchanged as part
of forced alignment: it restores a nondecreasing sequence, using neighbouring
anchors or interpolation for outliers. This model post-processing is not an
invented beat-timing fallback. V2 validates the corrected output and rejects
missing words, incomplete coverage, non-finite/negative times, reversed or
overlapping spans and out-of-audio boundaries. An individual word may have
`start == end` after model quantization/correction; its text and point timestamp
are retained without adding duration. Entirely collapsed alignment or a lyric
row without a positive time span is rejected. Model-aligned token starts form
readable rows; ends delimit gaps through existing blank timed-line support. The
existing beat mapping, chord markers, romanization, ChordPro rendering and
parser validation are reused. ChordPro provenance records analyzer, model,
alignment method, recognized languages, CPU/CUDA and audio input.

When the existing Demucs producer validates a complete current stem set,
V2 uses its vocals. Otherwise V2 uses original audio. It never triggers
separation or creates persistent stem copies; diagnostics and provenance name
the selected input. Temporary decoded audio is removed on success/failure.

The official ASR lists singing voice and songs with background music as input;
the aligner documents **speech**, not reliable singing alignment. Recognition
can hallucinate or miss words, especially with music; timestamp validation
cannot prove a transcript is correct. Instrumental chunks with empty ASR text
are skipped and an entirely empty song fails. Strong accompaniment, held
notes, repetition and chunk boundaries can reduce accuracy or make strict
alignment fail. No quality guarantee or automatic quality scoring is provided.
The 30-second chunking limits attention memory and stays below the aligner's
300-second input limit; it can cut sung words at boundaries. Results need
listening and manual review. There are no speculative tuning or fallback models.

Desktop displays V1 or V2 directly when only one exists, and a compact
**Lyrics V1 / Lyrics V2** selector when both exist. Switching preserves player
position and playback, transposition and beat following. Export reads the
selected sidecar. Version selection stays in browser memory, with no persisted
per-song state. Deleted V2 falls back to V1 on the next sheet request/song
reload; returning focus to the desktop Lyrics view refreshes the sheet.
Late replies for another song/version are discarded. Smartphone UI is unchanged;
desktop Prepare still creates V1 only.

`--replace` replaces only the selected version. `--force` remains a compatible
alias. Without either option, an existing target
(including one created while ASR runs) is preserved. `--dry-run` performs ASR,
alignment and rendering without writing. `--track`, batch, `--recursive` and
romanization continue through the shared pipeline. Retry uses the existing
root-scoped failure log and its saved analyzer/options; old logs mean V1.
Explicit options that conflict with saved retry options are rejected.
`--lyrics` and `--tag` are V1-only and rejected with Qwen even if the explicit
source list equals the default. There is no LRCLIB-text-plus-Qwen-alignment
option. Keeping text and timing separate allows a future independent text
source without implementing providers, plugins or another storage format today.

Remove V2 completely by deleting its ordinary sidecar:

```bash
rm -- song.v2.cho
# All V2 sidecars in the current directory:
rm -- *.v2.cho
# Recursively (review the target directory first):
find ~/Music -type f -name '*.v2.cho' -delete
```

V1 and runtime models are unaffected. `chordflask-maintain` is unchanged.
Core, standalone and DEB can read both versions; generation requires the
external CLI plus Qwen venv. No Torch packages or model weights are bundled.

API, language and license references: [official Qwen3-ASR documentation](https://github.com/QwenLM/Qwen3-ASR),
[official forced-aligner implementation](https://github.com/QwenLM/Qwen3-ASR/blob/main/qwen_asr/inference/qwen3_forced_aligner.py),
[ASR model card](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) and
[aligner model card](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B).
Both models and the Qwen package use Apache-2.0; setup preserves the official
model cards, including their license metadata, with the external snapshots.

### CPU integration test (2026-10-11)

One real offline CPU run used the existing `videos/Starsailor - Alcoholic.mp3`
(195.845 seconds) on an AMD Ryzen 5 5625U, 6 cores / 12 logical CPUs, about
30 GiB system RAM. `CUDA_VISIBLE_DEVICES=''` forced CPU. Python 3.12.3,
qwen-asr 0.0.6, PyTorch 2.14.1, Transformers 4.57.6, SoundFile 0.14.0 and
Accelerate 1.12.0 were installed in the separate Qwen venv; both official models
were downloaded and checked locally. The model snapshots were downloaded from
the official model repositories on the test date. Setup/download time is not
included in the inference measurement.

| Measurement | Result |
| --- | --- |
| End-to-end generator wall time | 119.98 seconds |
| Maximum RSS (`/usr/bin/time -v`, subprocess tree) | 13,646,920 KiB (13.01 GiB) |
| User / system CPU time | 494.63 / 13.93 seconds |
| Detected language | English in all seven audio chunks |
| Actual ASR | Completed on CPU |
| Actual forced alignment | Own raw-timestamp override rejected a nonmonotone sequence; chunk not identified in the saved log |
| V2 publication | Rejected; no `.v2.cho` file generated |
| Audio, existing V1 and analysis JSON | SHA-256 unchanged before/after |
| CUDA | Not tested; RTX 4070 validation remains deferred |

This historical failure did not demonstrate that singing alignment was
unusable: the integration had disabled official Qwen3 timestamp correction.
The saved log also predates the worker's chunk-specific error diagnostics, so
the claim that the failure occurred in the first chunk was not substantiated.
Its exact worker revision was not recorded. The raw sequence and transcript
were not saved, so that run cannot retrospectively identify which values
required correction. The targeted follow-up below supersedes that diagnosis.


### Targeted alignment correction (2026-10-11)

A read-only diagnosis compared the current worker with the actually installed
qwen-asr 0.0.6 implementation. The integration's replacement of `fix_timestamp`
was the problem: it rejected raw outliers before the aligner's normal correction.
The follow-up used only the first 30 seconds of the same song, plus a 4.928-second
English control generated by the already installed eSpeak (synthetic speech,
not a natural-speech benchmark). CPU and offline mode were retained; no model,
chunking or inference settings were changed. Diagnostic observation called the
original correction and returned its result unchanged.

| Input | Raw timestamp count | Adjacent backward jumps | Largest backward jump | Values changed upstream | Largest correction | Point words (`start == end`) |
| --- | --- | --- | --- | --- | --- | --- |
| Singing, 0–30 s | 26 | 2 | 560 ms | 2 | 560 ms | 1 |
| Synthetic English speech | 32 | 2 | 80 ms | 2 | 80 ms | 1 |

Both corrected sequences are nonnegative, nondecreasing and within their audio
boundaries. The old validation still rejected a single collapsed word in each.
The fix removes the integration's timestamp override, preserves the official
correction unchanged, and accepts individual point words without deleting text
or inventing duration. Entirely collapsed results or collapsed lyric rows,
negative/non-finite times, real backward boundaries, overlaps and out-of-audio
segments remain errors. No arbitrary quality threshold or replacement
interpolation was introduced.

The corrected real CLI generated two valid lyric lines for a lossless 30-second
MP4 cut in `/tmp/qwen3-alignment-review/singing.v2.cho`, using a temporary copy of
the existing song analysis. The original media and V1 were not modified; no
partial result was published alongside the full original song. A test V1 beside
the temporary clip was also preserved, including on the V2-only forced rerun.
The final worker and bridge SHA-256 identities were recorded before the test and
confirmed unchanged afterwards. That final CPU run took 24.46 seconds with a
maximum RSS of 13,646,432 KiB (13.01 GiB), excluding setup/download time.

Sample word spans are 20.560–20.880 s for the first word, 23.520–24.240 s for the
last word of the first phrase, and 24.800–24.800 s for the next phrase's first
word. The last word ends at 28.160 s. The resulting lyric rows span
20.560–24.240 s and 24.800–28.160 s before the existing beat-grid mapping. These
starts, pauses, ordering and end bounds are structurally plausible; recognized
phrases match the corresponding text in existing V1. V1's beat-assigned timing
is not treated as timing ground truth. No listening acceptance of individual
word times was performed. One short successful cut supports technical pipeline
compatibility, not reliable singing alignment for arbitrary songs. CUDA and
natural speech remain untested.

Raw sequences, transcripts, time measurements, SHA-256 code identities and the
validated sidecar are temporary artifacts under `/tmp/qwen3-alignment-review/`.
The observed raw correction counts above come from the instrumented diagnosis;
the publication test invokes the unmodified official correction via the actual
CLI. Normal regression tests mock the ML runtime and use recorded upstream
correction input/output, including a point word. They require no models or GPU.

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
chordflask-genlyrics [--dry-run] [--replace] [--tag SEARCH_TEXT]
                     [--lyrics SOURCES] [--track TRACK_ID]
                     [--romanize]
                     [--romanize-engine thai2rom_onnx|royin]
                     TARGET
```

`TARGET` is one MP3, MP4, or WebM file or one directory. Directory processing
is non-recursive and applies the normal same-stem preference: MP4, then WebM,
then MP3 when several supported files would share one analysis and `.cho`.

- `--lyrics SOURCES` selects and orders `lrc`, `embedded`, and `lrclib`.
- `--tag SEARCH_TEXT` supplies a manual LRCLIB search hint for one file.
- `--track TRACK_ID` selects the chord snapshot; default `auto` prefers
  `user_edited`, otherwise the active/default track, then Chordino as needed.
- `--replace` atomically replaces an existing same-stem `.cho`; `--force` is a
  backwards-compatible alias.
- `--dry-run` performs analysis loading, source lookup, alignment, rendering,
  and validation but writes nothing. It does not guarantee that a later
  filesystem write will succeed.
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
chordflask-genlyrics --replace song.mp3
```

An existing `.cho` is skipped before analysis or network lookup unless
`--replace` (or its `--force` alias) is present. For directory runs, one missing
analysis, unavailable track, unusable lyrics source, network error, or
romanization error is reported as `FAILED`; processing continues and the
command exits 1 if any file failed.
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
rendered as distinct lines so every source timestamp retains its own activation
range. Whitespace-only timed entries close the preceding range and create an
instrumental gap without becoming visible lyric rows.

Within a mapped lyric passage, chord markers represent actual analyzed chord
changes. A chord already sounding when a new timed line starts is repeated at
that line's mapped beat, so lyric activation does not depend on a musical chord
change. Later marker positions retain their time-based estimate but snap to a
word boundary. Each generated marker is mapped to its analyzed beat range,
which lets playback highlight the correct occurrence even when chord names
repeat. A genuine instrumental gap is left unmapped, so the highlight clears
until the next mapped passage. Seek and view switches use the same player
position synchronization as Grid; Lyrics adds no second playback clock.

Generated files contain ordinary ChordPro markers plus non-display provenance
and synchronization directives:

- `x_chordflask_track` records the selected chord-track snapshot;
- `x_chordflask_line` records the next lyric line's exclusive beat range;
- `x_chordflask_beats` maps markers on the next line to analyzed beat indexes;
- `x_chordflask_end` closes the final marker's exclusive beat range;
- `x_lrclib_search` records an explicit LRCLIB hint when used;
- `x_chordflask_romanized` belongs to the immediately following original lyric
  line.

Other ChordPro readers can ignore these unknown directives. Older and
hand-written `.cho` files without `x_chordflask_line` retain their existing
chord-marker synchronization behavior. Hand editing that changes the number of
chord markers without updating its mapping disables precise chord
synchronization for that line only; the line still renders. The analysis JSON
always remains authoritative.

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
| `thai2rom_onnx` | Default PyThaiNLP neural transliteration; installed in the external Lyrics runtime with ONNX Runtime and no PyTorch requirement. |
| `royin` | PyThaiNLP's RTGS-oriented alternative; available from the same external runtime. |

Select one explicitly:

```bash
chordflask-genlyrics --romanize --romanize-engine thai2rom_onnx song.mp3
chordflask-genlyrics --romanize --romanize-engine royin song.mp3
```

There is no silent engine fallback. An unavailable or failing requested engine
reports an error for that file. Details of the supported Python matrix are in
[COMPATIBILITY.md](COMPATIBILITY.md#python-version-policy).

Romanization is experimental pronunciation assistance, not IPA and not an
authoritative representation of Thai tones. Word segmentation, names, loan
words, and unusual vocabulary can produce poor or varying results. Always keep
the original lyric as the reference.

## Standalone behavior

The standalone contains the core `.cho` parser and desktop Lyrics display, but
not `chordflask_lyrics`, an LRCLIB client, PyThaiNLP, or ONNX Runtime.
When `~/.venvs/chordflask-lyrics/bin/chordflask-genlyrics` is installed, the
desktop Prepare action invokes that external helper, so local LRC, embedded,
LRCLIB, and any romanization supported by that runtime remain available. See
[STANDALONE.md](STANDALONE.md) for the complete source/standalone comparison.

## Data, privacy, and copyright

`.lrc` and `.cho` sidecars remain local user files beside the media. ChordFlask
does not ship a lyrics database. Displaying existing lyrics performs no network
request. An explicit LRCLIB generation request sends metadata and duration to
the external LRCLIB service but never uploads the media itself.

Because these lyrics files live beside the media, a single-media
`chordflask-maintain storage report` does not include them.

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
- **Lyrics follow consistently but several seconds late or early:** a
  syntactically valid, monotonic local LRC is not necessarily synchronized to
  the actual media. Audio and lyrics from different releases, masters, or
  providers can have incompatible timelines. Before changing ChordFlask's
  synchronization code, compare another lyrics source. To replace one `.cho`
  using LRCLIB only:

  ```bash
  chordflask-genlyrics --replace --lyrics lrclib "Artist - Song.mp3"
  ```

  For an existing library of `.cho` files, `scripts/regenerate-lyrics.sh`
  recursively regenerates only sidecars with same-stem media, using the
  deliberate bulk priority `lrclib:lrc:embedded`. The normal
  `chordflask-genlyrics` default remains `.lrc` → embedded → LRCLIB.
- **The existing `.cho` is not updated:** rerun with `--replace` (or the
  compatible `--force` alias) only when replacing that user-owned sidecar is
  intended.
- **Lyrics displays but does not follow playback:** hand-written sheets and
  edited marker counts may lack valid ChordFlask beat-range metadata.
- **A romanization engine fails:** rerun `make setup-lyrics`, select an engine supported
  by the current Python version, and do not expect an automatic fallback.
