"""Repetition schedules shared by ordinary and optimized recordings."""

import math
import time


def duration_repetitions(wait_since_last, duration_s, interval_s,
                         clock=time.monotonic):
    """Yield indices until a recording starts at or after the duration.

    A final acquisition is deliberately allowed across the deadline so the
    requested observation window is covered, rather than ending one interval
    early. The caller's existing wait function keeps its usual interval rules.
    """
    duration_s = float(duration_s)
    interval_s = float(interval_s)
    if not math.isfinite(duration_s) or duration_s <= 0:
        raise ValueError("Recording duration must be positive and finite")
    if not math.isfinite(interval_s) or interval_s < 0:
        raise ValueError("Repetition interval must be nonnegative and finite")
    deadline = clock() + duration_s
    repetition = 0
    while True:
        if repetition and clock() >= deadline:
            break
        wait_since_last(interval_s)
        yield repetition
        repetition += 1
