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
