# Stem-aware chord analysis — design spec

Status: approved design (2026-10-10). Not user documentation; the user-facing
text lands in `docs/ANALYSIS.md` and `docs/DEMUCS.md` during implementation.

## Problem

Chordino always analyzes the original mix. For recordings such as João
Gilberto's, the vocals disturb chord recognition, while Chordino on the Demucs
**Other** stem follows the guitar much better. The user wants those stem-derived
chords displayed while playing the original recording, with the existing stem
mixer still available.

## Requirements

1. The user can choose the chord-analysis source: **Original** (default, the
   existing `chordino` track), **Vocals**, **Bass**, **Drums**, **Other**.
   Available stems come from the registered audio set, not a hard-coded list,
   so future stem types work without UI changes.
2. Chordino runs on the selected stem file. Source media and stem files are
   never modified.
3. Each source has its own persisted chord track; switching never recomputes.
4. The player switches between chord tracks with the existing chord-track
   selector.
5. The Demucs stem mixer (STEMS, per-stem mute/volume) is unchanged and
   independent of the chosen chord source.
6. Every chord track stays synchronized with the original playback timeline.
7. Songs without Demucs stems behave exactly as today.
8. Editing: when a stem chord track is active, **Edit** seeds the Edited track
   from that stem track (decision 2026-10-10).

## Key findings that shape the design

- **Chord and rhythm tracks are independent.** `ChordData._rebuild_active_view`
  selects them separately and `get_chords_per_beat` samples the active chord
  track by *time* at each beat midpoint of the active rhythm track. A chord
  track from any source therefore renders on the original QM grid.
- **Stems share the original timeline sample-for-sample.** The Demucs producer
  decodes the source with ffmpeg, separates it, then pads/trims every FLAC to
  exactly the source sample count (`sync.start_sample = 0`, start time ≈ 0).
  The player plays stems with zero offset against the master media. A Chordino
  timestamp computed on a stem FLAC is already a playback-timeline time.
- **The existing original track is the less exact one.** MP4/WebM analysis goes
  through a moviepy-written MP3 (possible encoder delay); MP3 goes through
  librosa's decoder. Expect a constant difference of at most a few tens of ms
  between original and stem tracks, well inside the half-beat midpoint lookup
  tolerance. Recorded explicitly as `timeline.offset_seconds = 0`.
- **Extra chord tracks already survive reanalysis.**
  `preserve_analysis_user_data` copies every non-`chordino` chord track.
- **The queue is keyed by media path only**, so stem jobs do not go through it.

## Design

### Storage (Schema v3, no version bump)

One chord track per stem in the existing analysis JSON:

- Track ID: `chordino_stem_<stem>` (e.g. `chordino_stem_other`). Stem names are
  restricted to `[a-z0-9_]+`.
- `chords`: Chordino output after the normal `ChordPostProcessor`.
- `metadata`:

```json
{
  "display_name": "Chordino · Other stem",
  "engine": "chordino",
  "audio_source": {
    "kind": "stem",
    "set_id": "demucs:htdemucs",
    "stem": "other",
    "stem_sha256": "<registered sha256 of other.flac>",
    "stem_size": 12345678,
    "set_source_sha256": "<audio set metadata.source.sha256>"
  },
  "source_media": {"sha256": "...", "size": 123},
  "timeline": {"reference": "original", "offset_seconds": 0.0}
}
```

`source_media` is copied from the `chordino` track's metadata when present.
Older readers see an ordinary extra chord track (BTC precedent).

### Display grid

Stem tracks are displayed on the original `qm_barbeattracker` grid. No beat
tracking runs on stems: the drum-less stems would track worse, and a second
grid would conflict with Edited and Lyrics, which rely on the original grid.
The rhythm selector stays independent.

### Freshness (computed from JSON only; no file hashing at load or playback)

`stem_chord_track_status` returns, for a stem track:

| Status | Condition |
| --- | --- |
| `stems_missing` | the referenced audio set is no longer registered |
| `stale` | registered stem sha256 ≠ `audio_source.stem_sha256`, or set source sha256 ≠ `audio_source.set_source_sha256`, or `chordino.metadata.source_media` exists and differs from the track's `source_media` |
| `current` | otherwise |

Stale and stems-missing tracks are **kept**, stay selectable, and get a
suffix in their display name (` (stale)`, ` (stems missing)`). Re-running
replaces only that track. Original-media changes that have not been
reanalyzed are already reported by the existing `analysis_source_status`.

### Producer

`analyze_stem_chords(media, stem)`:

1. Requires a valid, canonical-complete analysis (`chordino` + `qm`).
2. Resolves the stem from `audio_tracks["demucs:htdemucs"]`. The file must
   lie inside `.chordflask`, must not be a symlink, and must match the
   registered size and sha256. The media's sha256 must equal the set's
   `metadata.source.sha256`; otherwise the stems are stale and the run fails.
3. Runs load → pre-emphasis → Chordino → post-processing on the FLAC directly
   (no intermediate audio file).
4. Under `analysis_json_lock`: rereads the JSON, aborts without writing if
   the stem sha256 or the `chordino` source identity changed meanwhile, writes
   only `chordino_stem_<stem>` with an atomic replace.

### Execution path

- Web UI: a `BackgroundPreparationManager` ("Stem chords") starts a
  **subprocess** `python -m chordflask --analyze-stem STEM MEDIA` (frozen:
  `<exe> --analyze-stem STEM MEDIA`). librosa/Vamp work stays out of the Flask
  process. `--analyze-stem` is a hidden flag.
- CLI: `chordflask-analyze --source {original,<stems>}`; `original` is the
  default and keeps today's behavior. Non-original sources support
  `--replace` and `--dry-run` (TODO / CURRENT / STALE / NO STEMS).

### Web routes (modeled on BTC)

- `POST /prepare_stem_chords` `{dirname, filename, stem}`: active media
  only; stem must be in the current `audio_stems_state()`; returns `ready` when
  the track is current.
- `GET /stem_chords_preparation_status`.
- `POST /refresh_stem_chords` `{dirname, filename, stem?}`: reloads tracks
  and selects `chordino_stem_<stem>` when given.

### UI

Desktop Prepare menu gains **Stem chords** with a stem picker populated from
`stems.stems`. It is shown only when a complete stem set is loaded and Vamp is
available. On completion the track selector refreshes and the new track is
selected. Tablet/phone get no Prepare entry (existing convention); stem tracks
remain selectable wherever the chord-track selector already appears.

### Editing

- **Edit** seeds `user_edited` from the active chord track if it is a stem
  track; otherwise from `chordino` (unchanged). The seed is recorded in the
  existing `metadata.sources.chord`.
- **Original** and **Reset** return to `sources.chord` when that track is
  available, otherwise `chordino`.
- An existing Edited track is never reseeded; there is still one Edited track
  per song.

## Out of scope

- Beat tracking on stems; mixing several stems for analysis.
- BTC or other analyzers on stems.
- Automatic analysis after Demucs completes.
- Deleting stale stem tracks automatically.

## Validation (Phase 3)

- `make check`.
- Manual: a song with stems: prepare **Other** chords, switch tracks during
  playback with STEMS on and off, edit from the stem track, regenerate stems →
  track shows "(stale)".
- Timeline check on a real MP4: cross-correlate the analysis-path decode
  against the stem sum; confirm the offset is far below half a beat.
