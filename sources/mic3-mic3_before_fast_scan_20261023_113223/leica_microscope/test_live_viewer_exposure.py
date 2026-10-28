"""Exercise viewer mode/filter buttons without connecting to microscope hardware."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class LiveExposureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(
            prefix="exposure-test-", dir=str(Path(__file__).resolve().parent)
        )
        cls.environment = patch.dict(os.environ, {
            "APPDATA": cls.temp.name, "QT_QPA_PLATFORM": "offscreen",
        })
        cls.environment.start()
        from leica_microscope import LiveViewer
        cls.viewer = LiveViewer
        cls.app = LiveViewer.QtWidgets.QApplication.instance() or LiveViewer.QtWidgets.QApplication([])
        cls.app_patch = patch.object(LiveViewer, "app", cls.app, create=True)
        cls.app_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.app_patch.stop()
        cls.environment.stop()
        cls.temp.cleanup()

    def setUp(self):
        viewer = self.viewer
        widgets = viewer.QtWidgets

        class TestWindow(viewer.Window):
            def __init__(self):
                widgets.QWidget.__init__(self)
                self._exposure_by_mode = {}

        self.window = window = TestWindow()
        self.addCleanup(window.close)
        window.mic = viewer.Microscope.__new__(viewer.Microscope)
        window.mic.properties = {
            "current_mode": 0, "current_filter": 1,
            "modes": ["TL_BF", "TL_POL", "FLUO", "FLUO_PH", "FLUO_DIC"],
            "filters": ["Filter {}".format(i) for i in range(1, 7)],
        }
        self.actual_mode = 0
        self.actual_filter = 1

        def set_mode(mode, channel=None):
            self.actual_mode = window.mic.mode_ids[mode] if isinstance(mode, str) else mode
            if channel is not None:
                self.actual_filter = channel

        def refresh():
            window.mic.properties.update(
                current_mode=self.actual_mode, current_filter=self.actual_filter,
            )

        window.mic.setMode = Mock(side_effect=set_mode)
        window.mic.getAllProperties = Mock(side_effect=refresh)
        window.cam = Mock()
        window.cam.exposure.return_value = 3.0
        window.cam.get_exposure_range.return_value = [0, 10000]
        window.cam.gain.return_value = 6.5
        window.cam.get_gain_range.return_value = [0, 36]
        window.cam.setExposure.side_effect = lambda value: setattr(window.cam.exposure, "return_value", value)
        layout = widgets.QVBoxLayout(window)
        self.methods = viewer.ModuleMethods(window, layout)
        self.filters = viewer.ModuleFilters(window, layout)
        self.exposure = viewer.ModuleExposure(window, layout)

    def select_mode(self, name):
        self.methods.buttons_by_mode[name].click()

    def set_exposure(self, value):
        self.exposure.input_exposure.spin_box.setValue(value)
        self.assertEqual(self.window.cam.exposure(), value)

    def assert_exposure(self, value):
        self.assertEqual(self.window.cam.exposure(), value)
        self.assertEqual(self.exposure.input_exposure.value(), value)

    def test_brightfield_and_fluorescence_restore_exposure_and_display(self):
        self.select_mode("FLUO")
        self.assert_exposure(3.0)  # First visit does not invent an exposure.
        self.window.cam.setExposure.assert_not_called()
        self.set_exposure(100.25)
        self.select_mode("TL_BF")
        self.assert_exposure(3.0)
        self.select_mode("FLUO")
        self.assert_exposure(100.25)
        self.window.cam.setGain.assert_not_called()

    def test_edit_to_previously_entered_value_still_reaches_camera(self):
        self.select_mode("FLUO")
        self.set_exposure(100)
        self.select_mode("TL_BF")
        self.assert_exposure(3)
        self.set_exposure(100)  # Same number as the last manual edit in FLUO.
        self.select_mode("FLUO")
        self.set_exposure(20)
        self.select_mode("TL_BF")
        self.assert_exposure(100)

    def test_filters_remember_separate_exposures_without_splitting_brightfield(self):
        self.select_mode("FLUO")
        self.set_exposure(20)
        self.filters.buttons[1].click()
        self.set_exposure(200)
        self.filters.buttons[0].click()
        self.assert_exposure(20)
        self.select_mode("TL_BF")
        self.assert_exposure(3)
        self.filters.buttons[1].click()
        self.assert_exposure(3)
        self.select_mode("FLUO")
        self.assert_exposure(200)
        self.select_mode("TL_BF")
        self.assert_exposure(3)

    def test_polarization_and_combined_fluorescence_modes_are_independent(self):
        for mode, exposure in (("TL_POL", 5), ("FLUO_PH", 50), ("FLUO_DIC", 150)):
            self.select_mode(mode)
            self.set_exposure(exposure)
        for mode, exposure in (("TL_BF", 3), ("TL_POL", 5), ("FLUO_PH", 50), ("FLUO_DIC", 150)):
            self.select_mode(mode)
            self.assert_exposure(exposure)

    def test_selecting_current_mode_does_not_reset_exposure(self):
        self.set_exposure(7)
        self.window.cam.setExposure.reset_mock()
        self.select_mode("TL_BF")
        self.assert_exposure(7)
        self.window.cam.setExposure.assert_not_called()

    def test_failed_mode_switch_does_not_apply_destination_exposure(self):
        self.select_mode("FLUO")
        self.set_exposure(100)
        self.window.cam.setExposure.reset_mock()
        with patch.object(self.window.mic, "setMode", side_effect=RuntimeError("switch failed")):
            with self.assertRaisesRegex(RuntimeError, "switch failed"):
                self.window.setMode("TL_BF")
        self.assert_exposure(100)
        self.window.cam.setExposure.assert_not_called()
        self.select_mode("TL_BF")
        self.assert_exposure(3)


if __name__ == "__main__":
    unittest.main()
