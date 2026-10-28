"""Gain regressions for the camera, shared commands, viewer, and recordings."""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from leica_microscope.camera_basler import Camera
from leica_microscope.includes.helper_functions import modesToDictList
from leica_microscope.microscope import Microscope
from leica_microscope.streamer import MemmapReader, MemmapWriter


class FakePylonCamera:
    def __init__(self):
        self.GainAuto = SimpleNamespace(Value="Continuous")
        self.writes = []
        camera = self

        class GainNode:
            Min = 0.0
            Max = 36.0
            value = 0.0

            @property
            def Value(self):
                return self.value

            @Value.setter
            def Value(self, value):
                camera.writes.append((camera.GainAuto.Value, value))
                self.value = value

        self.node = self.Gain = GainNode()


class GainBackendTests(unittest.TestCase):
    def setUp(self):
        self.camera = Camera.__new__(Camera)
        self.camera.camera = FakePylonCamera()

    def test_fractional_gain_reaches_camera_with_auto_gain_off(self):
        self.camera.setGain(12.25)
        self.assertEqual(self.camera.camera.writes, [("Off", 12.25)])
        self.assertEqual(self.camera.gain(), 12.25)

    def test_range_comes_from_camera(self):
        self.camera.camera.node.Max = 24.0
        self.assertEqual(self.camera.get_gain_range(), [0.0, 24.0])

    def test_invalid_gain_is_rejected_before_changing_camera(self):
        for gain in (-1, 37, float("nan"), float("inf")):
            with self.subTest(gain=gain), self.assertRaises(ValueError):
                self.camera.setGain(gain)
        self.assertEqual(self.camera.camera.writes, [])
        self.assertEqual(self.camera.camera.GainAuto.Value, "Continuous")

    def test_recording_applies_each_channel_gain_and_publishes_readback(self):
        mic = Microscope.__new__(Microscope)
        mic.cam = self.camera
        mic.cam.setExposure = Mock()
        mic.setMode = Mock()
        published = []
        mic.memmap_writer = Mock()
        mic.memmap_writer.store_parameters.side_effect = lambda: published.append(mic.cam.gain())
        modes = modesToDictList("[Mode_Fluo1(20, 6.5), Mode_Fluo2(100, 12.25)]")
        for mode in modes:
            mic.setProperties(**mode)
        self.assertEqual(published, [6.5, 12.25])
        self.assertEqual(self.camera.gain(), 12.25)

    def test_current_mode_preserves_gain_unless_explicitly_set(self):
        self.assertEqual(modesToDictList("[Mode_Current()]"), [{}])
        self.assertEqual(modesToDictList("[Mode_Current(20)]"), [{"exposure": 20}])
        self.assertEqual(modesToDictList("[Mode_Current(20, 0)]"),
                         [{"exposure": 20, "gain": 0}])


class NumpyCommand:
    """Match MemMap's numpy scalar flags, including their identity semantics."""
    counter = 0
    name = b"gain"
    value = b"6.5"
    written = True

    def __init__(self, on_done=None):
        self.flag = np.array([False], dtype=bool)
        self.on_done = on_done

    @property
    def done(self):
        return self.flag[0]

    @done.setter
    def done(self, value):
        self.flag[0] = value
        if value and self.on_done is not None:
            self.on_done()


class SharedGainTests(unittest.TestCase):
    def make_reader(self):
        reader = MemmapReader.__new__(MemmapReader)
        reader.mmap = SimpleNamespace(
            gain=np.array([0, 0, 36], dtype=np.float32),
            commands=[NumpyCommand()], pid=os.getpid(),
        )
        return reader

    def test_set_gain_waits_for_numpy_flag_and_reads_applied_value(self):
        reader = self.make_reader()
        def worker_applies_gain(_):
            command = reader.mmap.commands[0]
            self.assertTrue(command.written)
            self.assertEqual(command.counter, 1)
            reader.mmap.gain[0] = float(command.value)
            command.done = True
        with patch("leica_microscope.streamer.time.sleep", side_effect=worker_applies_gain) as sleep:
            reader.setGain(6.5)
        sleep.assert_called_once()
        self.assertEqual(reader.gain(), 6.5)

    def test_unsupported_gain_remains_none(self):
        reader = self.make_reader()
        reader.mmap.gain[0] = np.nan
        self.assertIsNone(reader.gain())

    def test_out_of_range_gain_is_not_queued(self):
        reader = self.make_reader()
        with self.assertRaises(ValueError):
            reader.setGain(37)
        self.assertEqual(reader.mmap.commands[0].counter, 0)

    def test_unresponsive_worker_times_out(self):
        reader = self.make_reader()
        reader.parameter_timeout = 0
        with self.assertRaises(TimeoutError):
            reader.setGain(6.5)

    def test_dead_worker_reports_error(self):
        reader = self.make_reader()
        with patch("leica_microscope.streamer.psutil.pid_exists", return_value=False):
            with self.assertRaises(RuntimeError):
                reader.setGain(6.5)

    def test_worker_publishes_readback_before_acknowledging(self):
        published = []
        command = NumpyCommand(on_done=lambda: self.assertEqual(published, [6.5]))
        writer = MemmapWriter.__new__(MemmapWriter)
        writer.mmap = SimpleNamespace(commands=[command])
        writer.cam = Mock()
        writer.cam.getImage.side_effect = [np.zeros((2, 2)), StopIteration]
        writer.store_image = Mock()
        writer.store_parameters = lambda: published.append(6.5)
        with self.assertRaises(StopIteration):
            writer.stream()
        writer.cam.setGain.assert_called_once_with(6.5)
        self.assertTrue(command.done)


class GainWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(
            prefix="gain-test-", dir=str(Path(__file__).resolve().parent)
        )
        cls.environment = patch.dict(os.environ, {
            "APPDATA": cls.temp.name, "QT_QPA_PLATFORM": "offscreen",
        })
        cls.environment.start()
        from leica_microscope import LiveViewer
        from leica_microscope.ConfigCreator import ConfigCreator
        cls.viewer = LiveViewer
        cls.creator = ConfigCreator
        cls.app = LiveViewer.QtWidgets.QApplication.instance() or LiveViewer.QtWidgets.QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        cls.temp.cleanup()

    def make_widget(self, gain=0.0):
        qt = self.viewer.QtCore
        widgets = self.viewer.QtWidgets
        class Parent(widgets.QWidget):
            signal = qt.Signal()
            signal_new_image = qt.Signal()
            signal_properties_changed = qt.Signal()
        parent = Parent()
        parent.mic = None
        parent.cam = Mock()
        parent.cam.get_exposure_range.return_value = [0, 10000]
        parent.cam.exposure.return_value = 3.0
        parent.cam.get_gain_range.return_value = [0, 36]
        parent.cam.gain.return_value = gain
        def set_gain(value):
            parent.cam.gain.return_value = value
        parent.cam.setGain.side_effect = set_gain
        widget = self.viewer.ModuleExposure(parent, widgets.QVBoxLayout(parent))
        self.addCleanup(parent.close)
        return parent, widget

    def test_zero_gain_has_editable_control_with_actual_limits(self):
        parent, widget = self.make_widget()
        self.assertIsNotNone(widget.input_gain)
        self.assertEqual(widget.input_gain.spin_box.maximum(), 36)
        widget.input_gain.spin_box.setValue(6.5)
        parent.cam.setGain.assert_called_once_with(6.5)
        self.assertEqual(widget.input_gain.value(), 6.5)

    def test_new_image_refreshes_gain_without_sending_a_command(self):
        parent, widget = self.make_widget()
        parent.cam.gain.return_value = 12.25
        parent.signal_new_image.emit()
        self.assertEqual(widget.input_gain.value(), 12.25)
        parent.cam.setGain.assert_not_called()

    def test_unsupported_gain_hides_control(self):
        for gain in (None, float("nan")):
            with self.subTest(gain=gain):
                _, widget = self.make_widget(gain)
                self.assertIsNone(widget.input_gain)

    def test_refresh_does_not_interrupt_slider_drag(self):
        parent, widget = self.make_widget()
        widget.input_gain.slider_dragged = True
        widget.input_gain.setValue(7.0)
        parent.signal_new_image.emit()
        self.assertEqual(widget.input_gain.value(), 7.0)

    def test_record_dialog_preserves_fractional_gain_and_explicit_zero(self):
        parent = self.viewer.QtWidgets.QWidget()
        parent.add_mode = Mock()
        self.addCleanup(parent.close)
        for gain in (6.25, 0):
            with self.subTest(gain=gain):
                dialog = self.creator.ModeDialog(parent)
                dialog.mode.setCurrentText("Current")
                dialog.exposure_time.setValue(20)
                dialog.gain_value.setValue(gain)
                dialog.ok()
                mode = modesToDictList("[Mode_{}]".format(parent.add_mode.call_args[0][0]))[0]
                self.assertEqual(mode, {"exposure": 20, "gain": gain})


if __name__ == "__main__":
    unittest.main()
