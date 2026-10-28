import runpy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from leica_microscope.microscope import Microscope


class TimedProjectionGuiTests(unittest.TestCase):
    def make_microscope(self, times):
        microscope = Microscope.__new__(Microscope)
        microscope.send_command_and_wait = Mock(
            side_effect=lambda command, *args: (
                0 if command == "70028" else [-1, 0]
            )
        )
        microscope.setShutter = Mock()
        microscope.cam = Mock()
        microscope.cam.exposure.return_value = 3.0
        microscope.cam.getMaximumFramerateAtShortExposure.return_value = 29.1
        microscope.cam.getImage.return_value = np.full(
            (2, 2), 20, dtype=np.uint8
        )
        microscope.cam.getMaxValue.return_value = 255
        image_min = np.array([[2, 10], [20, 30]], dtype=np.uint8)
        image_max = np.array([[5, 15], [25, 30]], dtype=np.uint8)
        min_indices = np.array([[0, 1], [2, 3]], dtype=np.uint8)
        max_indices = np.array([[3, 2], [1, 0]], dtype=np.uint8)
        microscope.recordTimedContinuousProjection = Mock(side_effect=[
            (image_min, image_max, min_indices, max_indices, {
                "actual_scan_time_s": value,
                "coverage_fraction": 0.99,
                "selected_speed": 100000,
                "selected_frame_count": 30,
                "camera_exposure_ms": 34.1,
            }) for value in times
        ])
        microscope.getZSpeedMin = Mock(return_value=1)
        microscope.getZSpeedMax = Mock(return_value=8820000)
        microscope.saveImage = Mock()
        microscope.memmap_writer = None
        microscope.used_disk_space = 0
        return microscope

    def test_timed_projection_saves_unmodified_legacy_image_names(self):
        microscope = self.make_microscope([1.0])
        result = microscope.rec_timed_continuous_projection(
            "projection_{z}.tif", -100, 100, 1.0
        )
        names = [str(call[0][0]) for call in microscope.saveImage.call_args_list]
        self.assertEqual(names, [
            "projection_MinProj.tif",
            "projection_MaxProj.tif",
            "projection_MinIndices30.tif",
            "projection_MaxIndices30.tif",
        ])
        np.testing.assert_array_equal(
            microscope.saveImage.call_args_list[0][0][1],
            np.array([[2, 10], [20, 30]], dtype=np.uint8),
        )
        self.assertEqual(result["attempts"][0]["actual_scan_time_s"], 1.0)
        self.assertEqual(
            microscope.saveImage.call_args_list[0][0][2]["Exposure"],
            "34.1",
        )
        microscope.setShutter.assert_any_call(0)

    def test_timed_projection_retries_out_of_tolerance_scan(self):
        microscope = self.make_microscope([1.1, 1.0])
        result = microscope.rec_timed_continuous_projection(
            "projection_{z}.tif", -100, 100, 1.0
        )
        self.assertEqual(len(result["attempts"]), 2)
        self.assertFalse(result["attempts"][0]["accepted"])
        self.assertTrue(result["attempts"][1]["accepted"])
        self.assertEqual(
            microscope.recordTimedContinuousProjection.call_args_list[1][1][
                "speed_override"
            ], 110000,
        )
        self.assertEqual(microscope.saveImage.call_count, 4)

    def test_queued_projection_keeps_raw_images_names_and_metadata(self):
        microscope = self.make_microscope([1.0])
        microscope.getMetadata = Mock(return_value={"Mode": 0, "Time": "now"})
        microscope.cam.getMetadata.return_value = {"BitDepth": 255}
        queued = []
        microscope.rec_timed_continuous_projection(
            "projection_{z}.tif", -100, 100, 1.0,
            center_z_steps=1000, leave_at_edge=True,
            save_callback=queued.append,
        )
        self.assertEqual(len(queued), 1)
        self.assertEqual([str(item[0]) for item in queued[0]], [
            "projection_MinProj.tif", "projection_MaxProj.tif",
            "projection_MinIndices30.tif", "projection_MaxIndices30.tif",
        ])
        np.testing.assert_array_equal(queued[0][0][1],
                                      np.array([[2, 10], [20, 30]]))
        self.assertEqual(queued[0][0][2]["Exposure"], "34.1")
        self.assertEqual(queued[0][0][2]["Mode"], 0)
        self.assertEqual(queued[0][0][2]["BitDepth"], 255)
        microscope.saveImage.assert_not_called()

    def test_index_tiffs_use_uint16_after_256_frames(self):
        microscope = self.make_microscope([1.0])
        response = list(next(
            microscope.recordTimedContinuousProjection.side_effect
        ))
        response[-1] = dict(response[-1], selected_frame_count=300)
        microscope.recordTimedContinuousProjection.side_effect = [tuple(response)]
        microscope.rec_timed_continuous_projection(
            "projection_{z}.tif", -100, 100, 1.0
        )
        call = microscope.saveImage.call_args_list[2][0]
        self.assertEqual(str(call[0]), "projection_MinIndices300.tif")
        self.assertEqual(call[1].dtype, np.uint16)

    def test_timed_projection_rejects_dark_brightfield_before_motion(self):
        microscope = self.make_microscope([1.0])
        microscope.cam.getImage.return_value = np.zeros((2, 2), dtype=np.uint8)
        with self.assertRaisesRegex(RuntimeError, "nearly black"):
            microscope.rec_timed_continuous_projection(
                "projection_{z}.tif", -100, 100, 1.0
            )
        microscope.recordTimedContinuousProjection.assert_not_called()
        microscope.saveImage.assert_not_called()
        microscope.setShutter.assert_any_call(0)

    def generate(self, folder, projection_mode, has_mode_option=True,
                 old_projection=False, slice_start=-3, slice_stop=3,
                 repetition_count=1, repetition_time_delta=5.0,
                 wait_before_image=0, modes=None,
                 positions_filename=None):
        stack = SimpleNamespace(
            projection=old_projection, projection_mode=projection_mode,
            projection_start_um=-300.0, projection_stop_um=300.0,
            projection_time_s=4.0,
            slice_start=slice_start, slice_stop=slice_stop,
            slice_thickness=10.0,
        )
        config = SimpleNamespace(
            general=SimpleNamespace(record_modes=[], wait_at_start=0,
                                    wait_before_image=wait_before_image),
            files=SimpleNamespace(target_folder=str(folder),
                                  positions_filename=positions_filename),
            grid=SimpleNamespace(countx=1, county=1),
            repetition=SimpleNamespace(
                repeat_positions_separately=False,
                repetition_count=repetition_count,
                repetition_time_delta=repetition_time_delta,
            ),
            stack=stack,
            has_option=lambda section, key: (
                has_mode_option if key == "projection_mode"
                else old_projection if key == "projection"
                else False
            ),
        )
        with patch("leica_microscope.includes.helper_functions.getConfig",
                   return_value=(config, "20260923-000000")), patch(
                "leica_microscope.includes.helper_functions.modesToDictList",
                return_value=[{}] if modes is None else modes), patch("os.system", return_value=0), patch(
                "os.chdir"):
            runpy.run_module("leica_microscope.generate_record", run_name="__main__")
        return (folder / "20260923-000000_record.py").read_text()

    def test_generated_script_uses_optimized_mode_by_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = self.generate(Path(directory), "optimized")
        self.assertIn("mic.rec_timed_continuous_projection(", generated)
        self.assertIn("z_start_um=-300.0", generated)
        self.assertIn("scan_time_s=4.0", generated)
        self.assertNotIn("mic.rec_projection(", generated)
        compile(generated, "generated_record.py", "exec")

    def test_generated_optimized_repetitions_use_alternating_series(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = self.generate(
                Path(directory), "optimized", repetition_count=5,
                repetition_time_delta=5.0, wait_before_image=0.2,
            )
        self.assertIn("mic.rec_timed_continuous_projection_series(", generated)
        self.assertIn("repetition_count=5", generated)
        self.assertIn("repetition_time_delta=5.0", generated)
        self.assertIn("wait_before_image_s=0.2", generated)
        self.assertNotIn("for rep in", generated)
        compile(generated, "generated_record.py", "exec")

    def test_generated_multiple_modes_keep_edge_and_recheck_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = self.generate(
                Path(directory), "optimized", repetition_count=2,
                modes=[{"mode": 0}, {"mode": 1}],
            )
        self.assertIn("with mic.timed_projection_session() as timed_series:",
                      generated)
        self.assertIn("timed_series.invalidate_preflight()", generated)
        self.assertIn("timed_series.record(", generated)
        self.assertNotIn("rec_timed_continuous_projection_series", generated)
        compile(generated, "generated_record.py", "exec")

    def test_generated_multiple_positions_restore_z_before_xy(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = self.generate(
                Path(directory), "optimized", repetition_count=2,
                positions_filename="positions.txt",
            )
        self.assertIn("timed_series.finish_position()\n", generated)
        self.assertIn("mic.setPos(pos)", generated)
        self.assertIn("timed_series.record(", generated)
        compile(generated, "generated_record.py", "exec")

    def test_series_alternates_and_restores_center(self):
        with tempfile.TemporaryDirectory() as directory:
            microscope = Microscope.__new__(Microscope)
            microscope.getZPos = Mock(side_effect=[1000, 1300])
            microscope.getZSpeed = Mock(return_value=77)
            microscope.getZSpeedMax = Mock(return_value=999)
            microscope.setZSpeed = Mock()
            microscope.setZPos = Mock()
            microscope.waitSinceLast = Mock()
            microscope.used_disk_space = 0
            calls = []

            def record(path, start, stop, duration, **kwargs):
                calls.append((path, start, stop, duration, kwargs))
                kwargs["save_callback"]([(
                    str(Path(directory) / "pass{}.tif".format(len(calls))),
                    np.full((2, 2), len(calls), dtype=np.uint8),
                    {"Projection": "max"},
                )])
                return {"preflight": {"mean": 10}}

            microscope.rec_timed_continuous_projection = Mock(
                side_effect=record
            )
            results = microscope.rec_timed_continuous_projection_series(
                str(Path(directory) / "scan_rep{repetition:03}_{z}.tif"),
                -300, 300, 2.0, repetition_count=3,
                repetition_time_delta=5.0,
            )
            self.assertEqual(len(results), 3)
            self.assertEqual([(item[1], item[2]) for item in calls], [
                (-300, 300), (300, -300), (-300, 300),
            ])
            self.assertEqual([item[4]["center_z_steps"] for item in calls],
                             [1000, 1000, 1000])
            self.assertTrue(all(item[4]["leave_at_edge"] for item in calls))
            self.assertIsNone(calls[0][4]["cached_preflight"])
            self.assertEqual(calls[1][4]["cached_preflight"], {"mean": 10})
            self.assertEqual(microscope.waitSinceLast.call_count, 3)
            microscope.setZSpeed.assert_any_call(999)
            microscope.setZPos.assert_called_once_with(1000)
            microscope.setZSpeed.assert_any_call(77)
            self.assertEqual(len(list(Path(directory).glob("pass*.tif"))), 3)

    def test_series_restores_center_when_recording_fails(self):
        microscope = Microscope.__new__(Microscope)
        microscope.getZPos = Mock(side_effect=[1000, 1300])
        microscope.getZSpeed = Mock(return_value=77)
        microscope.getZSpeedMax = Mock(return_value=999)
        microscope.setZSpeed = Mock()
        microscope.setZPos = Mock()
        microscope.waitSinceLast = Mock()
        microscope.rec_timed_continuous_projection = Mock(
            side_effect=RuntimeError("camera failed")
        )
        with self.assertRaisesRegex(RuntimeError, "camera failed"):
            microscope.rec_timed_continuous_projection_series(
                "scan_rep{repetition:03}_{z}.tif", -300, 300, 2.0, 2
            )
        microscope.setZPos.assert_called_once_with(1000)
        microscope.setZSpeed.assert_any_call(77)

    def test_session_alternates_across_modes_but_resets_at_new_position(self):
        microscope = Microscope.__new__(Microscope)
        microscope.getZPos = Mock(side_effect=[1000, 1300, 2000, 2300])
        microscope.getZSpeed = Mock(side_effect=[77, 88])
        microscope.getZSpeedMax = Mock(return_value=999)
        microscope.setZSpeed = Mock()
        microscope.setZPos = Mock()
        calls = []

        def record(path, start, stop, duration, **kwargs):
            calls.append((start, stop, kwargs["cached_preflight"]))
            return {"preflight": {"mode": len(calls)}}

        microscope.rec_timed_continuous_projection = Mock(side_effect=record)
        with microscope.timed_projection_session() as session:
            session.record("first_{z}.tif", -300, 300, 2)
            session.invalidate_preflight()
            session.record("second_{z}.tif", -300, 300, 2)
            session.finish_position()
            session.record("third_{z}.tif", -300, 300, 2)
        self.assertEqual(calls, [
            (-300, 300, None),
            (300, -300, None),
            (-300, 300, None),
        ])
        self.assertEqual([call[0][0] for call in microscope.setZPos.call_args_list],
                         [1000, 2000])

    def test_generated_script_keeps_default_old_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = self.generate(Path(directory), "default")
        self.assertIn("mic.rec_projection(", generated)
        self.assertNotIn("mic.rec_timed_continuous_projection(", generated)

    def test_old_config_without_selector_keeps_legacy_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = self.generate(
                Path(directory), "optimized", False, old_projection=True
            )
        self.assertIn("mic.rec_projection(", generated)

    def test_nonprojection_single_image_stays_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = self.generate(
                Path(directory), "off",
                slice_start=0, slice_stop=0,
            )
        self.assertIn("mic.rec_image(", generated)
        self.assertNotIn("mic.rec_timed_continuous_projection(", generated)

    def test_off_mode_with_slices_keeps_ordinary_stack(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = self.generate(Path(directory), "off")
        self.assertIn("mic.rec_stack(", generated)
        self.assertNotIn("mic.rec_projection(", generated)


if __name__ == "__main__":
    unittest.main()
