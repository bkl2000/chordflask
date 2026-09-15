# Helper Classification

This document classifies files under `chordflask/helpers/`. It does not move files
or change runtime behavior. The active Flask GUI does not import these helpers
directly.

## Supported CLI Helpers

These are kept as usable command-line tools and have smoke-test coverage.

- `analyze_cli.py` - the `chordflask-analyze` command. Chordino is the default
  built-in analyzer and runs in-process through the canonical
  `AnalysisWorker`/`ChordAnalyzer` path. Wrapper: `scripts/chordflask-analyze`.

  ```bash
  scripts/chordflask-analyze /path/to/collection
  ```

- `export_cli.py` - the `chordflask-export` command. It exports one media file
  or a whole directory as playable Markdown and print-ready A4 PDF leadsheets.
  It reuses valid analysis JSON, analyzes only missing files serially, and
  writes matching `.chordflask/<name>-chords-<track>.md` and `.pdf` files. One
  failing file does not stop later files. Exit code 0 means all exports
  succeeded, 1 means partial or per-file errors, and 2 means invalid invocation
  or a missing directory. Options: `--format markdown|pdf|both` (default
  `both`), `--chord-track auto|original|edited|TRACK_ID` (default `auto` =
  Edited when present, otherwise Chordino), `--rhythm-track TRACK_ID` (default
  `qm_barbeattracker`), `--transpose N`, `--sharps`, `--unicode`,
  `--repeat-mode changes|chords` (default `changes`), and `--no-metric-chords`
  to disable the enabled-by-default rhythm-aware smoothing. The leadsheet uses
  aligned monospace beat fields, two complete measures per row, and extra space
  after every eight measures. The helper never imports Flask or starts the
  server. Wrapper: `scripts/chordflask-export`.

  ```bash
  scripts/chordflask-export /path/to/collection
  ```

- `chordflask_lyrics/` - the source-installation-only
  `chordflask-genlyrics` command. It uses standard-library HTTP calls to fetch
  synchronized lyrics from LRCLIB on demand, requires existing ChordFlask
  analysis, and writes a same-stem `.cho` beside each media file. Directory
  discovery uses the application's non-recursive preferred-media rules. The
  `--tag SEARCH_TEXT` lookup hint is accepted only for a single file. `--track
  TRACK_ID` selects the chord-track snapshot (`auto` by default: valid
  `user_edited`, then the analysis active/default track, then `chordino`). An
  explicit missing track fails for that file without fallback. `--force`
  permits replacement of an existing `.cho`; `--dry-run` performs lookup,
  alignment, and rendering without writing. Directory failures do not stop
  later files. Wrapper: `scripts/chordflask-genlyrics`. This package is
  explicitly excluded from the standalone and uses the normal ChordFlask
  environment rather than a separate LRCLIB environment. Normal LRCLIB lookup
  needs no API key, and generated lyrics remain local user data.

  ```bash
  scripts/chordflask-genlyrics song.mp3
  scripts/chordflask-genlyrics /music/album
  scripts/chordflask-genlyrics --tag "Artist Song Title" song.mp3
  scripts/chordflask-genlyrics --track auto song.mp3
  scripts/chordflask-genlyrics --track btc song.mp3
  scripts/chordflask-genlyrics --force --track user_edited song.mp3
  scripts/chordflask-genlyrics --dry-run /music/album
  ```

- `batch_core.py` - shared non-recursive media discovery (MP4/WebM/MP3 with the
  active same-stem priority) used by `analyze_cli.py`, `export_cli.py`, and
  `chordleadsheet_batch.py`; backed by `chordflask/media_library.py`.

- `chordleadsheet_batch.py` - the leadsheet library used by `export_cli.py`. It
  holds the shared render/write logic and the export option definitions; new
  code should use `chordflask-export` rather than running this module directly.

## Production Boundary

The active production `ChordAnalyzer` lives in `chordflask/chordanalyzer.py`
(facade over `media_converter.py`, `audio_analyzer.py`, `chord_exporter.py`,
and `analysis_service.py`).

Do not import from `chordflask/helpers/` into the active application modules.
The GUI, worker, and analysis service use the main `chordflask` package. Tests
may import helpers for focused CLI testing.

## Maintenance Rule

Keep new production behavior out of `chordflask/helpers/` unless it is
explicitly a supported CLI helper. Active GUI and analyzer behavior should
live in the main `chordflask` package and be covered by tests. Portable scripts
under `scripts/` select the project venv and execute the installed console
entries; they do not make these modules importable with `PYTHONPATH`.
