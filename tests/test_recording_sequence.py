from types import SimpleNamespace

import numpy as np
import pytest

from leica_microscope.recording_sequence import (
    load_sequence_positions, parse_settle_pattern, position_indices, recording_cycles,
)


def test_order_matches_original_ten_position_script_and_today_five():
    expected = np.concatenate([np.arange(40)[i::10] for i in range(10)]).tolist()
    assert position_indices(40, "interleaved", 10) == expected
    assert position_indices(10, "interleaved", 5) == [0, 5, 1, 6, 2, 7, 3, 8, 4, 9]
    assert position_indices(10) == list(range(10))


@pytest.mark.parametrize("text", ["-1", "nan", "inf", "5,,0.5", "word"])
def test_invalid_settling_patterns_are_rejected(text):
    with pytest.raises(ValueError):
        parse_settle_pattern(text)


def test_cycle_overrun_starts_immediately_without_catchup_and_no_final_wait():
    clock = SimpleNamespace(now=0.0)
    starts = []
    for index in recording_cycles(3, 3, clock=lambda: clock.now,
                                  sleep=lambda seconds: setattr(clock, "now", clock.now + seconds)):
        starts.append(clock.now)
        clock.now += 15000 if index == 0 else 20
    assert starts == [0, 15000, 25800]
    assert clock.now == 25820


@pytest.mark.parametrize("text", ["1.5 2 3\n", "1 2\n", "1 2 nan\n"])
def test_invalid_coordinates_fail_before_hardware_use(tmp_path, text):
    path = tmp_path / "positions.txt"
    path.write_text(text)
    with pytest.raises(ValueError):
        load_sequence_positions(path)


def test_position_comments_and_single_position_are_supported(tmp_path):
    path = tmp_path / "positions.txt"
    path.write_text("100 200 300 # wA1p1\n")
    np.testing.assert_array_equal(load_sequence_positions(path), [[100, 200, 300]])
