"""Keep old fluorescence display and maintenance features without hardware access."""
import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from leica_microscope import LiveViewer as viewer
from leica_microscope import SetLimits


@pytest.fixture(scope="module")
def app():
    return viewer.QtWidgets.QApplication.instance() or viewer.QtWidgets.QApplication([])


@pytest.mark.parametrize("auto_contrast", [False, True])
@pytest.mark.parametrize("dark", [False, True])
def test_display_scaling_retains_raw_pixels_and_handles_dark_frames(app, auto_contrast, dark):
    raw = (np.zeros((4, 4), dtype=np.uint16) if dark else
           np.arange(100, 116, dtype=np.uint16).reshape(4, 4))
    saved = raw.copy()
    window = SimpleNamespace(im=raw, auto_contrast=auto_contrast,
                             cam=SimpleNamespace(getMaxValue=lambda: 65535), pixmap=Mock())
    captured = []
    convert = viewer.array2qimage

    def capture(values):
        captured.append(values.copy())
        return convert(values)

    with patch.object(viewer, "array2qimage", side_effect=capture), np.errstate(all="raise"):
        viewer.Window.showImage(window)
    np.testing.assert_array_equal(raw, saved)
    assert np.all(np.isfinite(captured[0]))
    if dark or not auto_contrast:
        assert captured[0].max() == 0
    else:
        assert captured[0].min() == 0
        assert captured[0].max() == 255


def test_histogram_exposes_legacy_autocontrast_toggle(app):
    parent = viewer.QtWidgets.QWidget()
    parent.layout = viewer.QtWidgets.QVBoxLayout(parent)
    parent.signal_new_image = Mock()
    parent.auto_contrast = False
    parent.showImage = Mock()
    histogram = viewer.ModuleHistogram(parent, parent.layout, 65535)
    histogram.checkbox_autocontrast.setChecked(True)
    assert parent.auto_contrast is True
    histogram.checkbox_autocontrast.setChecked(False)
    assert parent.auto_contrast is False
    assert parent.showImage.call_count == 2
    parent.close()


def test_set_limits_uses_this_rigs_config_and_no_camera():
    mic = Mock()
    mic.config = dict(stage_min_x=10, stage_max_x=1234,
                      stage_min_y=20, stage_max_y=5678)
    with patch.object(SetLimits, "Microscope", return_value=mic) as connect:
        SetLimits.main()
    connect.assert_called_once_with(no_camera=True, no_init=True)
    assert [call.args[0] for call in mic.send_command_and_wait.call_args_list] == [
        "72026 10", "72027 1234", "73026 20", "73027 5678",
    ]
