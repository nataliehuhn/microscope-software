"""Timing and motion helpers for pre-accelerated Z projections."""

import math

import numpy as np


def required_frame_count(distance_um, requested_spacing_um, minimum_frames):
    """Return an endpoint-inclusive frame count with a required minimum."""
    distance_um = float(distance_um)
    requested_spacing_um = float(requested_spacing_um)
    minimum_frames = int(minimum_frames)
    if not np.isfinite(distance_um) or distance_um <= 0:
        raise ValueError("distance_um must be positive")
    if not np.isfinite(requested_spacing_um) or requested_spacing_um <= 0:
        raise ValueError("requested_spacing_um must be positive")
    if minimum_frames < 2:
        raise ValueError("minimum_frames must be at least 2")
    nominal_frames = int(math.ceil(distance_um / requested_spacing_um)) + 1
    return max(minimum_frames, nominal_frames)


def desired_velocity_steps_s(distance_steps, frame_count, fps):
    """Velocity that spans the distance between first and last frame."""
    distance_steps = abs(float(distance_steps))
    frame_count = int(frame_count)
    fps = float(fps)
    if distance_steps <= 0:
        raise ValueError("distance_steps must be positive")
    if frame_count < 2:
        raise ValueError("frame_count must be at least 2")
    if not np.isfinite(fps) or fps <= 0:
        raise ValueError("fps must be positive")
    return distance_steps * fps / (frame_count - 1)


def _valid_velocity_samples(model):
    samples = []
    for sample in model.get("samples", []):
        speed = float(sample["speed"])
        velocity = float(sample["velocity_steps_s"])
        if speed > 0 and velocity > 0 and np.isfinite(speed) and np.isfinite(velocity):
            samples.append((velocity, speed, sample))
    if not samples:
        raise ValueError("The pre-acceleration velocity model has no valid samples")
    return sorted(samples, key=lambda item: item[0])


def estimate_stage_speed(model, target_velocity_steps_s, max_speed=None):
    """Estimate a Leica speed command by log interpolation/extrapolation."""
    target_velocity_steps_s = float(target_velocity_steps_s)
    if not np.isfinite(target_velocity_steps_s) or target_velocity_steps_s <= 0:
        raise ValueError("target_velocity_steps_s must be positive")
    samples = _valid_velocity_samples(model)

    if target_velocity_steps_s <= samples[0][0]:
        velocity, speed, _ = samples[0]
        candidate = speed * target_velocity_steps_s / velocity
    elif target_velocity_steps_s >= samples[-1][0]:
        velocity, speed, _ = samples[-1]
        candidate = speed * target_velocity_steps_s / velocity
    else:
        for lower, upper in zip(samples[:-1], samples[1:]):
            if lower[0] <= target_velocity_steps_s <= upper[0]:
                log_fraction = (
                    (np.log(target_velocity_steps_s) - np.log(lower[0]))
                    / (np.log(upper[0]) - np.log(lower[0]))
                )
                candidate = np.exp(
                    np.log(lower[1])
                    + log_fraction * (np.log(upper[1]) - np.log(lower[1]))
                )
                break

    candidate = max(1, int(round(candidate)))
    if max_speed is not None:
        candidate = min(int(max_speed), candidate)
    return candidate


def estimate_stage_velocity(model, selected_speed):
    """Estimate steady velocity for a Leica speed command."""
    selected_speed = float(selected_speed)
    if not np.isfinite(selected_speed) or selected_speed <= 0:
        raise ValueError("selected_speed must be positive")
    by_speed = sorted(
        (float(sample["speed"]), float(sample["velocity_steps_s"]))
        for _, _, sample in _valid_velocity_samples(model)
    )
    if selected_speed <= by_speed[0][0]:
        speed, velocity = by_speed[0]
        return velocity * selected_speed / speed
    if selected_speed >= by_speed[-1][0]:
        speed, velocity = by_speed[-1]
        return velocity * selected_speed / speed
    for lower, upper in zip(by_speed[:-1], by_speed[1:]):
        if lower[0] <= selected_speed <= upper[0]:
            fraction = (
                (np.log(selected_speed) - np.log(lower[0]))
                / (np.log(upper[0]) - np.log(lower[0]))
            )
            return float(
                np.exp(
                    np.log(lower[1])
                    + fraction * (np.log(upper[1]) - np.log(lower[1]))
                )
            )


def estimate_acceleration_steps(model, selected_speed):
    """Interpolate the measured distance required to reach steady velocity."""
    samples = [
        (float(sample["speed"]), float(sample.get("acceleration_steps", 0)))
        for _, _, sample in _valid_velocity_samples(model)
    ]
    samples = sorted(samples)
    speeds = np.array([item[0] for item in samples], dtype=float)
    distances = np.array([max(0.0, item[1]) for item in samples], dtype=float)
    if len(samples) == 1:
        return int(math.ceil(distances[0] * float(selected_speed) / speeds[0]))
    selected_speed = float(selected_speed)
    if selected_speed <= speeds[0]:
        distance = distances[0] * selected_speed / speeds[0]
    elif selected_speed >= speeds[-1]:
        distance = distances[-1] * selected_speed / speeds[-1]
    else:
        distance = np.interp(selected_speed, speeds, distances)
    return int(math.ceil(distance))


def aligned_camera_host_times(timing):
    """Use hardware tick intervals while anchoring them to monotonic host time."""
    host_times = np.asarray(timing["host_times_s"], dtype=float)
    if host_times.ndim != 1:
        raise ValueError("host_times_s must be one-dimensional")
    camera_ticks = timing.get("camera_ticks")
    tick_frequency = timing.get("camera_tick_frequency_hz")
    if camera_ticks is None or tick_frequency is None or len(host_times) < 2:
        return host_times
    camera_ticks = np.asarray(camera_ticks, dtype=np.float64)
    tick_frequency = float(tick_frequency)
    if tick_frequency <= 0 or len(camera_ticks) != len(host_times):
        return host_times
    relative_camera_s = (camera_ticks - camera_ticks[0]) / tick_frequency
    host_offset = float(np.median(host_times - relative_camera_s))
    return host_offset + relative_camera_s


def interpolate_frame_positions(frame_times_s, position_samples):
    """Interpolate Z position for each frame from monotonic host-time samples."""
    frame_times_s = np.asarray(frame_times_s, dtype=float)
    if len(position_samples) < 2:
        raise ValueError("At least two position samples are required")
    ordered = sorted(position_samples, key=lambda sample: sample[0])
    sample_times = np.asarray([sample[0] for sample in ordered], dtype=float)
    sample_positions = np.asarray([sample[1] for sample in ordered], dtype=float)
    unique = np.concatenate(([True], np.diff(sample_times) > 0))
    sample_times = sample_times[unique]
    sample_positions = sample_positions[unique]
    if len(sample_times) < 2:
        raise ValueError("Position sample times are not distinct")
    if frame_times_s[0] < sample_times[0] or frame_times_s[-1] > sample_times[-1]:
        raise ValueError("Position samples do not span all camera frame times")
    return np.interp(frame_times_s, sample_times, sample_positions)


def select_frame_window(frame_positions, frame_count, start, stop):
    """Choose a contiguous frame window that best matches both Z endpoints."""
    frame_positions = np.asarray(frame_positions, dtype=float)
    frame_count = int(frame_count)
    start = float(start)
    stop = float(stop)
    if frame_positions.ndim != 1:
        raise ValueError("frame_positions must be one-dimensional")
    if frame_count < 2 or frame_count > len(frame_positions):
        raise ValueError("frame_count is outside the acquired frame range")
    if start == stop:
        raise ValueError("start and stop must differ")
    direction = 1.0 if stop > start else -1.0
    signed_positions = direction * frame_positions
    signed_start = direction * start
    signed_stop = direction * stop

    candidates = []
    for index in range(len(frame_positions) - frame_count + 1):
        first_error = abs(signed_positions[index] - signed_start)
        last_error = abs(
            signed_positions[index + frame_count - 1] - signed_stop
        )
        backwards = np.count_nonzero(
            np.diff(signed_positions[index:index + frame_count]) < 0
        )
        candidates.append(
            (
                int(backwards),
                max(first_error, last_error),
                first_error + last_error,
                index,
            )
        )
    return min(candidates)[-1]
