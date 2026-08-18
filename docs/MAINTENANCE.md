# Maintenance commands

`chordflask-maintain` inspects, repairs, and validates existing ChordFlask data
and installation state. It is a framework-free tool: it uses only the
`chordflask_base` model/schema layer and the Python standard library, so it
works without the web app, the analysis engine, or any audio library.

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

## Doctor

```bash
scripts/chordflask-maintain doctor
```

Reports the installation state without changing anything:

- Python interpreter and version
- system `ffmpeg` on `PATH`
- the two required Vamp plugin binaries
- the global queue directory and whether it is writable

## Exit codes

- `0` — success (all checks pass, nothing failed, or nothing to do)
- `1` — partial failure (cleanup refused or failed, an invalid analysis, or an
  incomplete installation)
- `2` — invalid invocation (missing/unknown argument, or a target that is not a
  file/directory)

`migrate-schema` exits `1` when at least one file failed; `doctor` exits `1`
when any check is missing; `validate` exits `1` when at least one file is
invalid.
