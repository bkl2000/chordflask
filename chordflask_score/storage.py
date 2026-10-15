"""Read-only input snapshots and atomic, independent Score generations."""

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import re

from chordflask_base import ChordTrackRepository, analysis_json_lock, analysis_json_path, write_atomic
from chordflask_base.analysis import cached_media_source_identity, media_source_identity
from chordflask_demucs.audio import hash_file, probe_source_timeline
from chordflask_demucs.constants import AUDIO_SET_ID
from chordflask_demucs.storage import classify as classify_stems, safe_media_key

from .notation import QUANTIZATION, validate_musicxml, validate_notes
from .runtime import code_identity
from .svg import validate_svg
from .timing import BeatGrid, digest

MAX_JSON = 32 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
ARTIFACT = re.compile(r"original\.mid|notes\.json|score\.musicxml|measures\.json|page-[0-9]{4}\.svg")


class StaleRhythmError(ValueError):
    """The QM track belongs to an older source; replacement needs reanalysis."""


def safe_path(root: Path, relative):
    """Resolve only descendants, rejecting every symlink component, even internal ones."""
    relative = Path(relative)
    if root.is_symlink():
        raise ValueError(f"Symlink storage root is forbidden: {root}")
    if relative.is_absolute() or not relative.parts or any(p in {"..", "."} for p in relative.parts):
        raise ValueError("Unsafe Score path")
    candidate = root
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError(f"Symlink is forbidden in Score storage/input: {candidate}")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError("Score path escapes its storage root")
    return candidate


def score_root(media):
    return safe_path(media.parent, Path(".chordflask") / "scores" / safe_media_key(media))


def read_json(path):
    if not 0 < path.stat().st_size <= MAX_JSON:
        raise ValueError(f"Invalid JSON size: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def input_snapshot(media, audio_source, *, cache_identity=False):
    source = cached_media_source_identity(media) if cache_identity else media_source_identity(media)
    analysis = analysis_json_path(media)
    safe_path(media.parent, analysis.relative_to(media.parent))
    if not analysis.is_file():
        raise ValueError("Score requires existing QM analysis. Run chordflask-analyze first")
    data = ChordTrackRepository().load(analysis)
    if not data.has_rhythm_track("qm_barbeattracker"):
        raise ValueError("Score requires rhythm_tracks[qm_barbeattracker]")
    rhythm = data.rhythm_track_data("qm_barbeattracker")
    grid = BeatGrid.from_track(rhythm)
    provenance = rhythm.get("metadata", {}).get("source_media")
    if provenance is not None and provenance != source:
        raise StaleRhythmError("QM rhythm source is stale; reanalyze the original media")
    inputs = {"source": source, "rhythm": grid.as_dict(), "audio_source": audio_source, "stems": {}}
    if audio_source == "no-vocals":
        status = classify_stems(media)
        if status.label != "CURRENT":
            raise ValueError(f"no-vocals requires current Demucs stems: {status.label}: {status.reason}")
        tracks = data.audio_track_data(AUDIO_SET_ID)["tracks"]
        for name in ("other", "bass", "drums"):
            row = tracks[name]
            path = safe_path(media.parent, row["path"])
            if hash_file(path) != row["sha256"]:
                raise ValueError(f"Demucs {name} stem changed while inspecting it")
            inputs["stems"][name] = {"path": row["path"], "sha256": row["sha256"], "size": row["size"]}
    elif audio_source != "original":
        raise ValueError("Audio source must be original or no-vocals")
    return inputs


def validate_mapping(mapping):
    grid = BeatGrid.from_track(mapping["rhythm"])
    expected = grid.measures()
    rows = mapping["measures"]
    if len(rows) != len(expected):
        raise ValueError("Invalid measure-map count")
    for actual, wanted in zip(rows, expected, strict=True):
        if any(actual.get(key) != value for key, value in wanted.items()):
            raise ValueError("Measure map differs from QM rhythm")
        if type(actual.get("page")) is not int or not 1 <= actual["page"] <= 1024:
            raise ValueError("Invalid measure page")
        if not isinstance(actual.get("svg_id"), str) or not re.fullmatch(r"[A-Za-z_][\w.:-]*", actual["svg_id"]):
            raise ValueError("Invalid measure SVG id")
    coverage = mapping["notation_coverage"]
    if set(coverage) != {"omitted_notes", "clipped_notes"} or any(type(v) is not int or v < 0 for v in coverage.values()):
        raise ValueError("Invalid notation coverage")
    return rows


def validate_artifacts(directory, expected=None):
    names = sorted(p.name for p in directory.iterdir())
    required = {"original.mid", "notes.json", "score.musicxml", "measures.json"}
    if not required.issubset(names) or any(not ARTIFACT.fullmatch(name) for name in names):
        raise ValueError("Score generation has missing/unexpected artifacts")
    pages = [name for name in names if name.endswith(".svg")]
    if not 1 <= len(pages) <= 1024 or pages != [f"page-{p:04d}.svg" for p in range(1, len(pages) + 1)]:
        raise ValueError("Invalid Score page sequence")
    if expected is not None and set(names) != set(expected):
        raise ValueError("Score artifact set differs from manifest")
    total = 0
    artifacts = {}
    for name in names:
        path = safe_path(directory, name)
        size = path.stat().st_size
        total += size
        if not path.is_file() or not 0 < size <= MAX_JSON or total > MAX_TOTAL:
            raise ValueError("Score artifact size/type exceeds limits")
        artifacts[name] = {"size": size, "sha256": hash_file(path)}
    if expected is not None and artifacts != expected:
        raise ValueError("Score artifact integrity differs from manifest")
    mapping = read_json(directory / "measures.json")
    rows = validate_mapping(mapping)
    validate_notes(read_json(directory / "notes.json"))
    validate_musicxml((directory / "score.musicxml").read_bytes(), len(rows))
    # Complete MIDI structure is checked in the producer via pretty_midi; this
    # reader additionally rejects truncated chunk envelopes without heavy imports.
    validate_midi((directory / "original.mid").read_bytes())
    page_ids = {}
    for page, name in enumerate(pages, 1):
        svg = validate_svg((directory / name).read_bytes())
        page_ids[page] = {node.get("id") for node in svg.iter()}
    if any(row["svg_id"] not in page_ids.get(row["page"], set()) for row in rows):
        raise ValueError("Measure map references absent SVG elements")
    return artifacts, mapping


def validate_midi(content):
    if len(content) < 14 or content[:8] != b"MThd\x00\x00\x00\x06":
        raise ValueError("Invalid MIDI header")
    tracks = int.from_bytes(content[10:12], "big")
    if not tracks or not int.from_bytes(content[12:14], "big"):
        raise ValueError("Invalid MIDI track count/division")
    position = 14
    for _ in range(tracks):
        if content[position:position + 4] != b"MTrk" or position + 8 > len(content):
            raise ValueError("Invalid MIDI track header")
        size = int.from_bytes(content[position + 4:position + 8], "big")
        position += 8 + size
        if position > len(content):
            raise ValueError("Truncated MIDI track")
    if position != len(content):
        raise ValueError("Unexpected MIDI trailing data")


@dataclass(frozen=True)
class ScoreStatus:
    label: str
    reason: str


def classify(media, *, audio_source="original", device="auto", runtime=None, quantization="mixed"):
    try:
        inputs = input_snapshot(media, audio_source)
        root = score_root(media)
        path = safe_path(root, "manifest.json")
        if not path.exists():
            return ScoreStatus("TODO", "no complete Score generation")
        manifest = read_json(path)
        if manifest["schema_version"] != 1:
            raise ValueError("Unsupported Score manifest schema")
        generation = manifest["generation"]
        if not isinstance(generation, str) or not re.fullmatch(r"[0-9a-f]{24}", generation):
            raise ValueError("Unsafe Score generation name")
        pipeline = manifest["pipeline"]
        if digest(pipeline) != manifest["pipeline_fingerprint"]:
            raise ValueError("Invalid Score pipeline fingerprint")
        if inputs != manifest["inputs"]:
            return ScoreStatus("STALE", "source, QM rhythm or audio stems changed")
        if pipeline["code"] != code_identity():
            return ScoreStatus("STALE", "Score code changed")
        if pipeline.get("quantization") != list(QUANTIZATION[quantization]) or pipeline.get("hand_split") != 60:
            return ScoreStatus("STALE", "Score notation settings changed")
        if runtime is not None and {k: v for k, v in pipeline["runtime"].items() if k != "cuda"} != {
                k: v for k, v in runtime.items() if k != "cuda"}:
            return ScoreStatus("STALE", "Score runtime changed")
        directory = safe_path(root, generation)
        if not directory.is_dir():
            return ScoreStatus("STALE", "Score generation is missing")
        # Missing/modified reproducible files are stale; unsafe structure is ERROR.
        for name, facts in manifest["artifacts"].items():
            if not ARTIFACT.fullmatch(name):
                raise ValueError("Unsafe artifact path")
            file = safe_path(directory, name)
            if file.is_file() and file.stat().st_size > MAX_JSON:
                raise ValueError("Score artifact exceeds size limit")
            if not file.is_file() or file.stat().st_size != facts["size"] or hash_file(file) != facts["sha256"]:
                return ScoreStatus("STALE", f"Score artifact changed/missing: {name}")
        _, mapping = validate_artifacts(directory, manifest["artifacts"])
        if mapping["rhythm"] != inputs["rhythm"]:
            raise ValueError("Score measure map and source rhythm differ")
        return ScoreStatus("CURRENT", "inputs, pipeline and artifacts match")
    except StaleRhythmError as error:
        return ScoreStatus("STALE", str(error))
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as error:
        return ScoreStatus("ERROR", str(error))


@contextmanager
def score_lock(media):
    root = score_root(media)
    root.mkdir(parents=True, exist_ok=True)
    path = safe_path(root, ".score.lock")
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Score processing is already running for this media") from error
        try:
            yield root
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def publish(media, staged, inputs, pipeline):
    artifacts, mapping = validate_artifacts(staged)
    if mapping["rhythm"] != inputs["rhythm"]:
        raise ValueError("Rendered Score used another rhythm grid")
    timeline = probe_source_timeline(media)
    # Reuse the analysis transaction lock for the final snapshot/commit only.
    # Inference holds no lock on existing chord/rhythm editing.
    with analysis_json_lock(analysis_json_path(media)):
        return _publish_locked(media, staged, inputs, pipeline, artifacts, timeline)


def _publish_locked(media, staged, inputs, pipeline, artifacts, timeline):
    if input_snapshot(media, inputs["audio_source"]) != inputs:
        raise RuntimeError("Source, QM rhythm or stems changed during Score generation")
    root = score_root(media)
    generation = digest({"inputs": inputs, "pipeline": pipeline, "artifacts": artifacts})[:24]
    final = safe_path(root, generation)
    # Persist artifact data before directory rename and the final completion marker.
    for name in artifacts:
        with (staged / name).open("rb") as handle:
            os.fsync(handle.fileno())
    if final.exists():
        validate_artifacts(final, artifacts)
    else:
        os.replace(staged, final)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    manifest = {"schema_version": 1, "generation": generation, "inputs": inputs,
                "pipeline": pipeline, "pipeline_fingerprint": digest(pipeline),
                "artifacts": artifacts, "source_timeline": timeline}
    destination = safe_path(root, "manifest.json")
    write_atomic(destination, manifest)
    return destination
