# Per-song Journal

On desktop, **Journal** beside **Files** opens a compact expandable panel for
the loaded song. Click again to close it. Files and Journal share the area:
opening either closes the other. Playback continues. Tablet and smartphone
layouts have no Journal controls.

**+ Add note** opens the editor without a position, for a song-wide Note, Info,
or Agent entry. **+ Add at current position** snapshots playback seconds once.
The optional position field stays editable while typing; leave it empty to make
an entry song-wide, or enter seconds to position it (including `0` for the start).
Both actions use the same editor.

Song-wide entries appear first, in saved order (editing keeps their place).
Positioned entries follow in chronological order. Click a displayed timestamp
to seek the loaded media without starting playback. The panel scrolls vertically
for many entries or long text. Entries support Edit and Delete (with confirmation).
In normal desktop Journal view, visible timestamps briefly invert their colors
from their playback time until two playback seconds later. This highlighting
stops during Add/Edit, resumes after Save/Cancel, and never scrolls the panel.

- **Note**: personal notes, with text and an optional timestamp.
- **Info**: factual context about the song, version, or recording.
- **Agent**: a quality observation for later external investigation, with type
  General, Chord, Lyrics, or Rhythm, a Q/problem description, optional short
  A/resolution, and a resolved checkbox. Resolve sets a UTC `resolved_at`;
  reopening clears it. Chord reports can include an optional expected chord.

Agent is a category only; Journal never invokes an AI agent. Reports are quality
signals, **not verified labels or ML ground truth**. Use the existing chord Edit
workflow when you already want to change analysis. Journal does not edit it.
Keep resolutions short and human-readable, for example “Fixed: LRC offset
corrected by about 3.8 s.” Do not put transcripts, debug logs, commit SHAs,
implementation details, or investigation history here.

## Storage and developer contract

Journal is optional, user-authored data separate from analysis JSON. `FileRepr`
owns its path: `<media directory>/.chordflask/journals/<full media filename>.journal.json`,
for example `.chordflask/journals/song.mp3.journal.json`. Including the media
extension avoids same-stem recording collisions; the separate directory avoids
collisions with analysis for media named `song.mp3.journal.mp4`.
Existing `.chordy` fallback behavior is
the same as other `FileRepr` paths. No file or storage directory is created on
a missing-file read. After the last deletion, a minimal empty schema file stays.

Schema version 1 has `schema_version` and `entries`. Entries have stable opaque
`id` strings, `timestamp` values of `null` (whole song) or finite non-negative
numbers in playback seconds, and
`category` (`note`, `info`, `agent`). Note and Info have `text`. Agent has `kind`
(`general`, `chord`, `lyrics`, `rhythm`), `question`, nullable `answer`, boolean
`resolved`, and nullable UTC ISO `resolved_at`. Only Chord reports additionally
have nullable `expected_chord`. Current displayed chord/range capture is deferred.
Existing numeric-timestamp journals remain valid without rewriting or migration;
the schema version remains 1.

```json
{
    "schema_version": 1,
    "entries": [
        {
            "id": "4bf63740a1544a61b52b17c0b7d82db5",
            "timestamp": 67.2,
            "category": "agent",
            "kind": "lyrics",
            "question": "Lyrics are clearly shifted here.",
            "answer": null,
            "resolved": false,
            "resolved_at": null
        }
    ]
}
```

`POST /journal` uses the existing validated `dirname`/`filename` media identity.
Actions are `load` (default), `add`/`edit` with `entry`, `delete` with `id`, and
`resolve` with `id` and boolean `resolved`. Edit also takes `id`. Dates and new
IDs are server-owned. Mutations use the existing per-path process lock and
atomic JSON writer (fsync, replace). Malformed or unsupported files produce an
error and block writes; they are never silently reset. Switching songs discards
the form and ignores responses for the previous song.

Analysis/reanalysis never overwrites Journal. Maintenance storage reports list
the `journals` directory as **protected user journals** (including lock files).
Analysis validation/migration scan only top-level JSON and skip journals,
even malformed ones; generic cleanup preserves them. There is no new maintenance
subsystem or whole-journal CLI deletion. To remove an entire journal explicitly,
delete that exact sidecar yourself when it is not being edited. External tools
can scan `*.journal.json` for `category == "agent"` and `resolved == false`.
