"""Protocol checks without stage movements or fluorescence illumination."""
import importlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

protocol = importlib.import_module("MigAssay_FluoGroups")


class FakeMicroscope:
    def __init__(self):
        self.mode = "BF"
        self.position = None
        self.images = []
        self.shutter = False
        self.fail_fluorescence = False
        self.ignore_gain = False
        self.gain = 0.0
        self.exposure = 3.0
        self.cam = SimpleNamespace(
            camera=SimpleNamespace(ExposureAuto=SimpleNamespace(Value="Off"),
                                   GainAuto=SimpleNamespace(Value="Off")),
            gain=lambda: self.gain,
            exposure=lambda: self.exposure,
        )

    def isFluo(self):
        return self.mode.startswith("FLUO")

    def setMode(self, mode):
        self.mode = mode

    def setPos(self, position):
        if self.isFluo():
            assert not self.shutter
        self.position = tuple(position)

    def setProperties(self, exposure, gain, intensity=None):
        self.exposure = exposure
        if not self.ignore_gain:
            self.gain = gain

    def setShutter(self, state):
        self.shutter = state

    def rec_image(self, filename):
        if self.isFluo():
            self.shutter = True
            if self.fail_fluorescence:
                raise RuntimeError("Camera failed")
        self.images.append((self.mode, self.position, self.exposure, self.gain, filename))
        self.shutter = False


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="protocol-test-", dir=str(Path(__file__).resolve().parent))
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        self.positions = np.array([[10, 11, 12], [20, 21, 22], [30, 31, 32], [40, 41, 42]])
        self.groups = [dict(name="A", positions=[1, 2], exposure_ms=20.0, gain_db=0.0),
                       dict(name="B", positions=[3, 4], exposure_ms=100.0, gain_db=6.0)]
        self.assignments = protocol.condition_map(self.groups, 4)
        self.brightfield = dict(exposure_ms=3.0, gain_db=0.0)

    def run_protocol(self, mic):
        with patch.object(protocol.time, "sleep"):
            protocol.run_protocol(mic, self.positions, self.assignments, self.output,
                                  2, 0.0, "FLUO2", "BF", self.brightfield, 0.0)

    def test_brightfield_only_at_start_and_end_with_grouped_fluorescence(self):
        mic = FakeMicroscope()
        self.run_protocol(mic)
        self.assertEqual([image[0] for image in mic.images], ["BF"] * 4 + ["FLUO2"] * 8 + ["BF"] * 4)
        original_order = [tuple(p) for p in self.positions]
        self.assertEqual([image[1] for image in mic.images], original_order * 4)
        self.assertEqual([(image[2], image[3]) for image in mic.images[4:8]],
                         [(20.0, 0.0)] * 2 + [(100.0, 6.0)] * 2)
        paths = [Path(image[4]) for image in mic.images]
        self.assertEqual(len(set(paths)), 16)
        self.assertTrue(all(p.parent.name == "brightfield_start" for p in paths[:4]))
        self.assertTrue(all(p.parent.name == "brightfield_end" for p in paths[-4:]))
        self.assertEqual(mic.mode, "BF")

    def test_condition_definition_order_does_not_reorder_positions(self):
        assignments = protocol.condition_map(self.groups[::-1], 4)
        self.assertEqual([assignments[i]["name"] for i in range(1, 5)], ["A", "A", "B", "B"])

    def test_invalid_groups_fail_before_acquisition(self):
        for groups in ([self.groups[0]],
                       [self.groups[0], dict(self.groups[1], positions=[2, 3, 4])],
                       [self.groups[0], dict(self.groups[1], positions=[3, 4, 5])]):
            with self.subTest(groups=groups), self.assertRaises(ValueError):
                protocol.condition_map(groups, 4)

    def test_wrong_gain_stops_before_saving_fluorescence(self):
        mic = FakeMicroscope()
        mic.ignore_gain = True
        with self.assertRaisesRegex(RuntimeError, "Gain was not applied"):
            self.run_protocol(mic)
        self.assertEqual(len(mic.images), 6)  # Four BF, then the two zero-gain positions.
        self.assertFalse(mic.shutter)

    def test_acquisition_failure_closes_shutter_and_stops(self):
        mic = FakeMicroscope()
        mic.fail_fluorescence = True
        with self.assertRaisesRegex(RuntimeError, "Camera failed"):
            self.run_protocol(mic)
        self.assertEqual(len(mic.images), 4)
        self.assertFalse(mic.shutter)

    def test_position_reader_preserves_rows_and_rejects_fractional_coordinates(self):
        path = self.output / "positions.txt"
        np.savetxt(path, self.positions, fmt="%d")
        np.testing.assert_array_equal(protocol.load_positions(path), self.positions)
        path.write_text("1.5 2 3\n")
        with self.assertRaises(ValueError):
            protocol.load_positions(path)

    def test_dry_run_does_not_connect_to_the_microscope(self):
        path = self.output / "positions.txt"
        np.savetxt(path, self.positions, fmt="%d")
        with patch.object(protocol, "CONDITIONS", self.groups), \
                patch.object(protocol.sys, "argv", ["protocol", "--dry-run", "--positions", str(path)]), \
                patch.object(protocol, "load_microscope_class") as connect:
            protocol.main()
        connect.assert_not_called()

    def test_required_software_copy_is_selected(self):
        cls = protocol.load_microscope_class()
        module = importlib.import_module(cls.__module__)
        self.assertEqual(Path(module.__file__).resolve().parent, protocol.SOFTWARE_FOLDER.resolve())


if __name__ == "__main__":
    unittest.main()
