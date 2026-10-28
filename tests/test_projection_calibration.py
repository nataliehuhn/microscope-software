import unittest
import warnings

from leica_microscope.microscope import Microscope


class FakeCamera:
    def __init__(self, fps=30.0):
        self.fps = fps

    def getFramerate(self):
        return self.fps


class CalibrationMicroscope(Microscope):
    def __init__(self, camera_duration, stage_model):
        self.cam = FakeCamera()
        self.camera_duration = camera_duration
        self.stage_model = stage_model
        self.position = 100000
        self.speed = 123456
        self.max_speed = 8820000
        self.calibrated_proj_speed = None
        self.projection_calibration = None
        self.measured_speeds = []
        self.positions = []
        self.fail_stage_measurement = False

    def getZRange(self):
        return -1, 9999999

    def getZPos(self):
        return self.position

    def setZPos(self, position):
        self.position = position
        self.positions.append(position)

    def getZSpeed(self):
        return self.speed

    def setZSpeed(self, speed):
        self.speed = speed

    def getZSpeedMax(self):
        return self.max_speed

    def _measureCameraDuration(self, n_slices):
        return self.camera_duration

    def _measureZMoveDuration(self, z_start, z_stop, speed, reposition_speed):
        self.measured_speeds.append(speed)
        self.position = z_stop
        self.speed = speed
        if self.fail_stage_measurement:
            raise RuntimeError("synthetic stage failure")
        return self.stage_model(speed)


class ProjectionCalibrationTests(unittest.TestCase):
    @staticmethod
    def stage_model(speed):
        # Monotonic model with a fixed acceleration/communication overhead.
        return 0.2 + 2400000.0 / speed

    def test_converges_and_restores_state(self):
        mic = CalibrationMicroscope(3.4, self.stage_model)

        result = mic.calibrateZSpeedForStack(
            z=100000, z_start=0, z_stop=250000, n_slices=100
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "calibrated")
        self.assertLessEqual(
            abs(result["trials"][-1]["error_s"]), result["tolerance_s"]
        )
        self.assertLessEqual(len(result["trials"]), 6)
        self.assertEqual(mic.position, 100000)
        self.assertEqual(mic.speed, 123456)
        self.assertEqual(mic.calibrated_proj_speed, result["selected_speed"])

    def test_reports_physical_max_speed_limit_after_confirmation(self):
        mic = CalibrationMicroscope(0.3, self.stage_model)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = mic.calibrateZSpeedForStack(
                z=100000, z_start=0, z_stop=25000, n_slices=5
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "max_speed_limited")
        self.assertEqual(result["selected_speed"], mic.max_speed)
        self.assertEqual(len(result["trials"]), 3)
        self.assertEqual(len(caught), 1)
        self.assertIn("unreachable", str(caught[0].message))
        self.assertEqual(mic.position, 100000)
        self.assertEqual(mic.speed, 123456)

    def test_max_speed_limit_uses_median_of_three_near_boundary(self):
        durations = iter([1.16, 1.02, 1.04])
        mic = CalibrationMicroscope(1.04, lambda speed: next(durations))

        result = mic.calibrateZSpeedForStack(
            z=100000, z_start=0, z_stop=80000, n_slices=30
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "calibrated")
        self.assertEqual(result["selected_speed"], mic.max_speed)
        self.assertEqual(len(result["trials"]), 3)
        self.assertEqual(
            result["representative_trials"][0]["aggregation"], "median"
        )
        self.assertAlmostEqual(
            result["representative_trials"][0]["duration_s"], 1.04
        )

    def test_iteration_limit_uses_best_measured_trial(self):
        mic = CalibrationMicroscope(3.4, self.stage_model)

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = mic.calibrateZSpeedForStack(
                z=100000,
                z_start=0,
                z_stop=250000,
                n_slices=100,
                max_iterations=1,
            )

        self.assertEqual(result["status"], "max_iterations")
        self.assertEqual(result["selected_speed"], mic.max_speed)
        self.assertEqual(mic.position, 100000)
        self.assertEqual(mic.speed, 123456)

    def test_successful_previous_calibration_warm_starts_next_run(self):
        mic = CalibrationMicroscope(3.4, self.stage_model)
        mic.projection_calibration = {
            "success": True,
            "selected_speed": 750000,
            "reported_fps": 30.0,
            "camera_duration_s": 3.4,
            "travel_steps": 250000,
        }

        result = mic.calibrateZSpeedForStack(
            z=100000, z_start=0, z_stop=250000, n_slices=100
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["warm_start_speed"], 750000)
        self.assertEqual(mic.measured_speeds[:2], [mic.max_speed, 750000])
        self.assertEqual(len(result["trials"]), 2)

    def test_escapes_acceleration_limited_speed_plateau(self):
        def plateau_model(speed):
            if speed >= 2000000:
                return 1.0
            return 3.0 - speed / 1000000.0

        mic = CalibrationMicroscope(1.5, plateau_model)

        result = mic.calibrateZSpeedForStack(
            z=100000, z_start=0, z_stop=80000, n_slices=40
        )

        self.assertTrue(result["success"])
        self.assertLessEqual(len(result["representative_trials"]), 5)
        self.assertTrue(any(speed < 2000000 for speed in mic.measured_speeds))

    def test_fast_recording_refuses_unsuccessful_calibration(self):
        mic = CalibrationMicroscope(0.3, self.stage_model)
        mic.calibrated_proj_speed = mic.max_speed
        mic.projection_calibration = {
            "success": False,
            "status": "max_speed_limited",
            "n_slices": 5,
            "travel_steps": 25000,
        }

        with self.assertRaisesRegex(RuntimeError, "recording refused"):
            mic.recordFastStackToBuffer(
                z=100000, z_start=0, z_stop=25000, n_slices=5
            )

    def test_rejects_invalid_geometry_before_moving(self):
        mic = CalibrationMicroscope(1.0, self.stage_model)

        with self.assertRaises(ValueError):
            mic.calibrateZSpeedForStack(
                z=100000, z_start=0, z_stop=0, n_slices=10
            )
        with self.assertRaises(ValueError):
            mic.calibrateZSpeedForStack(
                z=100000, z_start=0, z_stop=1000, n_slices=0
            )

        self.assertEqual(mic.positions, [])
        self.assertEqual(mic.measured_speeds, [])

    def test_stage_failure_still_restores_position_and_speed(self):
        mic = CalibrationMicroscope(3.4, self.stage_model)
        mic.fail_stage_measurement = True

        with self.assertRaisesRegex(RuntimeError, "synthetic stage failure"):
            mic.calibrateZSpeedForStack(
                z=100000, z_start=0, z_stop=250000, n_slices=100
            )

        self.assertEqual(mic.position, 100000)
        self.assertEqual(mic.speed, 123456)


if __name__ == "__main__":
    unittest.main()
