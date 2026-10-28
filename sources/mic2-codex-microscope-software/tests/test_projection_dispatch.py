import unittest
from unittest.mock import Mock

from leica_microscope.microscope import Microscope


class ProjectionDispatchTests(unittest.TestCase):
    def test_default_projection_uses_preaccelerated_recorder(self):
        microscope = Microscope.__new__(Microscope)
        microscope.rec_preaccelerated_projection = Mock(return_value={"ok": True})
        microscope.rec_stack = Mock()

        result = microscope.rec_projection(
            "projection_{z}.tif",
            n_below=0,
            n_above=10,
            slice_thickness_um=2.0,
        )

        self.assertEqual(result, {"ok": True})
        microscope.rec_preaccelerated_projection.assert_called_once_with(
            "projection_{z}.tif",
            n_below=0,
            n_above=10,
            slice_thickness_um=2.0,
            minimum_frames=None,
            camera_margin_frames=4,
        )
        microscope.rec_stack.assert_not_called()

    def test_nonprojection_options_keep_legacy_stack_path(self):
        microscope = Microscope.__new__(Microscope)
        microscope.rec_preaccelerated_projection = Mock()
        microscope.rec_stack = Mock(return_value="legacy")

        result = microscope.rec_projection(
            "stack_{z}.tif",
            n_below=-2,
            n_above=2,
            slice_thickness_um=1.0,
            fast_recording=False,
            save_projection=False,
        )

        self.assertEqual(result, "legacy")
        microscope.rec_stack.assert_called_once_with(
            "stack_{z}.tif", -2, 2, 1.0, False, False
        )
        microscope.rec_preaccelerated_projection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
