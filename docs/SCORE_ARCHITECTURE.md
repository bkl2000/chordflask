# ChordFlask Score (Phases 1–2)

Score is **Alpha / experimental**. The technical pipeline works, and Transkun
sometimes produces musically convincing MIDI transcriptions. The automatically
generated piano notation is often rhythmically cluttered and not reliably
readable as music; it is not a reliably playable piano score.

Score is an optional piano transcription producer. The lightweight
`chordflask_score` CLI orchestrates an isolated `~/.venvs/chordflask-score`
subprocess: Transkun → original MIDI → music21 → MusicXML → Verovio SVG pages.
Torch, Transkun and Verovio never load in the caller. Desktop can display
prepared Score generations without the optional runtime.
No mandatory core dependencies, chord exports or existing analysis tracks change.

## Rhythm and notation

The existing `rhythm_tracks["qm_barbeattracker"]` is the only rhythm source.
Times must be finite, nonnegative and strictly increasing; numbered beats must
advance cyclically through one fixed integer meter. Missing, ambiguous or
unusable grids fail. One numbered beat represents one quarter note; the meter
is rendered as N/4, consistent with the existing beat-count contract. Meter
changes are unsupported. A first beat numbered 3 in 4/4 produces a two-beat
pickup. Existing source provenance, when present, must match the original media.

Piecewise linear interpolation maps audio seconds to quarter positions. Each
beat interval defines its own tempo. The same inverse mapping defines measure
start/end seconds. No replacement grid or extrapolation is invented: notation
covers the first through last measured beat. Notes outside that interval are
omitted from notation, crossing notes are clipped, and counts are recorded.
Original MIDI bytes and original note/controller seconds remain unchanged.
`notes.json` captures Transkun events before MIDI serialization, avoiding MIDI
tick rounding of the original seconds. Model loading/inference and MIDI writing
use existing Transkun APIs without patched internals or custom post-processing.
The final measure can be incomplete; its time interval ends at the last QM beat.
Tempo directions retain every changed interval exactly, omitting repeated equal
values. Only the initial metronome label is printed; later changes use music21's
sound-only tempo marks, avoiding per-beat labels without changing timing.

music21 quantizes to sixteenths and eighth-note triplets, combines equal-onset,
equal-duration notes into chords, assigns other overlapping notes to voices,
fills rests and builds/ties measures. Rest-only extra voices are removed per
measure and music21 flattens single remaining voices. MIDI pitches <60 go to
the left hand with bass clef; >=60 to the right hand with treble clef. This is
a deliberately simple range heuristic, not an optimized fingering/voicing model.

Transkun recognizes individual note pitches, onset/end times, velocities and
controller events. `original.mid` preserves its MIDI output. The notation is a
separate derived representation: mapping onto QM beats, quantization, voice
assignment, ties, rests and hand separation can make it difficult to read even
when the MIDI sounds convincing. Short notes and overlaps can produce many
voices and rests; mixed straight/triplet rhythms have known tuplet-notation
limitations. Meter changes and inferred musical hand/phrase structure are not
supported. MIDI transcription quality does not establish notation quality.

## Audio and runtime

`original` decodes the media's first audio stream using existing canonical
FFmpeg extraction. `no-vocals` mixes existing current Demucs `other + bass +
drums`, using all three at equal gain. Missing/stale stems fail; Demucs is never
started. Container timeline facts are retained separately from decoded sample
time, following existing Demucs conventions; no unexplained timing offset is added.

`make setup-score` installs a self-contained producer in the separate runtime;
`make score-check` probes versions, weights, CUDA availability and resource
loading without inference/downloads. `make score SCORE_ARGS="..."` invokes the
portable installed helper. The Python 3.12 runtime is the verified target.
CPU and CUDA are explicit devices; `auto` selects available CUDA, otherwise CPU.
Code, library versions, packaged weights and configuration identify the pipeline.
The standalone excludes Score's CLI/worker and heavy dependencies; its lightweight
reader consumes persisted, validated SVG without this runtime.

Setup defaults to CPU Torch wheels. For CUDA wheels, set
`CHORDFLASK_SCORE_TORCH_INDEX_URL=https://download.pytorch.org/whl/cu128` before
setup. setuptools 80.9.0 is pinned because the upstream console command still
needs `pkg_resources`; diagnostics verify that import explicitly.

Examples (no manual venv activation):

```bash
make setup-score
make score-check
scripts/chordflask-score --dry-run /path/to/music
scripts/chordflask-score --device cpu /path/to/song.mp3
scripts/chordflask-score --audio-source no-vocals --replace /path/to/song.mp4
make score SCORE_ARGS="--dry-run /path/to/music"
```

For use from any directory, copy or symlink `scripts/chordflask-score` to a
directory on PATH. `CHORDFLASK_SCORE_VENV` selects an alternative runtime.
Directory batches follow the existing Demucs/Core selection: one file per
casefolded basename, preferring MP4 over MP3. An explicitly selected alternative
is rejected with the preferred filename, since QM analysis is shared by basename.

## Persistence and security

`.chordflask/scores/<filename-derived-key>/manifest.json` references an immutable
complete generation with `original.mid`, `notes.json`, `score.musicxml`,
`measures.json` and `page-NNNN.svg`. The key includes the full filename, avoiding
MP3/MP4 collisions. Per-media persistent flock excludes concurrent producers.
Artifacts are bounded and validated before generation rename; the atomically
written manifest is the completion marker and is published last. Failure keeps
the previous manifest/generation intact. Unreferenced generations are retained
conservatively; generic maintenance must not delete them as chord export caches.

CURRENT means inputs, code/notation settings, optional runtime identity and artifact
hashes/structure match. TODO means no completion manifest. STALE means changed
inputs/settings/pipeline or missing/changed artifacts. ERROR means invalid
prerequisites, malformed manifests or unsafe content/paths. Dry-run never creates
storage or requires the optional runtime; existing artifacts can be inspected
without it. Replacement requires `--replace`. Batch failures do not stop later
files; exit 1 reports processing/classification failures, exit 2 invalid invocation.
Requested/used devices and CUDA availability remain provenance; changing the
device selection alone does not invalidate an otherwise CURRENT generation.

All Score and referenced stem paths reject symlink components and traversal.
SVG validation rejects DTD/entities, script, foreignObject, event attributes,
external references, unsafe CSS and oversized documents; local fragment references
used by Verovio are allowed. MIDI, note records, MusicXML and measure/page metadata
are validated in the runtime and checked again at publication/read boundaries.
The source/rhythm/stem identities are rechecked before publication. Existing
analysis, Edited, Lyrics, journal and stem data are read only.

## Phase 1 verification and limits (2026-10-14)

The focused Score, packaging and standalone-gate pytest run passed 77 tests.
After the final tempo-label adjustment, the affected timing, storage/CLI and
runtime tests passed again (46 tests). Ruff, changed-shell `bash -n` checks and
`git diff --check` passed. The separate CPU runtime was installed and the portable
command exercised from an unrelated working directory through MP3 processing,
publication, CURRENT reuse and read-only dry-run; original analysis stayed byte-identical.
That two-second synthetic smoke input produced no notes: it verifies pipeline
execution, not transcription accuracy. Real Verovio output is covered by a
positive fixture; notation regressions use real music21 parsing.
The final source-provenance correction passed all 18 storage/CLI tests: changed
media with recorded QM provenance is STALE and requires reanalysis before replacement.

CUDA, long-file performance and transcription quality have not been evaluated.
No standalone build or GUI test was run. Python 3.12, one fixed meter, simple
hand separation, measured-beat coverage and conservative retention of old
generations remain deliberate limitations. `make check` remains the human
developer's final check; no commit, push or publication was performed.

## Desktop display (Phase 2)

At 1024 px and wider, the existing view switch offers Grid, available Lyrics,
and Score when the active media has a complete valid generation. The existing
view preference also accepts Score; songs without it fall back to Grid without
forgetting that preference. Tablet and phone retain their existing views.
Loading media reads persisted data only; it never starts transcription.

Prepare → Score uses the existing background preparation manager and the
installed external `chordflask-score` helper. Capability checking runs
`chordflask_score.worker --check` in that runtime's isolated interpreter,
with the existing 60-second capability cache. Generation uses original audio,
auto device selection, and explicit replacement of stale output. Advanced
no-vocals/device choices remain CLI options. A valid prepared score is readable
without the helper. After a source upgrade, rerun `make setup` to refresh the
installed package discovery, including the lightweight Score modules.

`GET /score?media=…` returns generation, page count and stored measure intervals.
`GET /score/page/N?media=…&generation=…` returns one validated SVG. The media
must match the active client song before and after reading; no arbitrary file
path is served. Existing input identities, artifact hashes, bounded parsers,
path checks and SVG validation are reused. Missing, modified, unsafe and stale
inputs/artifacts fail closed. Display deliberately accepts producer upgrades:
code/runtime freshness determines regeneration, not readability of intact
persisted notation. Integrity checks run outside the playback lock. Display reuses the existing
bounded media-identity cache while device, inode, size, mtime and ctime match;
QM data and all generation artifacts are still validated on each request.
Producer snapshots remain uncached.

SVG pages live in separate same-origin object documents, with a restrictive
CSP and nosniff; they are never inserted as HTML into the application. Engraved
content bounds fit the available panel width. Existing `svg_id` and `page`
metadata identifies each measure; its Verovio `system` ancestor identifies the
notation line, so Phase 1 needs no new metadata. Both piano staves remain as
engraved. Previous/Next supports manual page browsing. The selected page stays
until the active playback measure changes, including while paused and before
the first measured interval. A seek or repeat into another measure resumes
automatic page following.

The existing `syncPlaybackPosition` calls Score with the media element's
`currentTime`, without Grid's anticipatory display lead. Stored half-open audio
intervals `[start_seconds, end_seconds)` select the measure, including pickup
measure zero. A translucent rectangle marks the whole measure. Only notation
line changes scroll; page changes fetch the appropriate page. Seek, repeat,
pause/resume and song changes use the existing playback events and scheduler;
Score adds no timer. Outside measured coverage no measure is highlighted.
Late metadata and page responses are discarded after a song reset.

Source wheels and standalone/.deb payloads include the reader and Score
JavaScript. The shared standalone build/gate excludes Score CLI/worker,
Transkun, Verovio, pretty_midi and the existing heavy runtimes/weights.
The pre-existing Core music21 dependency remains for chord exports.
No new core dependencies or separate Debian rendering path are needed.


## MIDI export

The existing Export menu distinguishes **Chord MIDI** (chord accompaniment from
the displayed chord analysis, not the actually performed individual notes) from
**Score MIDI** (Transkun's original detected notes). Score MIDI is hidden entirely
without a valid current active generation. **All formats (.zip)** keeps all four
previous chord formats and adds `<song>-score.mid` only when available.

Both GUI and CLI use `chordflask.score.read_score_midi` and the existing validated
Score reader. Only `manifest.json` selects the active generation; timestamps,
directory ordering and historical generations never select an export. Retained
older generations are not fallbacks: they may describe different source audio,
rhythm or pipeline decisions. A missing manifest, missing/changed artifacts,
stale source/QM/stem inputs or unsafe data make Score MIDI unavailable. Artifact
hashes/structure, pipeline fingerprint and input identities must match; exported
MIDI bytes and the manifest are rechecked after validation.

Producer **CURRENT** additionally checks code/settings and, when supplied,
runtime identity as described above. Export follows the existing display
contract: intact persisted generations remain readable across producer upgrades;
code/runtime freshness controls regeneration, not access to original MIDI. This
avoids requiring excluded producer source files or an installed Transkun runtime
in standalone and Debian players. Missing or stale input/artifact data are never
accepted merely because a historical MIDI file still exists.

```bash
chordflask-export --format midi SONG.mp3
chordflask-export --format score-midi SONG.mp3
chordflask-export --format all /path/to/music
```

`midi` preserves the existing `<song>-chords-<track>.mid` export. `score-midi`
copies only the validated original MIDI to `.chordflask/<song>-score.mid`; missing,
stale or invalid Score data produce a clear error, with no new analysis. Chord
track/display/transposition options do not alter it. `all` writes the previous
formats plus optional Score MIDI and skips unavailable Score data without error.
Single-file and non-recursive directory exports use the same selection; batches
continue after per-file errors (exit 1). The default remains `both` (Markdown/PDF).
No export starts Transkun transcription. Existing chord exports retain their
existing ability to create missing chord analysis. See [helper options](HELPERS.md)
and [command-line export](ANALYSIS.md#command-line-export).

### Installation verification (2026-10-14)

`make setup` successfully refreshed the existing editable Core installation.
From `/tmp`, the normal `~/.venvs/chordflask/bin/python -I` imported both
`chordflask_score` and `chordflask.score` with PYTHONPATH unset. No product
path injection, interpreter override or setup change is necessary.
The normal repository `scripts/chordflask` launcher was exercised from `/tmp`,
also without PYTHONPATH or CHORDFLASK_PYTHON overrides, for Score SVG display.

Packaging includes the lightweight Score reader modules through the existing
import graph and packages `static/score.js` in both wheels and the standalone.
The focused archive-gate tests reject ML runtimes/weights and Score CLI/worker
while allowing reader modules and the pre-existing music21 Core dependency.
A newly built executable/.deb has not been verified: the existing standalone
build script rejects uncommitted tracked changes. This gate is preserved;
artifact acceptance remains after the maintainer's commit. `make standalone`
also depends on `make check`, which was not authorized or run in this task.


### Review verification limits

The Node regression exercises Previous/Next, repeated scheduler calls, pickup,
seek/repeat and view changes with a small DOM. It does not verify real browser
SVG geometry. Manual acceptance with a long real score must check page-change
latency and highlight placement. After committing, standalone/.deb acceptance
must also load `/static/score.js`, display Score and return to Grid in a freshly
built payload. Packaging configuration and source HTTP serving are tested;
a fresh frozen executable has not been built during review corrections.
