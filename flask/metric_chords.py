import math
import statistics


def _is_finite_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _valid_beat_numbers(beat_numbers, meter):
    if not isinstance(beat_numbers, list):
        return False
    for bn in beat_numbers:
        if not isinstance(bn, int) or isinstance(bn, bool) or not (1 <= bn <= meter):
            return False
    return True


def classify_beat_grid(beat_times, beat_numbers, meter):
    if not isinstance(beat_times, list):
        return {
            "classification": "flexible",
            "beat_count": 0,
            "meter": meter,
            "reason": "beat_times is not a list",
        }

    result = {
        "classification": "uncertain",
        "beat_count": len(beat_times),
        "meter": meter,
    }

    if len(beat_times) < 32:
        result["reason"] = f"insufficient beats ({len(beat_times)} < 32)"
        return result

    if not isinstance(meter, int) or isinstance(meter, bool) or meter <= 0:
        result["classification"] = "flexible"
        result["reason"] = f"meter not a positive integer: {meter!r}"
        return result

    if not isinstance(beat_numbers, list) or len(beat_numbers) != len(beat_times):
        result["classification"] = "flexible"
        result["reason"] = "beat_numbers missing or length mismatch"
        return result

    if not _valid_beat_numbers(beat_numbers, meter):
        result["classification"] = "flexible"
        result["reason"] = "beat_numbers contain values outside 1..meter"
        return result

    for i, bt in enumerate(beat_times):
        if not _is_finite_number(bt) or bt < 0:
            result["classification"] = "flexible"
            result["reason"] = f"beat_times[{i}] is not a valid finite non-negative number"
            return result

    for i in range(1, len(beat_times)):
        if beat_times[i] <= beat_times[i - 1]:
            result["classification"] = "flexible"
            result["reason"] = f"non-increasing beat_time at index {i}"
            return result

    intervals = [beat_times[i] - beat_times[i - 1] for i in range(1, len(beat_times))]
    if any(interval <= 0 for interval in intervals):
        result["classification"] = "flexible"
        result["reason"] = "non-positive interval"
        return result

    cycle_ok = 0
    for i in range(len(beat_numbers) - 1):
        expected = (beat_numbers[i] % meter) + 1
        if beat_numbers[i + 1] == expected:
            cycle_ok += 1
    cycle_fraction = cycle_ok / max(len(beat_numbers) - 1, 1)

    mean_interval = statistics.mean(intervals)
    std_interval = statistics.stdev(intervals) if len(intervals) > 1 else 0.0
    cv = std_interval / mean_interval if mean_interval > 0 else float("inf")

    median_interval = statistics.median(intervals)
    deviations = [abs(interval - median_interval) for interval in intervals]
    mad = statistics.median(deviations)
    mad_ratio = mad / median_interval if median_interval > 0 else float("inf")

    deviant_count = sum(
        1 for interval in intervals
        if abs(interval - median_interval) / median_interval > 0.2
    ) if median_interval > 0 else len(intervals)
    deviant_fraction = deviant_count / len(intervals)

    result["intervals_count"] = len(intervals)
    result["mean_interval"] = round(mean_interval, 4)
    result["cv"] = round(cv, 4)
    result["mad_ratio"] = round(mad_ratio, 4)
    result["deviant_fraction"] = round(deviant_fraction, 4)
    result["cycle_pass_fraction"] = round(cycle_fraction, 4)

    if cycle_fraction < 0.95:
        result["classification"] = "flexible"
        result["reason"] = f"cycle pass {cycle_fraction:.2%} < 95%"
    elif cv > 0.06:
        result["classification"] = "flexible"
        result["reason"] = f"CV {cv:.4f} > 0.06"
    elif mad_ratio > 0.04:
        result["classification"] = "flexible"
        result["reason"] = f"MAD/median {mad_ratio:.4f} > 0.04"
    elif deviant_fraction > 0.10:
        result["classification"] = "flexible"
        result["reason"] = f"intervals deviating >20%: {deviant_fraction:.2%} > 10%"
    else:
        result["classification"] = "stable"

    return result


def is_strong_beat(beat_number, meter):
    if not isinstance(beat_number, int) or isinstance(beat_number, bool) or beat_number <= 0:
        return False
    if not isinstance(meter, int) or isinstance(meter, bool) or meter <= 0:
        return False
    if beat_number == 1:
        return True
    if meter % 2 == 0 and beat_number == (meter // 2) + 1:
        return True
    return False


def _compute_suppressed_beats(beat_chords, beat_times, beat_numbers, beat_chord_indexes,
                               meter, raw_chord_times):
    suppressed = set()

    for i in range(1, len(beat_chords) - 1):
        prev_chord = beat_chords[i - 1][1]
        curr_chord = beat_chords[i][1]
        next_chord = beat_chords[i + 1][1]

        if curr_chord == prev_chord or curr_chord == next_chord or prev_chord != next_chord:
            continue

        if "" in (prev_chord, curr_chord, next_chord):
            continue

        if i >= len(beat_numbers):
            continue
        beat_num = beat_numbers[i]
        if not isinstance(beat_num, int) or isinstance(beat_num, bool) or beat_num <= 0:
            continue
        if is_strong_beat(beat_num, meter):
            continue

        if i >= len(beat_chord_indexes):
            continue
        raw_idx = beat_chord_indexes[i]
        if not isinstance(raw_idx, int) or isinstance(raw_idx, bool):
            continue
        if raw_idx < 0 or raw_idx >= len(raw_chord_times) - 1:
            continue

        curr_raw_ts = raw_chord_times[raw_idx]
        next_raw_ts = raw_chord_times[raw_idx + 1]
        if not _is_finite_number(curr_raw_ts) or not _is_finite_number(next_raw_ts):
            continue
        raw_duration = next_raw_ts - curr_raw_ts
        if raw_duration <= 0:
            continue

        local_interval = beat_times[i] - beat_times[i - 1]
        if local_interval <= 0:
            continue

        if raw_duration < 0.75 * local_interval:
            suppressed.add(i)

    return suppressed


def filter_metric_chords(beat_chords, beat_times, beat_numbers, beat_chord_indexes,
                          meter, raw_chord_times):
    if not isinstance(beat_chords, list):
        return [], {"classification": "flexible",
                     "reason": "beat_chords is not a list"}
    if not isinstance(beat_times, list) or not isinstance(beat_numbers, list):
        return list(beat_chords), {"classification": "flexible",
                                    "reason": "beat_times or beat_numbers is not a list"}
    if not isinstance(beat_chord_indexes, list) or not isinstance(raw_chord_times, list):
        return list(beat_chords), {"classification": "flexible",
                                    "reason": "beat_chord_indexes or raw_chord_times is not a list"}

    if len(beat_chords) != len(beat_times):
        return list(beat_chords), {
            "classification": "flexible",
            "reason": "beat_chords and beat_times length mismatch",
        }
    if len(beat_chord_indexes) != len(beat_times):
        return list(beat_chords), {
            "classification": "flexible",
            "reason": "beat_chord_indexes and beat_times length mismatch",
        }

    for i, beat_chord in enumerate(beat_chords):
        if (
            not isinstance(beat_chord, (list, tuple))
            or len(beat_chord) != 2
            or not _is_finite_number(beat_chord[0])
            or not isinstance(beat_chord[1], str)
        ):
            return list(beat_chords), {
                "classification": "flexible",
                "reason": f"beat_chords[{i}] is invalid",
            }

    for i, chord_time in enumerate(raw_chord_times):
        if not _is_finite_number(chord_time) or chord_time < 0:
            return list(beat_chords), {
                "classification": "flexible",
                "reason": f"raw_chord_times[{i}] is invalid",
            }
        if i > 0 and chord_time < raw_chord_times[i - 1]:
            return list(beat_chords), {
                "classification": "flexible",
                "reason": f"raw_chord_times are decreasing at index {i}",
            }

    for i, chord_index in enumerate(beat_chord_indexes):
        if (
            not isinstance(chord_index, int)
            or isinstance(chord_index, bool)
            or chord_index < 0
            or chord_index >= len(raw_chord_times)
        ):
            return list(beat_chords), {
                "classification": "flexible",
                "reason": f"beat_chord_indexes[{i}] is invalid",
            }

    classification = classify_beat_grid(beat_times, beat_numbers, meter)
    if classification["classification"] != "stable":
        return list(beat_chords), classification

    suppressed = _compute_suppressed_beats(
        beat_chords, beat_times, beat_numbers, beat_chord_indexes, meter, raw_chord_times,
    )
    classification["suppressed_count"] = len(suppressed)

    if not suppressed:
        return list(beat_chords), classification

    filtered = list(beat_chords)
    for i in sorted(suppressed):
        filtered[i] = (filtered[i][0], filtered[i - 1][1])

    return filtered, classification


def format_classification_diagnostic(classification):
    if not isinstance(classification, dict):
        return "metric_chords: no classification available"
    cls = classification.get("classification", "unknown")
    if cls == "stable":
        suppressed = classification.get("suppressed_count", 0)
        return (
            f"metric_chords: stable "
            f"(beats={classification.get('beat_count', '?')} "
            f"cv={classification.get('cv', '?')} "
            f"mad_ratio={classification.get('mad_ratio', '?')} "
            f"deviant={classification.get('deviant_fraction', '?')} "
            f"cycle={classification.get('cycle_pass_fraction', '?')}) "
            f"suppressed={suppressed}"
        )
    reason = classification.get("reason", "")
    return f"metric_chords: {cls}" + (f" ({reason})" if reason else "")
