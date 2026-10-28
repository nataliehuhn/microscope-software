"""Exercise actual Qt/Matplotlib clicks without moving microscope hardware."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def position_finder(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from leica_microscope import LiveViewer as viewer
    from leica_microscope.microscope import Microscope
    from PyQt5 import QtTest
    app = viewer.QtWidgets.QApplication.instance() or viewer.QtWidgets.QApplication([])
    monkeypatch.setattr(viewer, "positions_file", str(tmp_path / "positions.txt"))

    class Parent(viewer.QtWidgets.QWidget):
        signal = viewer.QtCore.Signal()

    parent = Parent()
    mic = Microscope.__new__(Microscope)
    mic.config = dict(stage_min_x=0, stage_max_x=919500,
                      stage_min_y=0, stage_max_y=600750,
                      stage_flip_x=False, stage_flip_y=False)
    mic.properties = {"resolution": [0.1381836, 0.1381836, 0.0038]}
    mic.send_command_and_wait = Mock()
    mic.wait_for_stop = Mock()
    mic.setXYPos = Mock(wraps=mic.setXYPos)
    mic.getPos = Mock(return_value=np.array([459500, 300375, 0]))
    parent.mic, parent.cam = mic, Mock()
    panel = viewer.ModulePosition(parent, viewer.QtWidgets.QVBoxLayout(parent))
    parent.resize(300, 650)
    parent.show()
    app.processEvents()
    panel.plot.draw()
    with patch.object(viewer.QtWidgets.QMessageBox, "warning") as warning:
        yield SimpleNamespace(panel=panel, mic=mic, viewer=viewer, app=app,
                              qt_test=QtTest.QTest, warning=warning)
    parent.close()
    parent.deleteLater()
    app.processEvents()


def qt_click(finder, x, y, double=True, button=None):
    panel, qt = finder.panel, finder.viewer.QtCore.Qt
    pixels = panel.ax.transData.transform((x, y))
    ratio = getattr(panel.plot, "_dpi_ratio", 1)
    point = finder.viewer.QtCore.QPoint(
        round(pixels[0] / ratio), round(panel.plot.height() - pixels[1] / ratio),
    )
    events = []
    cid = panel.plot.mpl_connect("button_press_event", events.append)
    try:
        click = finder.qt_test.mouseDClick if double else finder.qt_test.mouseClick
        click(panel.plot, qt.LeftButton if button is None else button, pos=point)
        finder.app.processEvents()
    finally:
        panel.plot.mpl_disconnect(cid)
    return events[-1]


def select_plate(finder, name):
    index = finder.panel.combo_box.findText(name)
    assert index >= 0
    finder.panel.combo_box.setCurrentIndex(index)
    finder.app.processEvents()
    finder.panel.plot.draw()


@pytest.mark.parametrize("name", ["1 well plate", "6 well plate", "12 well plate", "24 well plate"])
def test_left_double_click_on_calibrated_well_sends_xy_only(position_finder, name):
    finder = position_finder
    select_plate(finder, name)
    x, y, radius = finder.panel.plate_data["wells"][0]
    event = qt_click(finder, x, y)
    assert event.dblclick
    expected_x, expected_y = int(event.xdata), int(event.ydata)
    finder.mic.setXYPos.assert_called_once_with(expected_x, expected_y)
    finder.mic.send_command_and_wait.assert_called_once_with(
        ["72022 %d" % expected_x, "73022 %d" % expected_y],
    )
    finder.warning.assert_not_called()
    np.testing.assert_array_equal(finder.panel.plot_line.get_xdata(), [459500])
    np.testing.assert_array_equal(finder.panel.plot_line.get_ydata(), [300375])


def test_single_and_right_double_click_do_not_move_stage(position_finder):
    finder = position_finder
    qt_click(finder, 459500, 300375, double=False)
    qt_click(finder, 459500, 300375, button=finder.viewer.QtCore.Qt.RightButton)
    finder.mic.setXYPos.assert_not_called()


@pytest.mark.parametrize("x,y,inaxes", [(None, None, False),
                                       (float("nan"), 20, True),
                                       (20, float("inf"), True)])
def test_invalid_plot_events_do_not_move_stage(position_finder, x, y, inaxes):
    finder = position_finder
    finder.panel.onPositionDoubleClick(SimpleNamespace(
        dblclick=True, button=1, inaxes=finder.panel.ax if inaxes else None,
        xdata=x, ydata=y,
    ))
    finder.mic.setXYPos.assert_not_called()
    finder.warning.assert_not_called()


def test_out_of_range_target_is_reported_before_any_motion(position_finder):
    finder = position_finder
    finder.panel.onPositionDoubleClick(SimpleNamespace(
        dblclick=True, button=1, inaxes=finder.panel.ax,
        xdata=13336451, ydata=8963018,
    ))
    finder.mic.setXYPos.assert_not_called()
    assert "outside" in finder.warning.call_args.args[2]


def test_controller_error_is_visible_in_viewer(position_finder):
    finder = position_finder
    finder.mic.setXYPos.side_effect = OSError("COM4 unavailable")
    qt_click(finder, 459500, 300375)
    assert "COM4 unavailable" in finder.warning.call_args.args[2]


def test_blank_map_and_current_marker_use_mic3_coordinates(position_finder):
    panel = position_finder.panel
    assert panel.plate_data["name"] == "-"
    assert panel.plate_data["extent"] == [0, 919500, 0, 600750]
    assert panel.ax.get_xlim()[0] < 459500 < panel.ax.get_xlim()[1]
    assert panel.ax.get_ylim()[0] < 300375 < panel.ax.get_ylim()[1]
    np.testing.assert_array_equal(panel.plot_line.get_xdata(), [459500])
    np.testing.assert_array_equal(panel.plot_line.get_ydata(), [300375])


def test_restored_maps_match_mic3_travel_and_calibration_measurements():
    folder = ROOT / "leica_microscope"
    for suffix, measurements, columns, rows in [
            ("01", "35mmdish.txt", 1, 1), ("06", "6well.txt", 3, 2),
            ("12", "12well.txt", 4, 3), ("24", "24well.txt", 6, 4)]:
        data = json.loads((folder / ("plate_data%s.json" % suffix)).read_text())
        wells = np.asarray(data["wells"])
        assert len(wells) == columns * rows
        assert np.all((0 <= wells[:, 0]) & (wells[:, 0] <= 919500))
        assert np.all((0 <= wells[:, 1]) & (wells[:, 1] <= 600750))
        edges = np.loadtxt(str(folder / measurements))
        edges[:, 1] = edges[::-1, 1]
        edges = edges.reshape(-1, 4, 3)
        centers_x = (edges[:, 0, 0] + edges[:, 1, 0]) / 2
        centers_y = (edges[:, 2, 1] + edges[:, 3, 1]) / 2
        np.testing.assert_allclose(sorted(set(wells[:, 0])),
                                   np.linspace(centers_x[0], centers_x[-1], columns))
        np.testing.assert_allclose(sorted(set(wells[:, 1])),
                                   sorted(np.linspace(centers_y[0], centers_y[-1], rows)))
