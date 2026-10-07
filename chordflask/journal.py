"""Small, independent per-recording user journals; never analysis labels."""

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from chordflask_base import analysis_json_lock, write_atomic


def validate_entry(entry):
    if not isinstance(entry, dict):
        raise ValueError("Journal entry must be an object")
    category = entry.get("category")
    if category not in ("note", "info", "agent"):
        raise ValueError("Unknown journal category")
    timestamp = entry.get("timestamp")
    if "timestamp" not in entry or (timestamp is not None and (
            isinstance(timestamp, bool) or not isinstance(timestamp, (int, float))
            or not math.isfinite(timestamp) or timestamp < 0)):
        raise ValueError("Timestamp must be null or finite, non-negative seconds")
    result = {"timestamp": timestamp, "category": category}
    field = "question" if category == "agent" else "text"
    text = entry.get(field)
    if not isinstance(text, str) or not text.strip() or len(text) > 10000:
        raise ValueError(f"{field} must contain text (maximum 10000 characters)")
    result[field] = text.strip()
    if category == "agent":
        kind = entry.get("kind")
        if kind not in ("general", "chord", "lyrics", "rhythm"):
            raise ValueError("Unknown Agent problem type")
        answer = entry.get("answer")
        if answer is not None and (not isinstance(answer, str) or len(answer) > 2000):
            raise ValueError("Answer must be text (maximum 2000 characters)")
        resolved = entry.get("resolved", False)
        if not isinstance(resolved, bool):
            raise ValueError("resolved must be a boolean")
        result.update(kind=kind, answer=(answer or "").strip() or None,
                      resolved=resolved, resolved_at=None)
        if kind == "chord":
            expected = entry.get("expected_chord")
            if expected is not None and (not isinstance(expected, str) or len(expected) > 100):
                raise ValueError("Expected chord must be short text")
            result["expected_chord"] = (expected or "").strip() or None
    return result


def entry_order(entry):
    # Stable sorting retains file/insertion order for song-wide entries.
    return (entry["timestamp"] is not None, entry["timestamp"] or 0)


def load_journal(path):
    """Missing means empty. Malformed/unsupported data fails without overwriting."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema_version": 1, "entries": []}
    if (not isinstance(data, dict) or type(data.get("schema_version")) is not int
            or data["schema_version"] != 1 or not isinstance(data.get("entries"), list)):
        raise ValueError("Unsupported or malformed journal schema")
    ids = set()
    entries = []
    for entry in data["entries"]:
        clean = validate_entry(entry)
        identity = entry.get("id")
        if not isinstance(identity, str) or not identity or identity in ids:
            raise ValueError("Journal IDs must be unique non-empty strings")
        ids.add(identity)
        clean["id"] = identity
        if clean["category"] == "agent":
            resolved_at = entry.get("resolved_at")
            if clean["resolved"]:
                if not isinstance(resolved_at, str):
                    raise ValueError("Resolved Agent entry needs resolved_at")
                datetime.fromisoformat(resolved_at)
                clean["resolved_at"] = resolved_at
            elif resolved_at is not None:
                raise ValueError("Open Agent entry must have no resolved_at")
        entries.append(clean)
    return {"schema_version": 1, "entries": sorted(entries, key=entry_order)}


def update_journal(path, action, entry=None, entry_id=None, resolved=None):
    """Serialize mutations; keep an empty schema file after the last deletion."""
    if action not in ("add", "edit", "delete", "resolve"):
        raise ValueError("Unknown journal action")
    with analysis_json_lock(path):
        data = load_journal(path)
        entries = data["entries"]
        previous = next((e for e in entries if e["id"] == entry_id), None) if action != "add" else None
        if action != "add" and previous is None:
            raise ValueError("Journal entry no longer exists")
        if action in ("add", "edit"):
            clean = validate_entry(entry)
            clean["id"] = previous["id"] if previous else uuid4().hex
            if clean["category"] == "agent" and clean["resolved"]:
                clean["resolved_at"] = (
                    previous.get("resolved_at") if previous else None
                ) or datetime.now(timezone.utc).isoformat()
            if previous:
                entries[entries.index(previous)] = clean
            else:
                entries.append(clean)
        elif action == "delete":
            entries.remove(previous)
        elif action == "resolve":
            if previous["category"] != "agent" or not isinstance(resolved, bool):
                raise ValueError("Resolve requires an Agent entry and boolean resolved")
            previous["resolved"] = resolved
            previous["resolved_at"] = (
                previous["resolved_at"] or datetime.now(timezone.utc).isoformat()
            ) if resolved else None
        entries.sort(key=entry_order)
        write_atomic(path, data)
        return data
