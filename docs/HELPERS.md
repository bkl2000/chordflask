# Helper Classification

This document classifies files under `chordflask/helpers/`. It does not move files
or change runtime behavior. The active Flask GUI does not import these helpers
directly.

## Supported CLI Helpers

These are kept as usable command-line tools and have smoke-test coverage.

- `analyze_cli.py` - the `chordflask-analyze` command. Chordino is the default
  built-in analyzer and runs in-process through the canonical
  `AnalysisWorker`/`ChordAnalyzer` path. Wrapper: `scripts/chordflask-analyze`.
  `--source bass|drums|other|vocals` analyzes one registered Demucs stem
  instead and stores a separate `chordino_stem_<stem>` chord track.

  ```bash
  scripts/chordflask-analyze /path/to/collection
  ```

- `export_cli.py` - the `chordflask-export` command. It exports one media file
  or a whole directory as playable Markdown, print-ready A4 PDF, or lyric-free
  ChordPro leadsheets.
  It reuses valid analysis JSON, analyzes only missing files serially, and
  writes matching `.chordflask/<name>-chords-<track>.md`, `.pdf`, and/or `.cho`
  files. One failing file does not stop later files. Exit code 0 means all exports
  succeeded, 1 means partial or per-file errors, and 2 means invalid invocation
  or a missing directory. Options: `--format markdown|pdf|both|chordpro|all` (default
  `both`), `--chord-track auto|original|edited|TRACK_ID` (default `auto` =
  Edited when present, otherwise Chordino), `--rhythm-track TRACK_ID` (default
  `qm_barbeattracker`), `--transpose N`, `--sharps`, `--unicode`,
  `--repeat-mode changes|chords` (default `changes`), and `--no-metric-chords`
  to disable the enabled-by-default rhythm-aware smoothing. The leadsheet uses
  aligned monospace beat fields, two complete measures per row, and extra space
  after every eight measures. The helper never imports Flask or starts the
  server. Unlike browser exports, this command does not include local Lyrics
  or romanization. Wrapper: `scripts/chordflask-export`.

  ```bash
  scripts/chordflask-export /path/to/collection
  ```

- `chordflask_lyrics/` - the externally runnable
  `chordflask-genlyrics` command. Its default lyrics priority is
  `lrc:embedded:lrclib`: a usable synchronized same-stem `.lrc`, embedded
  lyrics, then an on-demand LRCLIB lookup using standard-library HTTP. External
  `.lrc` files remain untouched user/external data beside their media files.
  `--lyrics` accepts an ordered colon-separated subset of `lrc`, `embedded`,
  and `lrclib`. The command requires existing ChordFlask analysis and writes a
  same-stem `.cho` beside each media file. Directory discovery uses the
  application's non-recursive preferred-media rules. The `--tag SEARCH_TEXT`
  LRCLIB lookup hint is accepted only for a single file and requires `lrclib`
  in `--lyrics`. `--track
  TRACK_ID` selects the chord-track snapshot (`auto` by default: valid
  `user_edited`, then the analysis active/default track, then `chordino`). An
  explicit missing track fails for that file without fallback. `--force`
  permits replacement of an existing `.cho`; `--dry-run` performs lookup,
  alignment, and rendering without writing. Directory failures do not stop
  later files. Existing `.cho` files are intentionally skipped unless `--force`
  is supplied.

  Thai romanization is **experimental**. `--romanize` uses the
  external-runtime PyThaiNLP `thai2rom_onnx` engine by default;
  `--romanize-engine royin` selects the RTGS-oriented alternative. Engines
  never silently fall back. Romanization is
  generated once as non-timed presentation metadata in the `.cho`; it is not
  recomputed by the browser or standalone, and the original Thai lyric remains
  canonical. It is intended as pronunciation assistance rather than IPA or
  authoritative tone notation, and results may vary for wording and names.
  The external Lyrics setup installs `pythainlp[onnx]>=5.3.3,<6` without
  PyTorch. Its supported engines are `thai2rom_onnx` and `royin`.

  Wrapper: `scripts/chordflask-genlyrics`. This package is excluded from the
  standalone. Desktop Prepare can instead invoke it from the isolated
  `~/.venvs/chordflask-lyrics` environment created by `make setup-lyrics`.
  Normal LRCLIB lookup needs no API key, and generated lyrics remain local user
  data.

  ```bash
  scripts/chordflask-genlyrics song.mp3
  scripts/chordflask-genlyrics /music/album
  scripts/chordflask-genlyrics --lyrics embedded:lrclib song.mp3
  scripts/chordflask-genlyrics --lyrics lrc song.mp3
  scripts/chordflask-genlyrics --tag "Artist Song Title" song.mp3
  scripts/chordflask-genlyrics --track auto song.mp3
  scripts/chordflask-genlyrics --track btc song.mp3
  scripts/chordflask-genlyrics --force --track user_edited song.mp3
  scripts/chordflask-genlyrics --romanize song.mp3
  scripts/chordflask-genlyrics --romanize --romanize-engine thai2rom_onnx song.mp3
  scripts/chordflask-genlyrics --romanize --romanize-engine royin song.mp3
  scripts/chordflask-genlyrics --force --romanize /music/thai-album
  scripts/chordflask-genlyrics --dry-run /music/album
  ```

- `batch_core.py` - shared non-recursive media discovery (MP4/WebM/MP3 with the
  active same-stem priority) used by `analyze_cli.py`, `export_cli.py`, and
  `chordleadsheet_batch.py`; backed by `chordflask/media_library.py`.

- `chordleadsheet_batch.py` - the leadsheet library used by `export_cli.py`. It
  holds the shared render/write logic and the export option definitions; new
  code should use `chordflask-export` rather than running this module directly.

### Portable launchers

After a source setup, repository launchers can be copied or symlinked into a
directory on `PATH`:

```bash
make all
cp scripts/chordflask \
   scripts/chordflask-{analyze,demucs,export,genlyrics,maintain} \
   ~/bin/
```

They select the configured/default ChordFlask virtual environment, preserve the
caller's working directory, and run the installed console command. They do not
infer a source checkout from their own location. When upgrading from an older
0.9.x installation, copy the launchers again: older copies can still target the
pre-package source layout.

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
