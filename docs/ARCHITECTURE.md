# ChordFlask Architecture

## Purpose and scope

ChordFlask is a local-first Flask application for analyzing chords and rhythm
in MP3, MP4, and WebM files and displaying the results during synchronized
browser playback. This document describes the current source layout, runtime
processes, virtual-environment model, and persistence boundaries. It is a map
of the implemented system, not a proposal for a different architecture.

## High-level runtime flow

The normal interactive path is:

```text
Browser
   |
   v
ChordFlask web application
   |
   +---- per-browser playback and display state
   |
   +---- persistent analysis queue
                |
                v
        analysis worker process
                |
                v
     ChordAnalyzer / analysis services
                |
                v
     media-directory .chordflask data
```

The web process serves the packaged template and media, maintains playback and
display state for browser clients, and adds missing or requested work to the
persistent queue. `WorkerSupervisor` starts one worker child for a normal
interactive launch. The worker claims queued jobs and runs the built-in
Chordino chord analysis and QM bar/beat analysis through the existing analyzer
services. Completed Schema-v3 JSON is published beside the media.

Optional heavy analyzers remain outside this core process path:

```text
chordflask-analyze --analyzer btc
   -> chordflask_btc orchestration
   -> dedicated BTC venv subprocess
   -> separate btc chord track in analysis JSON

chordflask-demucs
   -> chordflask_demucs orchestration
   -> dedicated Demucs venv subprocess
   -> separate FLAC stem set under .chordflask
```

## Main components

### `chordflask`

The main installable application package. `app.py` contains the Flask
application, routes, command-line parsing, and normal web/worker startup.
Queueing and worker ownership live in `analysis_queue.py` and
`analysis_worker.py`. Analysis orchestration is implemented by
`chordanalyzer.py`, `analysis_service.py`, `media_converter.py`, and
`audio_analyzer.py`. Playback, browser-client state, and chord presentation
live in `mp4playerflask.py`, `playbackview.py`, `client_state.py`, and the chord
utility modules.

The package also owns the browser template, PDF fonts, Markdown/PDF export
code, and supported CLI helper modules. Resources are resolved relative to the
installed package in both editable and frozen operation.

### `chordflask_base`

The framework-free Schema-v3 model and storage contract shared by the core
application and optional components. It defines chord and rhythm tracks,
optional audio-track sets, schema validation and conversion, chord labels, and
the `.chordflask` analysis-directory convention. It does not depend on Flask or
the analysis engines.

### `chordflask_btc`

Optional BTC analyzer orchestration and Schema-v3 integration. The normal
package side decodes/prepares input, invokes `btc-predict-raw` in the dedicated
`~/.venvs/chordflask-btc` environment, normalizes its output, and atomically
writes a separate `btc` chord track. Model inference and its heavy dependencies
are loaded only in that subprocess.

### `chordflask_demucs`

Optional Demucs producer package. Its CLI discovers media, prepares canonical
audio, invokes Demucs through `~/.venvs/chordflask-demucs`, validates the four
stems, and publishes a complete generation under the media directory's
`.chordflask` storage. The web player consumes the resulting generic audio-set
metadata without importing Demucs or its heavy runtime.

### `chordflask_maintain`

Framework-free inspection, validation, migration, storage cleanup, stem
cleanup, and installation diagnostics exposed as `chordflask-maintain`. It
depends on the standard library and `chordflask_base`, not the Flask app or
analysis engines, so maintenance does not load the media-analysis stack.

### `scripts`

Setup, launcher, diagnostic, test, publication, and release scripts. The five
portable user helpers select the configured/default core virtual environment
and execute its installed console commands. Internal scripts may remain
repository-relative. Standalone build tooling remains under `flask/` and is
invoked through the Makefile.

### `tests`

Pytest contract and regression tests for the core package, routes, queue and
worker recovery, persistence, helpers, optional-runtime boundaries,
publication safety, and standalone behavior.

## Runtime and virtual-environment model

`make setup` and `make setup-runtime` create or reuse the project environment,
normally `~/.venvs/chordflask`, install dependencies through the existing
requirements workflow, and install the current checkout editable. The venv
therefore owns normal package imports and the `chordflask`,
`chordflask-analyze`, `chordflask-export`, `chordflask-maintain`, and
`chordflask-demucs` console entry points.

User-facing scripts select that venv automatically. They preserve
`CHORDFLASK_VENV`, the legacy `CHORDIFIER_VENV` alias, default and legacy venv
locations, and supported interpreter overrides. Users normally do not activate
the venv. A copied or symlinked helper executes the explicit command in the
selected venv, preserves the caller's working directory, and does not construct
`PYTHONPATH` or locate application source files. Setup still writes
`.chordflask-root` inside the venv for compatibility and diagnostics; normal
imports and startup do not depend on it.

BTC and Demucs use separate optional venvs so their model and compute
dependencies are not installed or imported in the core runtime. The standalone
bundle contains the core application and package resources but excludes these
optional producer runtimes. It continues to use system FFmpeg and separately
installed Vamp plugins.

## Data and persistence model

- Source media are read but never modified.
- Generated data for a media directory live in its `.chordflask` subdirectory.
  This includes Schema-v3 analysis JSON, derived caches and exports, and
  optional Demucs generations.
- Queue state, worker locking, and application logs under `~/.chordflask` are
  separate from media-local analysis data. `CHORDFLASK_QUEUE_DIR` can override
  this state location.
- Chordino is the built-in default chord analyzer; the QM Vamp tracker supplies
  the default beat/bar rhythm track.
- Original analyzer tracks are preserved. Beat-aligned user corrections live
  in the distinct `user_edited` track rather than overwriting Chordino.
- Optional BTC results live in the separate `btc` chord track.
- Optional Demucs output is a separate `demucs:htdemucs` audio set referencing
  complete, validated FLAC stem generations.

Final analysis JSON is the completion marker. Queue updates and publication use
atomic replacement, and incomplete temporary output is not treated as a
completed analysis.

## Process boundaries

The web application and analysis worker are separate processes. The web process
owns Flask requests, client playback/display state, and queue submission. The
single worker owns queued analysis, with recovery returning interrupted
`processing` jobs to `pending` and a lock preventing multiple worker owners.

Chordino and QM Vamp analysis run in the core worker. BTC inference and Demucs
separation run only as subprocesses using their dedicated environments. This
keeps large optional model dependencies out of normal imports, web startup,
maintenance commands, and the standalone bundle.

## Where to change what

| Concern | Main location |
| --- | --- |
| Web application, routes, startup | `chordflask/app.py` |
| Browser template and package assets | `chordflask/templates/`, `chordflask/assets/` |
| Playback and per-client state | `chordflask/mp4playerflask.py`, `chordflask/playbackview.py`, `chordflask/client_state.py` |
| Analysis queue and worker | `chordflask/analysis_queue.py`, `chordflask/analysis_worker.py` |
| Chordino/QM analysis pipeline | `chordflask/chordanalyzer.py`, `chordflask/analysis_service.py`, `chordflask/audio_analyzer.py` |
| Chord display and post-processing | `chordflask/chorddata.py`, `chordflask/chordutils.py`, `chordflask/metric_chords.py`, `chordflask/chord_postprocess.py` |
| Storage model and schema | `chordflask_base/`, `chordflask/filerepr.py` |
| Markdown/PDF and other exports | `chordflask/chord_markdown.py`, `chordflask/chord_sheet_pdf.py`, `chordflask/chord_exporter.py`, `chordflask/helpers/` |
| BTC analyzer | `chordflask_btc/` |
| Demucs producer and stem storage | `chordflask_demucs/` |
| Maintenance commands | `chordflask_maintain/` |
| Setup and portable launchers | `scripts/setup_venv.sh`, `scripts/chordflask*` |
| Packaging and command metadata | `pyproject.toml` |
| Standalone/PyInstaller build | `flask/build_standalone.sh`, `flask/pyinstaller_hooks/` |
| Tests | `tests/` |

## Architectural invariants

- Core package imports must not require `sys.path` mutation or launcher-built
  `PYTHONPATH` values.
- Helper scripts select environments; the installed package provides imports
  and command entry points.
- Public command names and the no-manual-activation workflow remain stable.
- The web process, persistent queue, and single worker keep their current
  ownership and recovery semantics.
- BTC and Demucs heavy runtimes remain optional, isolated subprocesses and stay
  out of normal core imports and standalone artifacts.
- Source media are never modified; generated data remain media-local under
  `.chordflask`, while application state remains separate under the user's
  home directory.
- Chord, rhythm, edited, BTC, and Demucs data remain distinct tracks or audio
  sets under the shared Schema-v3 contract.
- Templates and runtime assets remain package-owned and available in editable,
  installed, and frozen operation.
- Existing routes, browser behavior, persistence formats, security assumptions,
  and standalone/publication safety gates remain unchanged unless a task
  explicitly changes them.
