#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def load_chords(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return [
        {
            "timestamp": float(entry["timestamp"]),
            "chord": str(entry["chord"]),
        }
        for entry in data.get("base_chords", [])
    ]


def event_key(event):
    return (round(event["timestamp"], 9), event["chord"])


def add_durations(chords):
    result = []
    for index, event in enumerate(chords):
        event_with_duration = dict(event)
        if index + 1 < len(chords):
            event_with_duration["duration"] = chords[index + 1]["timestamp"] - event["timestamp"]
        else:
            event_with_duration["duration"] = None
        result.append(event_with_duration)
    return result


def changed_events(old_chords, new_chords):
    old_keys = {event_key(event) for event in old_chords}
    new_keys = {event_key(event) for event in new_chords}
    removed = [event for event in add_durations(old_chords) if event_key(event) not in new_keys]
    added = [event for event in add_durations(new_chords) if event_key(event) not in old_keys]
    return removed, added


def nearest_event(event, candidates):
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: abs(candidate["timestamp"] - event["timestamp"]))


def format_event(event, candidates=None):
    duration = event["duration"]
    if duration is None:
        duration_text = "last"
    else:
        duration_text = f"{duration:.3f}s"
    text = f"{event['timestamp']:9.3f}s  {duration_text:>8}  {event['chord']}"
    nearest = nearest_event(event, candidates or [])
    if nearest:
        delta = nearest["timestamp"] - event["timestamp"]
        text = f"{text}    nearest: {nearest['timestamp']:.3f}s {nearest['chord']} ({delta:+.3f}s)"
    return text


def print_section(title, events, limit, candidates=None):
    print(f"{title}: {len(events)}")
    for event in events[:limit]:
        print(f"  {format_event(event, candidates=candidates)}")
    if len(events) > limit:
        print(f"  ... {len(events) - limit} more")


def main():
    parser = argparse.ArgumentParser(
        description="Compare two ChordFlask JSON files and show added/removed chord events."
    )
    parser.add_argument("old_json", type=Path, help="Original/reference ChordFlask JSON file.")
    parser.add_argument("new_json", type=Path, help="New ChordFlask JSON file.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum events to print per section.")
    args = parser.parse_args()

    old_chords = load_chords(args.old_json)
    new_chords = load_chords(args.new_json)
    removed, added = changed_events(old_chords, new_chords)

    print(f"Old: {args.old_json}")
    print(f"New: {args.new_json}")
    print(f"Chord events: {len(old_chords)} old, {len(new_chords)} new")
    print("")
    print_section("Removed from old", removed, args.limit, candidates=add_durations(new_chords))
    print("")
    print_section("Added in new", added, args.limit, candidates=add_durations(old_chords))


if __name__ == "__main__":
    main()
