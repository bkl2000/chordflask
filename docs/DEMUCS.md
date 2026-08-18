# Optional Demucs stems

ChordFlask can optionally separate a song into four stems and play them back
with individual mute and volume control. This document is the complete
workflow reference; the README has a shorter quick start.

## What it does

The optional **Demucs** runtime splits an MP3, MP4, or WebM file into four
persistent FLAC stems:

- **Vocals**
- **Drums**
- **Bass**
- **Other**

ChordFlask then plays the four stems in place of the original audio. The
original media (and video) stays the master timeline; the stems are slave
audio sources that follow it. Muting **Vocals** gives a karaoke backing track;
muting **Bass** is useful for bass practice.

## Architecture boundary

```text
Producer:
    chordflask-demucs           (scripts/chordflask-demucs)
    optional heavy runtime      (Demucs + Torch, isolated venv)

Consumer:
    ChordFlask player           (flask/, chordflask_base)
    reads generic audio_tracks  (audio_tracks["demucs:htdemucs"])
    no Demucs/Torch dependency
```

The producer and the consumer share only the generic Schema-v3
`audio_tracks` contract in `chordflask_base`. The normal ChordFlask app, its
worker, and the portable standalone bundle never import `chordflask_demucs`,
Torch, or torchaudio. The standalone can *play* prepared stems but cannot
*create* them.

## Separate runtime

The normal ChordFlask environment does not contain Demucs, Torch, or
torchaudio. The optional runtime is installed into its own isolated venv:

```bash
make setup-demucs
make demucs-check
```

The default runtime is `~/.venvs/chordflask-demucs`. Set
`CHORDFLASK_DEMUCS_VENV` to use another location. Demucs model files are kept
in `~/.cache/chordflask-demucs` (or `CHORDFLASK_DEMUCS_CACHE`) and are never
part of the repository or a standalone bundle. The pinned `htdemucs` model is
downloaded by Demucs on the first real processing run.

## Batch command

The command accepts one file or one non-recursive directory:

```bash
scripts/chordflask-demucs --dry-run /music/videos
scripts/chordflask-demucs /music/videos
scripts/chordflask-demucs --replace song.mp4
```

- `--dry-run` reports `CURRENT`, `TODO`, `STALE`, or `ERROR` without writing
  anything.
- A normal run processes `TODO` files, skips `CURRENT` files, and leaves
  `STALE` files unchanged unless `--replace` is supplied.
- `--replace` regenerates the complete four-stem set, never just one stem.
- A malformed analysis JSON is protected and must be repaired separately.

Directory discovery is direct-only and uses the normal MP4, WebM, MP3
same-stem priority. Processing is serial to keep resource use predictable.
Run the preparation once for a directory; re-running reports `CURRENT` for
songs that are already prepared.

## Storage layout

Each successful run stores only FLAC stems below the media directory:

```text
.chordflask/stems/demucs/htdemucs/<media-key>/<generation>/
  bass.flac
  drums.flac
  other.flac
  vocals.flac
```

The analysis JSON registers these four files as one
`audio_tracks["demucs:htdemucs"]` set. The set is current only when all four
files, hashes, dimensions, source identity, model/runtime metadata, and
synchronization facts validate together. Chord/rhythm tracks, Edited data,
user data, and unrelated audio sets are preserved.

The original container audio-stream start time and timeline fields are stored
in the `source_timeline` metadata object when FFprobe provides them. They are
metadata only in this phase: playback applies **no** offset, and the
normalized stems are aligned to the decoded canonical source audio at time
zero.

The JSON is published last. An interrupted run can leave an unreferenced
generation, but cannot make an incomplete four-stem set appear current.

## Player behavior

When a loaded song has a complete stem set, a small **STEMS** control appears
in the chord header. For ordinary songs the control is hidden.

- **STEMS ON** mutes the original media audio and plays the four stems. The
  original media remains the master timeline; the stems follow play, pause,
  seek, repeat, and song changes.
- Click a stem name (**Voc** / **Drm** / **Bass** / **Oth**) to mute/unmute.
  Muting keeps the stored volume.
- Click a percentage to open the single shared volume slider (0–100%, step 5).
  Adjusting one stem does not affect the others.
- STEMS OFF/ON on the same song keeps the per-stem levels; loading a different
  song resets all four to 100%. Levels are session state only — nothing is
  persisted.

Stem loading failure safely returns to the original audio and restores the
original master mute state.

## Known limitations

- Browser playback uses bounded synchronization, not sample-accurate DAW
  playback. Audible sync should be checked on real devices.
- Demucs quality depends on the source and the music.
- Demucs is never run automatically from the GUI.
- The standalone consumes prepared stems but contains no Demucs/Torch.

## Maintenance

Inspect or clean up generated stem data without invoking Demucs:

```bash
scripts/chordflask-maintain stems report /music/videos
scripts/chordflask-maintain stems cleanup /music/videos --orphans
scripts/chordflask-maintain stems cleanup /music/videos --orphans --dry-run
```

`report` shows which media have complete or incomplete sets, missing
referenced files, orphan generation directories, and total/orphan disk usage.
`cleanup --orphans` deletes only unreferenced generation directories; it never
deletes a generation referenced by a valid analysis JSON, never touches
chord/rhythm/user data, and refuses when a worker or Demucs process is active
or an analysis JSON cannot be read safely. See
[docs/MAINTENANCE.md](MAINTENANCE.md).

## Scope boundary

The old `demucs_audio/` directory is historical local reference material. It is
not imported, migrated, or modified by the supported command.
