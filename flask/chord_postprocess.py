import os
import re


NOTE_TO_PC = {
    "C": 0,
    "C#": 1,
    "Db": 1,
    "D": 2,
    "D#": 3,
    "Eb": 3,
    "E": 4,
    "Fb": 4,
    "E#": 5,
    "F": 5,
    "F#": 6,
    "Gb": 6,
    "G": 7,
    "G#": 8,
    "Ab": 8,
    "A": 9,
    "A#": 10,
    "Bb": 10,
    "B": 11,
    "Cb": 11,
    "B#": 0,
}
ROOT_PATTERN = re.compile(r"^([A-G](?:#|b)?)")
MAJOR_SCALE = [0, 2, 4, 5, 7, 9, 11]
MAJOR_QUALITIES = {
    0: "major",
    2: "minor",
    4: "minor",
    5: "major",
    7: "major",
    9: "minor",
    11: "diminished",
}
MINOR_SCALE = [0, 2, 3, 5, 7, 8, 10]
MINOR_QUALITIES = {
    0: "minor",
    2: "diminished",
    3: "major",
    5: "minor",
    7: "major",
    8: "major",
    10: "major",
}
TRIAD_SUFFIXES = {"major": "", "minor": "m", "diminished": "dim", "dominant": "7"}
SEVENTH_SUFFIXES = {"major": "maj7", "minor": "m7", "diminished": "m7b5", "dominant": "7"}


class ChordPostProcessor:
    """
    Optional cleanup for raw chord engine output.

    Smooth mode removes short chord segments and merges adjacent equal chords.
    Key correction uses the estimated key as a weak, transposition-invariant
    prior for chord quality candidates with the same root.
    """

    def __init__(
        self,
        enabled=False,
        min_duration_seconds=0.5,
        key_correction_enabled=False,
        correction_margin=0.25,
    ):
        self.enabled = enabled
        self.min_duration_seconds = min_duration_seconds
        self.key_correction_enabled = key_correction_enabled
        self.correction_margin = correction_margin
        self.estimated_key_pc = None
        self.estimated_key_mode = None

    @classmethod
    def from_environment(cls):
        enabled = os.environ.get("CHORDIFIER_POSTPROCESS", "0").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        key_correction_enabled = os.environ.get("CHORDIFIER_KEY_CORRECT", "0").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        min_duration = float(os.environ.get("CHORDIFIER_POSTPROCESS_MIN_DURATION", "0.5"))
        correction_margin = float(os.environ.get("CHORDIFIER_KEY_CORRECT_MARGIN", "0.25"))
        return cls(
            enabled=enabled,
            min_duration_seconds=min_duration,
            key_correction_enabled=key_correction_enabled,
            correction_margin=correction_margin,
        )

    def process(self, chords, beat_times=None):
        if not self.enabled:
            return chords
        if len(chords) < 2:
            return list(chords)

        processed = self._merge_adjacent_equal_chords(chords)
        processed = self._remove_short_chords(processed)
        processed = self._merge_adjacent_equal_chords(processed)
        if self.key_correction_enabled:
            processed = self._correct_chord_qualities(processed)
            processed = self._merge_adjacent_equal_chords(processed)
        return processed

    def _merge_adjacent_equal_chords(self, chords):
        merged = []
        for chord in chords:
            if merged and merged[-1]["chord"] == chord["chord"]:
                continue
            merged.append(dict(chord))
        return merged

    def _remove_short_chords(self, chords):
        if len(chords) < 2:
            return chords

        cleaned = []
        for index, current_chord in enumerate(chords):
            if index == len(chords) - 1:
                cleaned.append(current_chord)
                continue

            duration = self._duration_until_next(chords, index)
            if duration >= self.min_duration_seconds:
                cleaned.append(current_chord)

        if not cleaned:
            return [chords[-1]]

        return cleaned

    def _correct_chord_qualities(self, chords):
        key_pc, key_mode = self._estimate_key(chords)
        self.estimated_key_pc = key_pc
        self.estimated_key_mode = key_mode
        corrected = []
        for index, chord in enumerate(chords):
            corrected.append(self._correct_one_chord(chords, index, key_pc, key_mode))
        return corrected

    def _estimate_key(self, chords):
        best_key = (0, "major")
        best_score = None
        for key_pc, mode in ((key_pc, mode) for mode in ("major", "minor") for key_pc in range(12)):
            score = 0.0
            for index, chord in enumerate(chords):
                parsed = self._parse_chord(chord["chord"])
                if not parsed:
                    continue
                weight = self._chord_duration(chords, index)
                expected_quality = self._expected_quality(parsed["root_pc"], key_pc, mode)
                if expected_quality:
                    score += weight
                    if parsed["quality"] == expected_quality:
                        score += weight * 0.5
                    elif parsed["quality"] == "dominant" and expected_quality == "major":
                        score += weight * 0.35
                elif self._is_scale_degree(parsed["root_pc"], key_pc, mode):
                    score += weight * 0.3
            if best_score is None or score > best_score:
                best_key = (key_pc, mode)
                best_score = score
        return best_key

    def _correct_one_chord(self, chords, index, key_pc, key_mode):
        chord = chords[index]
        parsed = self._parse_chord(chord["chord"])
        if not parsed or not self._is_simple_triad(parsed):
            return dict(chord)

        candidates = self._quality_candidates(parsed, key_pc, key_mode)
        if len(candidates) <= 1:
            return dict(chord)

        original_score = self._score_candidate(chords, index, parsed, parsed, key_pc, key_mode)
        best_candidate = parsed
        best_score = original_score
        for candidate in candidates:
            score = self._score_candidate(chords, index, parsed, candidate, key_pc, key_mode)
            if score > best_score:
                best_score = score
                best_candidate = candidate

        if best_candidate["label"] != parsed["label"] and best_score >= original_score + self.correction_margin:
            changed = dict(chord)
            changed["chord"] = best_candidate["label"]
            return changed

        return dict(chord)

    def _is_simple_triad(self, parsed):
        return (
            not parsed["slash"]
            and not parsed["has_extension"]
            and parsed["quality"] in {"major", "minor"}
        )

    def _quality_candidates(self, parsed, key_pc, key_mode):
        expected_quality = self._expected_quality(parsed["root_pc"], key_pc, key_mode)
        if expected_quality != "minor":
            expected_quality = None
        qualities = {parsed["quality"]}
        if expected_quality:
            qualities.add(expected_quality)
        candidates = []
        suffixes = SEVENTH_SUFFIXES if parsed["has_seventh"] else TRIAD_SUFFIXES
        for quality in qualities:
            suffix = suffixes.get(quality, "")
            candidates.append({
                "label": f"{parsed['root']}{suffix}",
                "root": parsed["root"],
                "root_pc": parsed["root_pc"],
                "quality": quality,
                "slash": None,
                "has_seventh": parsed["has_seventh"],
            })
        return candidates

    def _score_candidate(self, chords, index, original, candidate, key_pc, key_mode):
        score = 0.0
        expected_quality = self._expected_quality(candidate["root_pc"], key_pc, key_mode)
        if expected_quality == candidate["quality"]:
            score += 1.0
        elif candidate["quality"] == "dominant" and expected_quality == "major":
            score += 0.85
        elif self._is_scale_degree(candidate["root_pc"], key_pc, key_mode):
            score += 0.25

        if candidate["label"] == original["label"]:
            score += 0.45

        score += self._context_score(chords, index, candidate, key_pc, key_mode)
        return score

    def _context_score(self, chords, index, candidate, key_pc, key_mode):
        score = 0.0
        for neighbor_index in (index - 1, index + 1):
            if not 0 <= neighbor_index < len(chords):
                continue
            neighbor = self._parse_chord(chords[neighbor_index]["chord"])
            if not neighbor:
                continue
            if self._expected_quality(neighbor["root_pc"], key_pc, key_mode):
                score += 0.2
            if neighbor["quality"] == candidate["quality"]:
                score += 0.05
        return score

    def _expected_quality(self, root_pc, key_pc, key_mode):
        degree = (root_pc - key_pc) % 12
        if key_mode == "minor":
            return MINOR_QUALITIES.get(degree)
        return MAJOR_QUALITIES.get(degree)

    def _is_scale_degree(self, root_pc, key_pc, key_mode):
        degree = (root_pc - key_pc) % 12
        if key_mode == "minor":
            return degree in MINOR_SCALE
        return degree in MAJOR_SCALE

    def _parse_chord(self, label):
        if not label or label == "N":
            return None
        base_label = label.split("/")[0]
        slash = label.split("/", 1)[1] if "/" in label else None
        match = ROOT_PATTERN.match(base_label)
        if not match:
            return None
        root = match.group(1)
        suffix = base_label[len(root):]
        suffix_lower = suffix.lower()
        if root not in NOTE_TO_PC:
            return None
        return {
            "label": label,
            "root": root,
            "root_pc": NOTE_TO_PC[root],
            "quality": self._quality_from_suffix(suffix),
            "has_seventh": "7" in suffix_lower,
            "has_extension": self._has_extension(suffix_lower),
            "slash": slash,
        }

    def _quality_from_suffix(self, suffix):
        suffix_lower = suffix.lower()
        if "dim" in suffix_lower or "m7b5" in suffix_lower:
            return "diminished"
        if suffix_lower.startswith("m") and not suffix_lower.startswith("maj"):
            return "minor"
        if "7" in suffix_lower and "maj" not in suffix_lower:
            return "dominant"
        return "major"

    def _has_extension(self, suffix_lower):
        return bool(suffix_lower) and suffix_lower not in {"m", "min"}

    def _chord_duration(self, chords, index):
        if index < len(chords) - 1:
            return max(0.0, self._duration_until_next(chords, index))
        if index > 0:
            return max(0.0, self._duration_until_next(chords, index - 1))
        return 1.0

    def _duration_until_next(self, chords, index):
        return float(chords[index + 1]["timestamp"]) - float(chords[index]["timestamp"])
