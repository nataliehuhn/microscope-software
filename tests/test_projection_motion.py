import unittest

import numpy as np

from leica_microscope.projection_motion import (
    aligned_camera_host_times,
    desired_velocity_steps_s,
    estimate_acceleration_steps,
    estimate_stage_speed,
    estimate_stage_velocity,
    interpolate_frame_positions,
    required_frame_count,
    select_frame_window,
)


class ProjectionMotionTests(unittest.TestCase):
    def setUp(self):
        self.model = {
            "samples": [
                {
                    "speed": 100000,
                    "velocity_steps_s": 10000,
                    "acceleration_steps": 100,
                },
                {
                    "speed": 400000,
                    "velocity_steps_s": 40000,
                    "acceleration_steps": 400,
                },
            ]
        }

    def test_frame_count_is_endpoint_inclusive_and_enforces_minimum(self):
        self.assertEqual(required_frame_count(100, 10, 5), 11)
        self.assertEqual(required_frame_count(10, 10, 5), 5)
        self.assertEqual(required_frame_count(10.1, 10, 2), 3)

    def test_velocity_spans_first_to_last_frame(self):
        self.assertEqual(desired_velocity_steps_s(100, 6, 20), 400)

    def test_speed_model_interpolates_and_extrapolates(self):
        self.assertEqual(estimate_stage_speed(self.model, 20000), 200000)
        self.assertEqual(estimate_stage_speed(self.model, 5000), 50000)
        self.assertEqual(
            estimate_stage_speed(self.model, 80000, max_speed=500000), 500000
        )
        self.assertAlmostEqual(estimate_stage_velocity(self.model, 200000), 20000)

    def test_acceleration_distance_interpolates_by_speed(self):
        self.assertEqual(estimate_acceleration_steps(self.model, 250000), 250)
        self.assertEqual(estimate_acceleration_steps(self.model, 50000), 50)

    def test_camera_ticks_remove_host_retrieval_jitter(self):
        timing = {
            "host_times_s": np.array([10.03, 10.11, 10.20]),
            "camera_ticks": np.array([1000, 1100, 1200], dtype=np.uint64),
            "camera_tick_frequency_hz": 1000.0,
        }
        aligned = aligned_camera_host_times(timing)
        np.testing.assert_allclose(np.diff(aligned), [0.1, 0.1])

    def test_frame_positions_interpolate_from_stage_samples(self):
        positions = interpolate_frame_positions(
            np.array([1.0, 1.5, 2.0]),
            [(0.5, 0), (1.5, 100), (2.5, 200)],
        )
        np.testing.assert_allclose(positions, [50, 100, 150])

    def test_selects_contiguous_window_nearest_both_endpoints(self):
        positions = np.array([-20, -10, 1, 11, 21, 30], dtype=float)
        self.assertEqual(select_frame_window(positions, 3, 0, 20), 2)

    def test_selects_reverse_direction_window(self):
        positions = np.array([120, 110, 99, 89, 79, 70], dtype=float)
        self.assertEqual(select_frame_window(positions, 3, 100, 80), 2)


if __name__ == "__main__":
    unittest.main()
