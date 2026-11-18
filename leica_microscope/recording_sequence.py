"""Position order and whole-route timing, with no microscope connection."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import time

import numpy as np


def _value(config, section, key, default):
    if config.has_option(section, key):
        value = config.get(section, key)
        if isinstance(value, str):
            value = value.strip()
            if value.startswith('"') and value.endswith('"'):
                value = json.loads(value)
        return value
    return default


def _positive_integer(value, name):
    number = float(value)
    if not math.isfinite(number) or number < 1 or int(number) != number:
        raise ValueError("{} must be a positive whole number".format(name))
    return int(number)


def parse_settle_pattern(value):
    """A comma-separated sequence repeats over visits, starting at each cycle."""
    if not str(value).strip():
        return ()
    try:
        pattern = tuple(float(part.strip()) for part in str(value).split(","))
    except ValueError:
        raise ValueError("Position settling times must be comma-separated seconds, e.g. 5,5,0.5,0.5")
    if any(not math.isfinite(delay) or delay < 0 for delay in pattern):
        raise ValueError("Position settling times must be finite and nonnegative")
    return pattern


@dataclass(frozen=True)
class SequenceSettings:
    position_order: str = "as_saved"
    positions_per_condition: int = 5
    settle_pattern: tuple = ()
    cycle_count: int = 1
    cycle_interval_hours: float = 3.0

    @classmethod
    def from_config(cls, config):
        order = _value(config, "position_sequence", "position_order", "as_saved")
        if order not in ("as_saved", "interleaved"):
            raise ValueError("Unknown position order: {!r}".format(order))
        block_size = _positive_integer(_value(
            config, "position_sequence", "positions_per_condition", 5,
        ), "Positions per condition")
        pattern = parse_settle_pattern(_value(
            config, "position_sequence", "settle_pattern_s", "",
        ))
        count = _positive_integer(_value(config, "cycles", "cycle_count", 1), "Cycle count")
        interval = float(_value(config, "cycles", "cycle_interval_hours", 3.0))
        if (not math.isfinite(interval) or interval < 0
                or (count > 1 and interval == 0)):
            raise ValueError("Cycle interval must be positive when repeating the full route")
        return cls(order, block_size, pattern, count, interval)


def position_indices(count, order="as_saved", positions_per_condition=5):
    count = _positive_integer(count, "Number of positions")
    if order == "as_saved":
        return list(range(count))
    if order != "interleaved":
        raise ValueError("Unknown position order: {!r}".format(order))
    block_size = _positive_integer(positions_per_condition, "Positions per condition")
    if count % block_size:
        raise ValueError(
            "{} saved positions cannot be split into conditions of {} positions. "
            "Store each condition together with the same number of positions."
            .format(count, block_size)
        )
    return [index for offset in range(block_size)
            for index in range(offset, count, block_size)]


def load_sequence_positions(filename):
    """Validate the position file before any microscope initialization or move."""
    positions = np.loadtxt(str(filename), ndmin=2)
    if (positions.size == 0 or positions.shape[1] != 3
            or not np.all(np.isfinite(positions))
            or not np.all(positions == np.round(positions))):
        raise ValueError("The positions file must contain one integer X Y Z row per position")
    return positions.astype(np.int64)


def sequence_rows(positions, settings):
    order = position_indices(len(positions), settings.position_order,
                             settings.positions_per_condition)
    grouped = settings.position_order == "interleaved"
    return [dict(
        visit=visit + 1, saved_position=index + 1,
        condition=index // settings.positions_per_condition + 1 if grouped else None,
        position_in_condition=index % settings.positions_per_condition + 1 if grouped else None,
        xyz_steps=[int(value) for value in positions[index]],
        settle_seconds=settings.settle_pattern[visit % len(settings.settle_pattern)]
        if settings.settle_pattern else 0.0,
    ) for visit, index in enumerate(order)]


def write_sequence_manifest(filename, positions, settings):
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(
        position_order=settings.position_order,
        positions_per_condition=settings.positions_per_condition,
        cycle_count=settings.cycle_count,
        cycle_interval_hours=settings.cycle_interval_hours,
        filename_position_index="zero-based original row in the positions file",
        visits=sequence_rows(positions, settings),
    )
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def recording_cycles(count, interval_hours, clock=None, sleep=None):
    """Start-to-start cycles; overruns start immediately without catch-up bursts."""
    count = _positive_integer(count, "Cycle count")
    period = float(interval_hours) * 3600
    if not math.isfinite(period) or period < 0 or (count > 1 and period == 0):
        raise ValueError("Cycle interval must be positive when repeating the full route")
    clock = time.monotonic if clock is None else clock
    sleep = time.sleep if sleep is None else sleep
    previous_start = None
    for cycle in range(count):
        if previous_start is not None:
            deadline = previous_start + period
            remaining = deadline - clock()
            if remaining < 0:
                print("Previous cycle exceeded its interval by {:.1f} s; starting the next cycle now."
                      .format(-remaining))
            elif remaining > 0:
                print("Waiting {:.1f} min before the next full cycle.".format(remaining / 60))
            while remaining > 0:
                sleep(min(remaining, 1.0))
                remaining = deadline - clock()
        previous_start = clock()
        print("Cycle {}/{} started at {}".format(
            cycle + 1, count, time.strftime("%Y-%m-%d %H:%M:%S"),
        ))
        yield cycle


def cycle_output_folder(base_folder, cycle, interval_hours):
    """Unique folders retain nominal schedule labels; actual starts are logged."""
    folder = Path(base_folder) / "cycle_{:03d}_{:g}h".format(cycle + 1, cycle * interval_hours)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def wait_for_position_repeat(previous_start, interval_seconds):
    """Return the next local repetition start, independent of other positions."""
    interval = float(interval_seconds)
    if not math.isfinite(interval) or interval < 0:
        raise ValueError("Repetition interval must be finite and nonnegative")
    if previous_start is not None:
        remaining = previous_start + interval - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)
    return time.monotonic()
