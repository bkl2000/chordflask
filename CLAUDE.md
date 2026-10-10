# ChordFlask

Local-first Flask app: analyzes chords and rhythm in MP3/MP4/WebM files and shows them during synchronized browser playback. Authoritative developer docs live in `docs/` (start with `docs/ARCHITECTURE.md`); this file only covers what a session needs to work safely.

## Fork and upstream

- `origin` is the contributor fork; `upstream` is `bkl2000/chordflask`. Upstream history consists of "Sync public snapshot from …" commits and the repo carries `.chordflask-public-snapshot` ("Managed ChordFlask public snapshot"). *Assumption:* upstream is a mirrored snapshot, so PRs may not merge as-is. No document describes upstream's PR process.
- Keep changes small, focused and rebasable onto `upstream/main`. Do not touch `VERSION`, `CNAME`, `THIRD_PARTY_NOTICES.md`, or the snapshot marker unless asked.
- `CONTRIBUTING.md`: focused changes, tests for public behavior and failure paths, run `make check` first, keep public APIs stable unless agreed.
- Never commit or push unless asked.

## Commands

All go through the Makefile; the default venv is `~/.venvs/chordflask` (`VENV_DIR=` overrides).

- `make setup` installs runtime + dev tools into the venv (`make help` marks every installing/destructive target).
- `make run` starts worker + web app (default port 5000; `chordflask --port N`). `make worker` starts only the worker.
- `make test TEST_ARGS="-q -k name"`: pytest via `scripts/run_tests.sh`.
- `make lint`: Ruff only (line length 110, rules E4/E7/E9/F/B; `chordflask_btc/model/**` excluded).
- `make check` = test + lint + `compileall` + `git diff --check`. This is what CI runs.
- Real-plugin tests skip unless `CHORDIFIER_REQUIRE_VAMP=1` is set (CI's `vamp` job sets it, plus `VAMP_PATH`): `tests/test_vamp_integration.py`.
- Optional runtimes: `make setup-btc` / `btc-check`, `make setup-demucs` / `demucs-check`, `make setup-lyrics` / `lyrics-check`.
- CLIs (`pyproject.toml`): `chordflask`, `chordflask-analyze`, `chordflask-export`, `chordflask-demucs`, `chordflask-maintain`, `chordflask-genlyrics`.
- Avoid `make clean`, `make setup-recreate` (delete files/venv).
- Python 3.12–3.14 supported; only 3.12 has a constraints file. Details: `docs/COMPATIBILITY.md`.

## Architecture map

Web process (`chordflask/app.py`) and a **single** analysis worker are separate processes sharing a file-locked persistent queue.

- Queue/worker: `chordflask/analysis_queue.py`, `analysis_worker.py`. State in `~/.chordflask` (override `CHORDFLASK_QUEUE_DIR`). Stale `processing` jobs are requeued; a lock prevents a second worker.
- Analysis: `canonical_analysis.analyze_media` → `chordanalyzer.py` / `analysis_service.py` / `audio_analyzer.py`. Chordino + QM bar/beat tracker via Vamp; `librosa` for BPM/meter.
- Playback/state: `mp4playerflask.py`, `playbackview.py`, `client_state.py`. The Grid is the single playback authority (`/set_position` carries the beat index); Lyrics follows it and adds no clock.
- `chordflask_base/`: framework-free Schema-v3 model and storage; shared by app and optional producers.
- `chordflask_btc/`, `chordflask_demucs/`: thin orchestrators that run heavy inference in their own venv via subprocess.
- `chordflask_maintain/`: stdlib + `chordflask_base` only. `chordflask_lyrics/`: `.cho` generator.
- `docs/ARCHITECTURE.md` has a "Where to change what" table and an "Architectural invariants" list. Read the invariants before structural changes.

## Persistence rules

- Analysis JSON: `<media dir>/.chordflask/<media stem>.json` (Schema v3, `chordflask_base/schema.py`). The final JSON is the completion marker; publish via atomic replace.
- Read-modify-write of analysis JSON must hold `analysis_json_lock` (`chordflask_base/storage.py`). It is **not reentrant**, and its lock file must never be unlinked.
- Tracks stay distinct: `chordino`, `qm_barbeattracker`, `user_edited` (beat-aligned corrections, never overwrite Chordino), `btc`, and `audio_tracks["demucs:htdemucs"]`. Do not merge or overwrite one producer's track from another.
- Source media is never modified. Journal (`.chordflask/journals/`) and `.cho` sidecars are user-owned and must survive reanalysis and maintenance.
- Legacy env aliases (`CHORDIFIER_*`, `CHORDY_QUEUE_DIR`) and the `~/.venvs/chordifier` fallback are still honored; do not remove them.

## Optional runtimes (BTC, Demucs)

- Never import Torch, Demucs or BTC model code from `chordflask/` or `chordflask_base/`. Those run only in subprocesses in `~/.venvs/chordflask-btc` / `~/.venvs/chordflask-demucs` (overrides `CHORDFLASK_BTC_VENV`, `CHORDFLASK_DEMUCS_VENV`). The standalone bundle excludes them.
- Demucs: producer writes four FLAC stems (`bass`, `drums`, `other`, `vocals`) under `.chordflask`; the consumer reads only generic `audio_tracks` metadata (`mp4playerflask.audio_stems_state`). Only a complete, validated set is used. The original media remains the master timeline. `chordflask/stem_preparation.py` is the UI's on-demand path.
- Capability is detected at runtime; the core must keep working when these venvs are missing.

## Testing conventions

- pytest with plain `assert`; no `unittest.TestCase`. `conftest.py` puts the repo root on `sys.path`.
- Tests guard contracts, not just behavior: `tests/test_package_boundary.py` (no `sys.path` mutation in `chordflask/`), `test_documentation.py` and `test_makefile.py` (docs/Makefile text is asserted), `test_packaging.py`, `test_standalone_runtime_gate.py`. Changing docs, Makefile targets or packaging can fail these.
- Tests must use temp dirs. Do not point them at real media directories or the real `~/.chordflask` queue.

## Pitfalls

- Editing `README.md`, `docs/`, or the `Makefile` can break tests (see above); run the related test file.
- Desktop is the full UI; tablet/phone layouts intentionally expose fewer controls.
- Existing routes, persistence formats and security assumptions stay unchanged unless the task says otherwise. Schema changes need backward-compatible readers (supported versions 1–3).
- Needs system `ffmpeg` on `PATH` and Vamp plugins `nnls-chroma:chordino`, `qm-vamp-plugins:qm-barbeattracker` (searched via `VAMP_PATH`). Without plugins the UI still starts, but analysis cannot run.
- `build/`, `*.egg-info/`, `__pycache__` are ignored build output.

## Unverified

- Baseline `make check` result on this checkout has not been recorded.
- BTC runtime/venv was not exercised.
- Upstream's acceptance process for external PRs is unknown.

Machine-specific paths belong in `CLAUDE.local.md`, not here.
