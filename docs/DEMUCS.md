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
scripts/chordflask-demucs --device auto song.mp4
scripts/chordflask-demucs --device cpu song.mp4
scripts/chordflask-demucs --device cuda song.mp4
```

- `--dry-run` reports `CURRENT`, `TODO`, `STALE`, or `ERROR` without writing
  anything.
- A normal run processes `TODO` files, skips `CURRENT` files, and leaves
  `STALE` files unchanged unless `--replace` is supplied.
- `--replace` regenerates the complete four-stem set, never just one stem.
- A malformed analysis JSON is protected and must be repaired separately.

`--device auto` selects CUDA when the inspected Torch runtime reports it
available, otherwise CPU. `--device cpu` and `--device cuda` request those
devices explicitly. The resolved effective device is stored and participates
in `CURRENT`/`STALE` classification; moving between CPU and CUDA can therefore
make an existing set `STALE`.

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
`audio_tracks["demucs:htdemucs"]` set. `CURRENT` means its provider and model,
source hash and size, and all four FLAC stem files still validate against the
registered paths, hashes, sizes, and audio facts. The complete runtime check
also compares the stored processing device and pipeline fingerprint, which
tracks the `htdemucs` model, Demucs and Torch versions, effective device, and
the fixed output/synchronization configuration. Otherwise the set is `STALE`.
Chord/rhythm tracks, Edited data, user data, and unrelated audio sets are
preserved.

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

Individual stem OFF intentionally uses an effectively silent nonzero gain
instead of browser mute or exact-zero volume. Real Chromium playback timing
tests found that fully silent media elements could remain playing and ready
while their clocks diverged from the other stems. This is deliberate
synchronization behavior, not an audio-level workaround; browser timing must be
re-tested before changing it.

Stem loading failure safely returns to the original audio and restores the
original master mute state.

## Optional stem caching

By default ChordFlask serves stem audio with `no-store` semantics. Starting the
web player with `chordflask --stem-cache` enables versioned stem URLs and
private cache-friendly response headers, so a browser may avoid transferring
unchanged stems repeatedly. This option is optional and experimental. It is a
transfer/cache performance option, not a claimed fix for Android or other
mobile playback interruptions.

## Known limitations

Verified 2026-08-20: STEM playback works on localhost with Firefox and works
very well over a remote LAN with desktop Chromium. Repeated individual stem
OFF/ON toggles no longer accumulate drift in the tested local and desktop
Chromium cases. Remote-LAN Firefox remains unreliable and may leave **Stem
playback unavailable** visible. This currently appears to be a
Firefox/remote-origin media playback compatibility issue; the exact
browser-side cause has not been isolated. Chromium/Chrome is the recommended
browser for STEM playback.

Remote-LAN Android Chromium still exhibits the earlier timeout/dropout
behavior, including with `--stem-cache`. Current evidence points to a separate
mobile browser media-pipeline, buffering, or scheduling limitation; the stem
mute/synchronization fix does not address it.

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
