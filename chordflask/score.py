"""Read validated, complete Score generations without an inference runtime."""

from hashlib import sha256
import re
import xml.etree.ElementTree as ET

from chordflask_score.storage import (
    input_snapshot, read_json, safe_path, score_root, validate_artifacts,
)
from chordflask_score.svg import validate_svg
from chordflask_score.timing import digest


def read_score_midi(media):
    """Return original MIDI from the validated active generation, or None."""
    try:
        root = score_root(media)
        manifest_path = safe_path(root, "manifest.json")
        manifest = read_json(manifest_path)
        directory, metadata = read_score(media)
        if manifest["generation"] != metadata["generation"]:
            return None
        content = safe_path(directory, "original.mid").read_bytes()
        facts = manifest["artifacts"]["original.mid"]
        # Validate the actual exported bytes and detect concurrent publication.
        if (len(content) != facts["size"] or sha256(content).hexdigest() != facts["sha256"]
                or read_json(manifest_path) != manifest):
            return None
        return content
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError):
        return None


def read_score(media):
    root = score_root(media)
    manifest = read_json(safe_path(root, "manifest.json"))
    generation = manifest["generation"]
    if manifest["schema_version"] != 1 or not isinstance(generation, str) or not re.fullmatch(r"[0-9a-f]{24}", generation):
        raise ValueError("Invalid Score generation")
    if digest(manifest["pipeline"]) != manifest["pipeline_fingerprint"]:
        raise ValueError("Invalid Score pipeline fingerprint")
    inputs = input_snapshot(media, manifest["inputs"]["audio_source"], cache_identity=True)
    if inputs != manifest["inputs"]:
        raise ValueError("Score inputs are stale")
    directory = safe_path(root, generation)
    try:
        _, mapping = validate_artifacts(directory, manifest["artifacts"])
    except ET.ParseError as error:
        raise ValueError("Malformed Score document") from error
    if mapping["rhythm"] != inputs["rhythm"]:
        raise ValueError("Score rhythm is stale")
    # Persisted notation is readable across producer upgrades. Runtime/code
    # freshness remains a producer concern, not a display prerequisite.
    return directory, {"generation": generation, "measures": mapping["measures"],
                       "pages": sum(name.endswith(".svg") for name in manifest["artifacts"])}


def read_page(media, page, generation):
    directory, metadata = read_score(media)
    if generation != metadata["generation"]:
        raise ValueError("Score generation changed")
    if not 1 <= page <= metadata["pages"]:
        raise ValueError("Invalid Score page")
    content = safe_path(directory, f"page-{page:04d}.svg").read_bytes()
    try:
        validate_svg(content)
    except ET.ParseError as error:
        raise ValueError("Malformed Score SVG") from error
    # Recheck bytes actually served, not merely a file inspected earlier.
    manifest = read_json(safe_path(score_root(media), "manifest.json"))
    if manifest["generation"] != generation or sha256(content).hexdigest() != manifest["artifacts"][f"page-{page:04d}.svg"]["sha256"]:
        raise ValueError("Score page changed")
    return content
