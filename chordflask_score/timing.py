"""Strict QM grid and invertible audio-second/quarter-position mapping."""

import bisect
import hashlib
import json
import math
from dataclasses import dataclass


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class BeatGrid:
    times: tuple
    numbers: tuple
    meter: int

    @classmethod
    def from_track(cls, track):
        times = track.get("beat_times")
        numbers = track.get("beat_numbers")
        meter = track.get("meter_signature")
        if type(meter) is not int or not 1 <= meter <= 32:
            raise ValueError("QM rhythm needs one fixed integer meter (1..32)")
        if not isinstance(times, list) or len(times) < 2 or not isinstance(numbers, list):
            raise ValueError("QM rhythm needs at least two timed, numbered beats")
        if len(times) != len(numbers):
            raise ValueError("QM beat_times and beat_numbers lengths differ")
        if any(type(t) not in (int, float) or not math.isfinite(t) or t < 0 for t in times):
            raise ValueError("QM beat times must be finite and nonnegative")
        if any(b <= a for a, b in zip(times, times[1:], strict=False)):
            raise ValueError("QM beat times must increase strictly")
        if any(type(n) is not int or not 1 <= n <= meter for n in numbers):
            raise ValueError("QM beat numbers do not fit the fixed meter")
        if any(b != a % meter + 1 for a, b in zip(numbers, numbers[1:], strict=False)):
            raise ValueError("QM beat numbers must advance cyclically; meter changes unsupported")
        return cls(tuple(float(t) for t in times), tuple(numbers), meter)

    @property
    def first_quarter(self):
        return self.numbers[0] - 1

    @property
    def last_quarter(self):
        return self.first_quarter + len(self.times) - 1

    def to_quarter(self, seconds):
        if not self.times[0] <= seconds <= self.times[-1]:
            raise ValueError("Time lies outside the measured QM beat range")
        index = min(bisect.bisect_right(self.times, seconds) - 1, len(self.times) - 2)
        fraction = (seconds - self.times[index]) / (self.times[index + 1] - self.times[index])
        return self.first_quarter + index + fraction

    def to_seconds(self, quarter):
        position = quarter - self.first_quarter
        if not 0 <= position <= len(self.times) - 1:
            raise ValueError("Quarter lies outside the measured QM beat range")
        index = min(int(position), len(self.times) - 2)
        return self.times[index] + (position - index) * (self.times[index + 1] - self.times[index])

    def measures(self):
        result = []
        start = self.first_quarter
        number = 0 if start else 1
        while start < self.last_quarter:
            end = min((int(start // self.meter) + 1) * self.meter, self.last_quarter)
            result.append({"number": number, "start_quarter": start,
                           "end_quarter": end, "start_seconds": self.to_seconds(start),
                           "end_seconds": self.to_seconds(end)})
            number += 1
            start = end
        return result

    def as_dict(self):
        return {"beat_times": list(self.times), "beat_numbers": list(self.numbers),
                "meter_signature": self.meter}
