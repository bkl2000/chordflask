# Stem-aware Chord Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run Chordino on a Demucs stem, persist each result as its own chord track, and show it on the original playback timeline with the stem mixer unchanged.

**Architecture:** A stem result is an extra Schema-v3 chord track `chordino_stem_<stem>` in the existing analysis JSON, rendered on the original QM grid. A framework-free helper in `chordflask_base` owns IDs, metadata and JSON-only freshness. A producer module in `chordflask/` analyzes the stem FLAC and writes the track under `analysis_json_lock`. The web UI runs it as a subprocess through a `BackgroundPreparationManager`; the CLI calls it directly.

**Tech Stack:** Python 3.12, Flask, librosa, vamp (`nnls-chroma:chordino`), pytest, vanilla JS in `chordflask/templates/home.html`.

**Spec:** `design/specs/2026-10-10-stem-aware-chord-analysis-design.md`

## Global Constraints

- Branch: `feature/stem-aware-chord-analysis` (already checked out). **Do not commit or push unless the user asks.** Each task ends with a verification checkpoint instead of a commit.
- Track ID format: `chordino_stem_<stem>`; stem names must match `^[a-z0-9_]+$`.
- Audio set ID: `"demucs:htdemucs"` (use `STEMS_AUDIO_SET_ID` from `chordflask/mp4playerflask.py` in `chordflask/`; define a local constant in `chordflask_base`).
- Display name: `f"Chordino · {stem.capitalize()} stem"`; stale suffix `" (stale)"`, missing suffix `" (stems missing)"`.
- `timeline` metadata is exactly `{"reference": "original", "offset_seconds": 0.0}`.
- Never import `chordflask_demucs`, Torch or Demucs from `chordflask/` or `chordflask_base/`.
- No schema version bump; no change to existing routes' request/response contracts.
- Every read-modify-write of analysis JSON holds `analysis_json_lock` (not reentrant; never unlink its lock file).
- Tests use `tmp_path` and `monkeypatch.setenv("CHORDFLASK_QUEUE_DIR", ...)`; never real media or `~/.chordflask`.
- Ruff: line length 110; run `make lint`.
- Desktop-only Prepare UI (tablet/phone get no new controls).

## Review Focus

1. **Stems regenerated while a stem analysis runs:** the write must be aborted and the JSON left byte-identical. Pinned in Task 3 (`test_aborts_when_stem_set_changes_during_analysis`).
2. **Second client edits chords while a stem analysis finishes:** the editor's mtime check must detect the new write (409, reload) rather than overwrite the stem track. Pinned in Task 5 (`test_stem_track_write_triggers_edit_conflict`).
3. **Stem name from the request body that is not in the loaded set** (e.g. `"../x"`, `"guitar"`): 400 before any job starts. Pinned in Task 5 (`test_prepare_rejects_unknown_stem`).
4. **Reanalyze (Chordino) after stem tracks exist:** stem tracks preserved and then reported `stale` only if the source identity changed. Pinned in Task 1 (`test_status_stale_when_chordino_source_changes`) and Task 3 (`test_canonical_reanalysis_preserves_stem_tracks`).
5. **Edited track seeded from a stem, then Reset, when the stem track was removed or never existed on disk:** Reset falls back to `chordino` instead of raising. Pinned in Task 6 (`test_reset_falls_back_to_chordino_when_seed_missing`).

---

### Task 1: Stem chord track model helpers (`chordflask_base`)

**Files:**
- Create: `chordflask_base/stem_chords.py`
- Modify: `chordflask_base/__init__.py` (import and add to `__all__`)
- Test: `tests/test_stem_chords_model.py`

**Interfaces:**
- Produces:
  - `STEM_CHORD_TRACK_PREFIX = "chordino_stem_"`
  - `stem_chord_track_id(stem: str) -> str`: raises `ValueError` unless `stem` matches `^[a-z0-9_]+$`
  - `stem_from_track_id(track_id: str) -> str | None`: `None` when not a stem track ID
  - `build_stem_chord_metadata(*, stem: str, set_id: str, stem_entry: dict, set_source_sha256: str, source_media: dict | None) -> dict`: shape exactly as in the spec; omit `source_media` when `None`
  - `stem_chord_track_status(chord_data: ChordData, track_id: str) -> str | None`: `"current" | "stale" | "stems_missing"`, or `None` when the track lacks `audio_source.kind == "stem"` metadata

- [ ] **Step 1: Write the failing tests**

```python
def test_track_id_roundtrip():
    assert stem_chord_track_id("other") == "chordino_stem_other"
    assert stem_from_track_id("chordino_stem_other") == "other"
    assert stem_from_track_id("chordino") is None

@pytest.mark.parametrize("bad", ["", "Other", "../x", "a b", "a-b"])
def test_track_id_rejects_unsafe_stem(bad):
    with pytest.raises(ValueError):
        stem_chord_track_id(bad)

def test_metadata_shape():
    meta = build_stem_chord_metadata(stem="other", set_id="demucs:htdemucs",
        stem_entry={"sha256": "b" * 64, "size": 7}, set_source_sha256="a" * 64,
        source_media={"sha256": "a" * 64, "size": 9})
    assert meta["display_name"] == "Chordino · Other stem"
    assert meta["audio_source"] == {"kind": "stem", "set_id": "demucs:htdemucs", "stem": "other",
        "stem_sha256": "b" * 64, "stem_size": 7, "set_source_sha256": "a" * 64}
    assert meta["timeline"] == {"reference": "original", "offset_seconds": 0.0}

def test_status_current(...)                         # set registered, hashes equal → "current"
def test_status_stale_when_stem_regenerated(...)     # registered stem sha differs → "stale"
def test_status_stale_when_set_source_changes(...)   # set metadata.source.sha256 differs → "stale"
def test_status_stale_when_chordino_source_changes(...)  # chordino source_media differs → "stale"
def test_status_stems_missing_without_audio_set(...)  # → "stems_missing"
def test_status_none_for_non_stem_track(...)          # "chordino", "btc" → None
```

Build the fixture `ChordData` with `set_base_chords`, a `qm_barbeattracker` rhythm track, `set_audio_track("demucs:htdemucs", ...)` (copy the `_audio_set` shape from `tests/test_stem_serving.py`), and `set_chord_track("chordino_stem_other", [...], metadata=build_stem_chord_metadata(...))`.

- [ ] **Step 2: Run to verify failure**

Run: `make test TEST_ARGS="-q tests/test_stem_chords_model.py"`. Expected: collection error (`ModuleNotFoundError: chordflask_base.stem_chords`).

- [ ] **Step 3: Implement `chordflask_base/stem_chords.py`**

Stdlib + `.schema` only. `stem_chord_track_status` reads `chord_data.chord_track_metadata(...)`, `has_audio_track`/`audio_track_data`, and `chord_track_metadata(DEFAULT_CHORD_TRACK).get("source_media")`. It never touches the filesystem. Any malformed metadata yields `"stale"`.

- [ ] **Step 4: Run to verify pass**

Same command. Expected: all pass. Also run `make test TEST_ARGS="-q tests/test_package_boundary.py"`.

---

### Task 2: Reusable chord-only analysis in `AudioAnalyzer`

**Files:**
- Modify: `chordflask/audio_analyzer.py` (`analyze`, new methods)
- Test: `tests/test_chordanalyzer.py` (append)

**Interfaces:**
- Produces:
  - `AudioAnalyzer._chords_from_signal(self, y, sr) -> list[dict]`: pre-emphasis → `_extract_chords_vamp` → `self.postprocessor.process`
  - `AudioAnalyzer.analyze_chords(self, audio_path) -> list[dict]`: `require_vamp_plugins()`, `librosa.load(audio_path, sr=self.sample_rate, mono=True)`, then `_chords_from_signal`. Does **not** call `require_system_ffmpeg` and does not detect beats.

- [ ] **Step 1: Write the failing tests**

```python
def test_analyze_chords_runs_chordino_on_preemphasized_signal_without_beats(monkeypatch):
    # stub librosa.load → ([1.0, 0.0], 44100); stub librosa.effects.preemphasis → marker list
    # stub vamp.collect: assert plugin == "nnls-chroma:chordino" and signal is the marker;
    # assert it is never called with "qm-vamp-plugins:qm-barbeattracker"
    assert AudioAnalyzer().analyze_chords("stem.flac") == [{"timestamp": 0.0, "chord": "C"}]

def test_analyze_output_unchanged_by_refactor(monkeypatch):
    # same stubs as test_analyze_labels_chord_and_rhythm_sources; assert the chordino
    # track receives exactly the vamp chords after postprocessing, and preemphasis
    # is applied once
```

- [ ] **Step 2: Run to verify failure**

Run: `make test TEST_ARGS="-q tests/test_chordanalyzer.py -k analyze_chords"`. Expected: `AttributeError: ... analyze_chords`.

- [ ] **Step 3: Implement**

In `analyze()`, replace the inline pre-emphasis + Chordino + post-processing with `self._chords_from_signal(y, sr)` in the non-madmom branch. Keep the madmom branch calling `self.postprocessor.process(...)` on its own result. Pre-emphasis moves into the helper; beat detection already ran on the raw `y`, so output is unchanged.

- [ ] **Step 4: Run to verify pass**

Run: `make test TEST_ARGS="-q tests/test_chordanalyzer.py tests/test_analysis_service.py"`. Expected: all pass.

---

### Task 3: Stem chord producer and hidden `--analyze-stem` flag

**Files:**
- Create: `chordflask/stem_chord_analysis.py`
- Modify: `chordflask/app.py` (`_build_argument_parser`, `main`)
- Test: `tests/test_stem_chord_analysis.py`

**Interfaces:**
- Consumes: Task 1 helpers; `AudioAnalyzer.analyze_chords` (Task 2); `media_source_identity`, `is_canonical_analysis_complete`, `ChordTrackRepository`, `analysis_json_path`, `analysis_json_lock`, `ANALYSIS_DIR_NAME` from `chordflask_base`; `STEMS_AUDIO_SET_ID` from `chordflask.mp4playerflask`.
- Produces:
  - `class StemChordAnalysisError(RuntimeError)`
  - `resolve_registered_stem(media_path: Path, chord_data: ChordData, stem: str) -> tuple[Path, dict, dict]`: returns `(stem_file, stem_entry, set_data)`; raises `StemChordAnalysisError` for an unknown stem, a missing set, a symlink, a path outside `<media dir>/.chordflask`, or a missing file
  - `analyze_stem_chords(media_path: Path, stem: str, *, analyzer=None) -> dict`: returns `{"track_id": str, "chords": int}`; `analyzer` defaults to `AudioAnalyzer()`
  - `cli_analyze_stem(stem: str, media: str) -> int`: 0 on success; prints `ERROR: <msg>` to stderr and returns 1 on `StemChordAnalysisError`/`OSError`/`ValueError`
  - `chordflask --analyze-stem STEM MEDIA` (argparse `nargs=2`, `help=argparse.SUPPRESS`); `main()` dispatches it right after the `--check-vamp` block, **before** constructing `FlaskMP4App`

- [ ] **Step 1: Write the failing tests**

Fixture: media file bytes `b"media"`; real FLAC-named files with known bytes under `.chordflask/stems/demucs/htdemucs/song/gen/`; audio set whose stem `sha256`/`size` are the real hashes of those bytes; set `metadata.source.sha256` = real sha256 of the media; canonical `chordino` + `qm_barbeattracker` tracks, with `chordino.metadata.source_media` = media identity; plus `user_edited`, a `btc` track and `user_data`. Use a `FakeAnalyzer` whose `analyze_chords(path)` records `path` and returns `[{"timestamp": 1.25, "chord": "Am"}]`.

```python
def test_writes_only_the_stem_track_and_preserves_everything_else(tmp_path)
    # chords == [{"timestamp": 1.25, "chord": "Am"}]  (no offset applied)
    # analyzer received the other.flac path; every other chord/rhythm/audio track,
    # user_data and transpose are equal to the pre-run values
def test_rerun_replaces_only_that_track(tmp_path)
def test_rejects_unknown_stem_missing_set_symlink_outside_root_and_missing_file(tmp_path)  # parametrized
def test_rejects_stem_hash_mismatch(tmp_path)       # message contains "stale"
def test_rejects_when_media_differs_from_stem_source(tmp_path)  # message contains "stale"
def test_requires_canonical_analysis(tmp_path)      # no chordino → error mentions "Chordino"
def test_aborts_when_stem_set_changes_during_analysis(tmp_path)
    # FakeAnalyzer rewrites the registered stem sha256 in the JSON (under the lock) before returning;
    # expect StemChordAnalysisError and the JSON equal to what FakeAnalyzer wrote
def test_canonical_reanalysis_preserves_stem_tracks(tmp_path)
    # call preserve_analysis_user_data(current, replacement) → stem track kept with metadata
def test_stem_track_renders_on_original_grid(tmp_path)
    # load result into ChordData with qm beats [0.0, 0.5, 1.0, 1.5, 2.0];
    # select chordino_stem_other; get_chords_per_beat labels == ["N", "N", "Am", "Am", "Am"]
    #   (lookup midpoints 0.25, 0.75, 1.25, 1.75, 2.25; the first two precede the 1.25 s chord)
def test_cli_flag_dispatches_without_starting_web_app(monkeypatch)
    # monkeypatch cli_analyze_stem → returns 0; main(["--analyze-stem", "other", "x.mp3"])
    # raises SystemExit(0); FlaskMP4App constructor patched to fail if called
```

- [ ] **Step 2: Run to verify failure**

Run: `make test TEST_ARGS="-q tests/test_stem_chord_analysis.py"`. Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `chordflask/stem_chord_analysis.py`**

Order inside `analyze_stem_chords`:

1. Load (no lock) and check canonical completeness.
2. `resolve_registered_stem`; verify the file's size and sha256 against `stem_entry` (stream hash in 1 MiB chunks), and `media_source_identity(media)["sha256"] == set_data["metadata"]["source"]["sha256"]`.
3. `chords = analyzer.analyze_chords(str(stem_file))`, outside the lock.
4. `with analysis_json_lock(json_path)`: reload; abort if the registered stem sha256 or `chordino` `source_media` differ from step 2. Then `set_chord_track(track_id, chords, metadata=build_stem_chord_metadata(...))` and `ChordTrackRepository().save(data, json_path)` (atomic).

- [ ] **Step 4: Add the hidden flag in `chordflask/app.py`**

Add the argument. In `main()`: `if args.analyze_stem: from .stem_chord_analysis import cli_analyze_stem; raise SystemExit(cli_analyze_stem(*args.analyze_stem))`. `VAMP_PATH` is inherited from the parent web process, which ran `setup_vamp_plugins()`.

- [ ] **Step 5: Run to verify pass**

Run: `make test TEST_ARGS="-q tests/test_stem_chord_analysis.py tests/test_chordflask_cli.py tests/test_package_boundary.py tests/test_flask_demucs_boundary.py"`. Expected: all pass.

---

### Task 4: `chordflask-analyze --source`

**Files:**
- Modify: `chordflask/helpers/analyze_cli.py`
- Test: `tests/test_analyze_cli.py` (append)

**Interfaces:**
- Consumes: `analyze_stem_chords`, `StemChordAnalysisError` (Task 3); `stem_chord_track_id`, `stem_chord_track_status` (Task 1).
- Produces: `--source` option, `choices=("original",) + DEMUCS_STEM_NAMES`, `default="original"`; `_run_stem_chordino(target: Path, stem: str, *, replace: bool, dry_run: bool) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
def test_source_defaults_to_original_and_keeps_chordino_path(monkeypatch)   # _run_chordino called, _run_stem_chordino not
def test_source_rejected_with_non_chordino_analyzer(capsys)               # --analyzer btc --source other → exit 2
def test_stem_dry_run_labels(tmp_path, capsys)  # TODO / CURRENT / STALE / NO STEMS, no writes (JSON bytes unchanged)
def test_stem_run_skips_current_unless_replace(monkeypatch, tmp_path)
def test_stem_run_counts_failures_and_returns_1(monkeypatch, tmp_path)
```

- [ ] **Step 2: Run to verify failure**

Run: `make test TEST_ARGS="-q tests/test_analyze_cli.py -k source"`. Expected: argparse error `unrecognized arguments: --source`.

- [ ] **Step 3: Implement**

`main()`: if `args.source != "original"` and `args.analyzer != "chordino"`, call `parser.error(...)`. Otherwise dispatch to `_run_stem_chordino`. It mirrors `_run_chordino`'s per-file loop, summary block and exit codes. Status: no audio set → `NO STEMS`; no track → `TODO`; else `stem_chord_track_status` uppercased.

- [ ] **Step 4: Run to verify pass**

Run: `make test TEST_ARGS="-q tests/test_analyze_cli.py"`. Expected: all pass.

---

### Task 5: Background preparation, subprocess runner and routes

**Files:**
- Modify: `chordflask/stem_preparation.py` (`BackgroundPreparationManager.start`, `_run`)
- Modify: `chordflask/media_preparation.py`
- Modify: `chordflask/app.py` (`__init__`, `setup_routes`, three handlers, `_stem_chords_ready`)
- Test: `tests/test_stem_chord_routes.py`

**Interfaces:**
- Consumes: Task 1 helpers; `audio_stems_state()`; the existing `_active_editing_media`, `_media_is_queued`, `__analysis_is_valid`.
- Produces:
  - `BackgroundPreparationManager.start(self, media_path, *runner_args) -> dict`: `runner_args` are passed to `runner(media_path, *runner_args)` and stored in the job as `"args"`. Existing call sites are unchanged.
  - `stem_chords_command(media_path: Path, stem: str) -> list[str]`: `[sys.executable, "-m", "chordflask", "--analyze-stem", stem, str(media_path)]`; frozen: `[sys.executable, "--analyze-stem", stem, str(media_path)]`
  - `run_stem_chord_preparation(media_path: Path, stem: str) -> int`: `_run_helper("Stem chords", stem_chords_command(...))`
  - `stem_chords_capability() -> dict`: cached via `_cached_capability("stem_chords", ...)`; available iff `require_vamp_plugins()` succeeds
  - `app.stem_chords_preparation = BackgroundPreparationManager(capability_probe=stem_chords_capability, runner=run_stem_chord_preparation, label="Stem chords")`
  - Routes: `POST /prepare_stem_chords`, `GET /stem_chords_preparation_status`, `POST /refresh_stem_chords` (contracts in the spec). Status payload adds `"stem"` when a job exists.

- [ ] **Step 1: Write the failing tests**

Reuse the `_client`, `_load` and `_wait_status` helpers (copy from `tests/test_media_preparation.py`) and the stem-set fixture from `tests/test_stem_serving.py`.

```python
def test_manager_passes_runner_args(tmp_path)          # runner receives (path, "other")
def test_stem_chords_command_source_and_frozen(monkeypatch)
def test_prepare_starts_job_and_refresh_selects_new_track(tmp_path)
    # runner writes chordino_stem_other via build_stem_chord_metadata; 202 → ready;
    # refresh with stem → active_chord_track_id == "chordino_stem_other"; user_data kept
def test_prepare_rejects_unknown_stem(tmp_path)        # "guitar", "../x", missing → 400, runner never called
def test_prepare_requires_loaded_stem_set(tmp_path)    # song without audio set → 409
def test_prepare_returns_ready_for_current_track_without_recompute(tmp_path)
def test_prepare_recomputes_stale_track(tmp_path)      # stale → 202
def test_prepare_rejects_non_active_media_and_queued_media(tmp_path)
def test_stem_track_write_triggers_edit_conflict(tmp_path)
    # load + start editing; write a stem track to JSON from outside; POST /edit_chord → 409
```

- [ ] **Step 2: Run to verify failure**

Run: `make test TEST_ARGS="-q tests/test_stem_chord_routes.py"`. Expected: 404s and `TypeError` on `start(...)` args.

- [ ] **Step 3: Implement manager, runner, capability, routes**

`prepare_stem_chords` order:

1. JSON body → `_active_editing_media` under `state.lock`.
2. Valid analysis, otherwise 409.
3. `stems = state.player.audio_stems_state()`: `None` → 409; `stem not in stems["stems"]` → 400.
4. `_stem_chords_ready` (track exists and status `current`) → `{"status": "ready"}`.
5. Queued → 409.
6. `manager.start(media, stem)`; map results like `_prepare_current_media`.

`refresh_stem_chords` copies `refresh_btc`, then soft-selects `stem_chord_track_id(stem)` when `stem` is given and valid.

- [ ] **Step 4: Run to verify pass**

Run: `make test TEST_ARGS="-q tests/test_stem_chord_routes.py tests/test_media_preparation.py tests/test_stem_preparation.py tests/test_multi_client.py"`. Expected: all pass.

---

### Task 6: Player status labels and stem-seeded editing

**Files:**
- Modify: `chordflask/mp4playerflask.py` (`analysis_track_state`, `start_chord_editing`, `set_chord_version`, `reset_edited_chords`, new `_edit_source_chord_track_id`)
- Test: `tests/test_chord_editing.py` (append)

**Interfaces:**
- Consumes: `stem_from_track_id`, `stem_chord_track_status` (Task 1).
- Produces:
  - `analysis_track_state()["available_chord_tracks"][i]` gains `"status"` (`"current" | "stale" | "stems_missing"`) for stem tracks only; `display_name` gets the suffix from Global Constraints. Other keys unchanged.
  - `MP4PlayerFlask._edit_source_chord_track_id(self) -> str`: the active ID if `stem_from_track_id(active)` is not `None`, else `"chordino"`
  - `MP4PlayerFlask.__original_chord_track_id(self) -> str`: `user_edited.metadata.sources.chord` if that track is available, else `"chordino"`

- [ ] **Step 1: Write the failing tests**

```python
def test_stem_tracks_listed_with_status_and_suffix(tmp_path)
def test_edit_seeds_from_active_stem_track(tmp_path)
    # select chordino_stem_other (labels differ from chordino) → start_chord_editing →
    # edited per-beat labels equal the stem track's; metadata["sources"]["chord"] == "chordino_stem_other"
def test_edit_seeds_from_chordino_when_btc_active(tmp_path)   # unchanged behavior for non-stem producers
def test_existing_edited_track_is_not_reseeded(tmp_path)
def test_original_toggle_returns_to_seed_track(tmp_path)
def test_reset_returns_to_seed_track(tmp_path)
def test_reset_falls_back_to_chordino_when_seed_missing(tmp_path)
```

The existing `test_player_reset_selects_chordino_when_other_producer_active` must keep passing unchanged.

- [ ] **Step 2: Run to verify failure**

Run: `make test TEST_ARGS="-q tests/test_chord_editing.py -k 'stem or seed'"`. Expected: failures on `sources.chord` and selection.

- [ ] **Step 3: Implement** using the interfaces above. The `"Chordino analysis is not available"` / QM guards in `start_chord_editing` and `reset_edited_chords` stay as they are.

- [ ] **Step 4: Run to verify pass**

Run: `make test TEST_ARGS="-q tests/test_chord_editing.py tests/test_analysis_tracks.py tests/test_flask_app.py"`. Expected: all pass.

---

### Task 7: Prepare-menu UI for stem chords

**Files:**
- Modify: `chordflask/templates/home.html` (Prepare popover, `prepareActions`, `prepareCurrent`, `finishPreparation`, `updatePrepareButtons`, `updateStemsAvailability`)
- Test: `tests/test_stem_chord_routes.py` (append template assertions, style of `test_prepare_menu_is_compact_capability_driven_and_desktop_only`)

**Interfaces:**
- Consumes: routes from Task 5; `stems.stems` from `/load_file` and `/refresh_stems`.
- Produces (DOM IDs asserted by tests): `prepareStemChordsButton`, `prepareStemChordsState`, `stemChordsSourceSelect`; `prepareActions.stemChords` with `startUrl: '/prepare_stem_chords'`, `statusUrl: '/stem_chords_preparation_status'`, `refreshUrl: '/refresh_stem_chords'`, and `body: () => ({ stem: stemChordsSourceSelect.value })`.

- [ ] **Step 1: Write the failing template test**

```python
def test_prepare_menu_offers_stem_chords_only_with_stems():
    body = client.get("/").get_data(as_text=True)
    for marker in ('id="prepareStemChordsButton"', 'id="stemChordsSourceSelect"',
                   "'/prepare_stem_chords'", "'/stem_chords_preparation_status'",
                   "'/refresh_stem_chords'"):
        assert marker in body
    assert 'id="prepareStemChordsButton" class="prepare-action"' in body  # inside the desktop-only popover
```

- [ ] **Step 2: Run to verify failure**

Run: `make test TEST_ARGS="-q tests/test_stem_chord_routes.py -k prepare_menu"`. Expected: assertion failure.

- [ ] **Step 3: Implement**

- `prepareCurrent`: merge `action.body ? action.body() : {}` into the POST body.
- `finishPreparation`: send the same extra body to `refreshUrl`. For `stemChords`, call `updateTrackSelectors(data)`; usable when `data.available_chord_tracks` contains `chordino_stem_<stem>`.
- Populate `stemChordsSourceSelect` options from `stems.stems` in `updateStemsAvailability`, labeled with the capitalized stem name.
- Hide the action when `!stemsAvailable`.

- [ ] **Step 4: Run to verify pass**

Run: `make test TEST_ARGS="-q tests/test_stem_chord_routes.py tests/test_media_preparation.py tests/test_grid_frontend.py tests/test_journal_ui.py"`. Expected: all pass.

---

### Task 8: Documentation and full check

**Files:**
- Modify: `docs/ANALYSIS.md` (new section "Chords from a Demucs stem": sources, track IDs, freshness labels, editing seed, CLI `--source`)
- Modify: `docs/DEMUCS.md` (short "Chord analysis from stems" pointer under Player behavior; remove nothing)
- Modify: `docs/ARCHITECTURE.md` ("Where to change what" row `Stem chord analysis | chordflask/stem_chord_analysis.py, chordflask_base/stem_chords.py`; one sentence in Process boundaries: stem Chordino runs in a subprocess started by the web process)
- Modify: `docs/HELPERS.md` (`--source` in the `analyze_cli.py` bullet)

- [ ] **Step 1: Write the docs** (user-facing; no internal design rationale).
- [ ] **Step 2: Run** `make test TEST_ARGS="-q tests/test_documentation.py tests/test_makefile.py tests/test_packaging.py"`. Expected: all pass.
- [ ] **Step 3: Run** `make check`. Expected: tests, lint, compileall and `git diff --check` all pass. Paste the summary line in the handoff.

---

### Task 9: Validation on a real recording (Phase 3; read-only on user data)

No code. Copy one recording **and its `.chordflask/` directory** into the scratchpad first, and run everything against the copy.

- [ ] **Step 1:** `chordflask-analyze --source other --dry-run <copy>` → `TODO`; run without `--dry-run` → `OK`; rerun → `SKIP`.
- [ ] **Step 2: Timeline check.** Decode the analysis-path audio (derived MP3 for MP4/WebM, the file itself for MP3) and the sum of the four stem FLACs at 44.1 kHz mono. Cross-correlate within ±200 ms. Expected: the absolute offset is well below half a beat at the song's BPM. Record the measured value.
- [ ] **Step 3: Manual UI pass** (start with `make run`, open `http://localhost:5000`, pointing at the copy directory): Prepare → Stem chords → Other; the selector switches to "Chordino · Other stem"; chords follow playback with STEMS on and off and with Vocals muted; Edit seeds from the stem chords; Original returns to the stem track. Then regenerate the stems on the copy → the track shows "(stale)".
