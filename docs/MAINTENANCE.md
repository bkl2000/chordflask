# Maintenance commands

`chordflask-maintain` inspects, repairs, and validates existing ChordFlask data
and installation state. It is a framework-free tool: it uses only the
`chordflask_base` model/schema layer and the Python standard library, so it
works without the web app, the analysis engine, or any audio library.
It neither imports nor requires PyThaiNLP, ONNX Runtime, or TLTK.

All commands are run from the repository root:

```bash
scripts/chordflask-maintain <subcommand> ...
```

## Read-only vs. modifying

| Command | Effect |
| --- | --- |
| `storage report` | **read-only** — prints a report, deletes nothing |
| `stems report` | **read-only** — reports Demucs stem storage, deletes nothing |
| `validate` | **read-only** — checks JSON, changes nothing |
| `doctor` | **read-only** — checks the installation, changes nothing |
| `storage cleanup` | **modifies files** — deletes only explicitly requested leftovers |
| `stems cleanup` | **modifies files** — deletes only unreferenced stem generations |
| `migrate-schema` | **modifies files** — rewrites analysis JSON to schema v3 |

Start with read-only commands. `doctor`, `validate`, and both report commands
are safe inventory/diagnostic operations. Cleanup and migration require an
explicit subcommand and target; no maintenance command silently repairs or
deletes an analysis merely because it was inspected.

## Storage report

```bash
scripts/chordflask-maintain storage report /path/to/music
```

Prints, for the directory's `.chordflask` storage, how many files and how much
space each category uses (analysis JSON, cached audio, MusicXML, MIDI,
leadsheet exports, temporary files, etc.) and its status. It never deletes
anything and never follows symlinks.

## Storage cleanup

```bash
scripts/chordflask-maintain storage cleanup /path/to/music --orphan-temp
scripts/chordflask-maintain storage cleanup /path/to/music --cached-audio
scripts/chordflask-maintain storage cleanup /path/to/music --corrupt-backups --older-than-days 30
scripts/chordflask-maintain storage cleanup /path/to/music --orphan-temp --cached-audio --dry-run
```

Cleanup is explicit and limited to one media directory (non-recursive). At
least one category flag is required:

- `--orphan-temp` — delete orphaned analysis/conversion temporary directories
  (refused while an analysis worker is active).
- `--cached-audio` — delete cached `.mp3` audio that ChordFlask can regenerate
  from a video source (refused while a worker is active).
- `--corrupt-backups` — delete corrupt-analysis backup files older than
  `--older-than-days N` (a positive number, required with this flag).

Valid analysis JSON, source media, and user-edited data are never deleted.
Use `--dry-run` first to show the candidates and totals without deleting
anything. Dry runs use the same lock checks and refusal rules as real cleanup.
External same-stem `.cho` sidecars are outside `.chordflask` storage and are
never inspected, rewritten, or deleted. This includes sidecars containing
`x_chordflask_romanized` metadata.

Corrupt-analysis backups are retained unless both `--corrupt-backups` and an
explicit positive `--older-than-days` retention age are provided. The age is
applied only to that backup category. Orphan temporary work is incomplete data
left outside the final analysis contract; cached audio is derived and can be
created again from its source video. Neither category includes source media,
valid JSON, exports, or Edited chord data.

## Stems report

```bash
scripts/chordflask-maintain stems report /path/to/music
```

Reports, for the directory's optional Demucs stem storage, which media have a
complete or incomplete `demucs:htdemucs` set, any missing referenced FLAC
files, unreferenced ("orphan") generation directories, and the total and
orphan disk usage. It is read-only and never follows symlinks.

## Stems cleanup

```bash
scripts/chordflask-maintain stems cleanup /path/to/music --orphans
scripts/chordflask-maintain stems cleanup /path/to/music --orphans --dry-run
```

Deletes only unreferenced generation directories under
`.chordflask/stems/demucs/htdemucs/`. It never deletes a generation referenced
by a valid analysis JSON, never touches chord/rhythm/user data, and never
deletes anything outside the stem storage directory. Cleanup refuses (deleting
nothing) when an analysis worker or a Demucs process is active, or when any
actual analysis JSON is unreadable/invalid, because orphan status cannot then
be proven safely. Non-analysis JSON files (for example `*.training.json`) do
not block cleanup. `--dry-run` shows what would be removed without deleting.

## Migrate schema

```bash
scripts/chordflask-maintain migrate-schema /path/to/music
```

Rewrites the `.chordflask/*.json` analysis files of one directory from older
schemas to the current schema v3, without reanalyzing the audio:

- schema 1 → 3
- schema 2 → 3
- unversioned legacy files that contain `base_chords` → 3
- files already at schema 3 are skipped
- non-analysis JSON files (for example `*.training.json`) are ignored silently

The migration is idempotent: running it again on an already-migrated directory
is a no-op. Each file is written atomically (fsync + `os.replace`), so a failed
or interrupted migration leaves the original file byte-for-byte unchanged. A
file's error never aborts the batch.

## Validate

```bash
scripts/chordflask-maintain validate /path/to/song.json
scripts/chordflask-maintain validate /music/videos
```

Loads each analysis JSON through the `chordflask_base` repository and reports
whether it is valid. A media directory validates every `.chordflask/*.json`
inside it. This is a pure check: nothing is changed or rewritten.

The shared model handles current schema-v3 chord and rhythm tracks, including
`user_edited`, `qm_barbeattracker_original`, and beat-grid correction metadata,
and optional `audio_tracks["demucs:htdemucs"]` stem data. Validation loads
these through the model, migration skips current schema-v3 files, and
storage/stem commands preserve valid analysis and referenced stem generations.
Queue and worker lock state, Demucs locks, logs, and media-local storage
categories remain separate and are handled only by the commands that explicitly
report or guard them.

## Doctor

```bash
scripts/chordflask-maintain doctor
```

Reports the installation state without changing anything:

- Python interpreter and version
- system `ffmpeg` on `PATH`
- the two required Vamp plugin binaries
- the global queue directory and whether it is writable

`doctor` intentionally checks only dependencies required for the core runtime.
It does not report the source-only lyrics/romanization packages. Those packages
are optional at application runtime and intentionally absent from standalone
builds; treating them as doctor failures would incorrectly mark a healthy
standalone as incomplete. The generator itself reports a clear error when a
requested romanization engine is unavailable, without importing or loading ML
packages during maintenance.

## Diagnosis and repair workflows

### Check an installation before touching collection data

```bash
chordflask-maintain doctor
```

Resolve missing FFmpeg, Vamp plugins, or an unwritable queue directory first.
`doctor` does not inspect media-local analyses.

### Validate one collection

```bash
chordflask-maintain validate /music/videos
chordflask-maintain storage report /music/videos
```

Validation identifies unreadable or structurally invalid analysis JSON. The
storage report provides category sizes and leftover status without deleting
anything. A corrupt analysis is not automatically overwritten: preserve any
reported backup, inspect the failure, then deliberately reanalyze the affected
media if regeneration is appropriate. See [ANALYSIS.md](ANALYSIS.md) for
replacement semantics and Edited-track preservation.

### Preview cleanup before applying it

```bash
chordflask-maintain storage cleanup /music/videos \
  --orphan-temp --cached-audio --dry-run
chordflask-maintain stems cleanup /music/videos --orphans --dry-run
```

Run the corresponding command without `--dry-run` only after reviewing the
candidates. Cleanup refuses ambiguous or active states instead of guessing.
Analysis worker locks and Demucs locks protect work that may still be owned by
a running process. If a refusal is unexpected, stop only the ChordFlask process
that owns that work and rerun the report; do not delete lock or queue files as a
generic repair step.

### Migrate old but valid analysis

```bash
chordflask-maintain validate /music/videos
chordflask-maintain migrate-schema /music/videos
chordflask-maintain validate /music/videos
```

Migration changes the storage schema, not musical analysis. It retains chord,
rhythm, user-edited, and other valid track data and uses atomic replacement.
Keep normal filesystem backups when migrating a valuable collection, even
though each individual failed write leaves its original unchanged.

## Exit codes

- `0` — success (all checks pass, nothing failed, or nothing to do)
- `1` — partial failure (cleanup refused or failed, an invalid analysis, or an
  incomplete installation)
- `2` — invalid invocation (missing/unknown argument, or a target that is not a
  file/directory)

`migrate-schema` exits `1` when at least one file failed; `doctor` exits `1`
when any check is missing; `validate` exits `1` when at least one file is
invalid.
