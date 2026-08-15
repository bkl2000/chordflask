# Helper Classification

This document classifies files under `flask/helpers/`. It does not move files
or change runtime behavior. The active Flask GUI does not import these helpers
directly.

## Supported CLI Helpers

These are kept as usable command-line tools and have smoke-test coverage.

- `batch_core.py` - batch serial/parallel execution helpers; media discovery is
  shared with the active app through `flask/media_library.py`.
- `chordbatch.py` - serial batch analyzer entry point for MP3, MP4, and WebM
  files, including the active same-stem priority.
- `chordbatch_mp.py` - multiprocessing batch analyzer entry point.
- `chordleadsheet_batch.py` - serial batch leadsheet exporter. It discovers
  MP3/MP4/WebM files non-recursively, reuses valid analysis JSON, analyzes only
  missing files serially, and atomically writes matching
  `.chordflask/<name>-chords-<track>.md` and `.pdf` files. One failing file does not
  stop later files. Exit code 0 means all exports succeeded, 1 means partial
  or per-file errors, and 2 means invalid invocation or a missing directory.
  Options: `--chord-track auto|original|edited|TRACK_ID` (default `auto` =
  Edited when present, otherwise Chordino), `--rhythm-track TRACK_ID` (default
  `qm_barbeattracker`), `--transpose N`, `--sharps`, `--unicode`,
  `--repeat-mode changes|chords` (default `changes`), and
  `--no-metric-chords` to disable the enabled-by-default rhythm-aware
  smoothing. The leadsheet uses aligned monospace beat fields, two complete
  measures per row, and extra space after every eight measures. The helper
  never imports Flask or starts the server.

  ```bash
  ~/.venvs/chordflask/bin/python flask/helpers/chordleadsheet_batch.py /path/to/collection
  ```

- `create_sheet_pdf.py` - thin command-line wrapper around the shared PDF
  renderer used by browser Save and the batch helper. Pillow is its only PDF
  dependency; the open-licensed fonts are bundled with ChordFlask.

  ```bash
  python flask/helpers/create_sheet_pdf.py leadsheet.md
  python flask/helpers/create_sheet_pdf.py leadsheet.md -o leadsheet.pdf
  ```

## Legacy Or Experimental Analyzer Variants

These overlap with the active analyzer in `flask/chordanalyzer.py`. New fixes
should go into the active analyzer unless there is an explicit reason to revive
one of these variants.

- `chordanalyzer_mp.py` - older multiprocessing analyzer variant.
- `chordanalyzer_quantized_patch.py` - alternate analyzer with quantization
  experiments.
- `chordlogic.py` - small standalone wrapper/demo around `ChordData`.

## Standalone Analysis Experiments

These are standalone scripts for exploration or one-off analysis. They are not
part of the active Flask app path.

- `analyze_pitch.py` - pitch variation inspection for audio files.
- `getscale.py` - Vamp key detector experiment.
- `process_audio.py` - vocal/instrumental separation experiment.
- `liverecord.py` - live recording and live chord-analysis experiment.

## Conversion And Compatibility Utilities

These may be useful for data preparation or local compatibility work, but they
are not required by the active GUI.

- `convert_chordlabels_to_cnn.py` - converts ChordFlask chord JSON into a
  CNN-training-oriented format.
- `romanize.py` - Thai romanization helper; requires `pythainlp`, which is not
  part of the active dependency set.

## Local Media Shell Helpers

These are local convenience scripts. Their naming and behavior should be
reviewed before treating them as supported tools.

- `webm2mp4` - converts `.webm` files in the current directory to `.mp4`.
- `youtube_donwload` - downloads a 720p MP4 using `yt-dlp`; filename contains a
  typo kept for compatibility with the current file.

## Production Boundary

The active production `ChordAnalyzer` lives in `flask/chordanalyzer.py` (facade
over `media_converter.py`, `audio_analyzer.py`, `chord_exporter.py`, and
`analysis_service.py`). The three legacy analyzer variants below each define
their own `ChordAnalyzer` class and must NOT be imported by the main Flask app
or worker.

Do not import from `flask/helpers/` into the active `flask/` app modules. The
active GUI, worker, and analysis service import only from the main `flask/`
modules. Tests may import helpers for standalone testing.

## Maintenance Rule

Keep new production behavior out of `flask/helpers/` unless it is explicitly a
supported CLI helper. Active GUI and analyzer behavior should live in the main
`flask/` modules and be covered by tests.
