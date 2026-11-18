"""Long recordings must cover their requested elapsed time."""

import pytest

from leica_microscope.recording_schedule import duration_repetitions


def test_duration_runs_past_old_repetition_limit_and_covers_deadline():
    now = [0.0]
    starts = []

    def wait(interval):
        if starts:
            now[0] += interval
        starts.append(now[0])

    for rep in duration_repetitions(wait, 4 * 3600, 15, lambda: now[0]):
        assert rep == len(starts) - 1
    assert len(starts) == 961  # 4 h at 15 s, including the endpoint
    assert starts[-1] >= 4 * 3600


def test_duration_finishes_last_scan_after_deadline():
    now = [0.0]

    def wait(interval):
        now[0] += interval

    seen = []
    for rep in duration_repetitions(wait, 10, 6, lambda: now[0]):
        seen.append((rep, now[0]))
    assert seen == [(0, 6), (1, 12)]


@pytest.mark.parametrize("duration,interval", [(0, 1), (-1, 1), (1, -1)])
def test_invalid_duration_schedule_is_rejected(duration, interval):
    with pytest.raises(ValueError):
        next(duration_repetitions(lambda _: None, duration, interval))
