"""Generate and run recording plans without connecting to real hardware."""
import contextlib
import importlib
import io
import os
from pathlib import Path
import runpy
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pytest

from leica_microscope.includes import helper_functions
from leica_microscope.microscope import Microscope

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "leica_microscope"
microscope_module = importlib.import_module("leica_microscope.microscope")


def generate(tmp_path, stack=None, positions=False, modes=False, grid=False, repetitions=1):
    config = helper_functions.Config(str(PACKAGE / "ConfigCreator/Config_Default.txt"))
    target = tmp_path / "images with spaces"
    config.set("files", "target_folder", str(target))
    config.set("files", "positions_filename", str(tmp_path / "positions.txt") if positions else "None")
    config.set("repetition", "repetition_count", str(repetitions))
    if modes:
        config.set("general", "record_modes", "[Mode_BF(3, 0), Mode_Fluo1(20, 2.5)]")
    if grid:
        config.set("grid", "countx", "2")
    for key, value in (stack or {"projection_mode": "optimized"}).items():
        if value is None:
            config.remove_option("stack", key)
        else:
            config.set("stack", key, str(value))
    with patch.object(helper_functions, "getConfig", return_value=(config, "test")), \
            patch.object(subprocess, "run") as launch, contextlib.redirect_stdout(io.StringIO()):
        runpy.run_path(str(PACKAGE / "generate_record.py"))
    script = target / "test_record.py"
    launch.assert_called_once_with(
        [sys.executable, str(script), "--timestamp=test"], cwd=str(target), check=True,
    )
    code = script.read_text()
    compile(code, str(script), "exec")
    return code


class PlanMicroscope(Microscope):
    def __init__(self):
        self.position = np.array([0, 0, 500])
        self.speed = 123
        self.origin = 500
        self.records = []
        self.position_changes = []
        self.cam = SimpleNamespace(getWidth=lambda: 10, getHeight=lambda: 10,
                                   getPixelSize=lambda: 1)
        self.waitSinceLast = Mock()
        self.used_disk_space = 0

    def getDefaultFilename(self, target):
        return str(Path(target) / "{pos}_{repetition}_{mode}_{x}_{y}_{z}.tif")

    def loadPositions(self, filename):
        return np.array([[10, 20, 500], [30, 40, 600]])

    def getZPos(self):
        return int(self.position[2])

    def setZPos(self, z):
        self.position[2] = z

    def getZSpeed(self):
        return self.speed

    def setZSpeed(self, speed):
        self.speed = speed

    def getZSpeedMax(self):
        return 1000

    def getPos(self):
        assert self.getZPos() == self.origin
        return self.position.copy()

    def setPos(self, pos):
        assert self.getZPos() == self.origin, "XY motion began before Z restoration"
        self.position = np.array(pos)
        self.origin = self.getZPos()
        self.position_changes.append(self.position.copy())

    def setProperties(self, **kwargs):
        pass

    def getEffectiveMagnification(self):
        return 1

    getXResolution = getEffectiveMagnification
    getYResolution = getEffectiveMagnification

    def rec_timed_continuous_projection(self, filename, z_start_um, z_stop_um,
                                       scan_time_s, **kwargs):
        center = kwargs.get("center_z_steps", self.getZPos())
        self.records.append((str(filename), center, z_start_um, z_stop_um))
        if kwargs.get("leave_at_edge"):
            self.position[2] = center + z_stop_um + (1 if z_stop_um > z_start_um else -1)
        return {"preflight": {}}


@pytest.mark.parametrize("positions,modes,grid", [(False, False, False),
                                                (True, True, False),
                                                (True, False, True)])
def test_generated_plans_keep_origins_and_restore_before_xy(tmp_path, positions, modes, grid):
    code = generate(tmp_path, positions=positions, modes=modes, grid=grid, repetitions=2)
    mic = PlanMicroscope()
    with patch.object(microscope_module, "Microscope", return_value=mic), \
            contextlib.redirect_stdout(io.StringIO()):
        exec(compile(code, "generated_record.py", "exec"), {})
    expected = 2 * (2 if positions else 1) * (2 if modes else 1) * (2 if grid else 1)
    assert len(mic.records) == expected
    assert len({record[0] for record in mic.records}) == expected
    assert mic.getZPos() == mic.origin
    assert mic.speed == 123
    assert "sys.path.insert(0, {!r})".format(str(ROOT)) in code


@pytest.mark.parametrize("stack,expected", [
    ({"projection_mode": "off"}, "mic.rec_image("),
    ({"projection_mode": "off", "slice_start": -1}, "mic.rec_stack("),
    ({"projection_mode": None, "projection": "True", "slice_start": -1}, "mic.rec_projection("),
    ({"projection_mode": "timed"}, "mic.rec_timed_continuous_projection_series("),
])
def test_legacy_and_optimized_config_dispatch(tmp_path, stack, expected):
    assert expected in generate(tmp_path, stack, repetitions=2)


def test_generator_propagates_recording_failure(tmp_path):
    config = helper_functions.Config(str(PACKAGE / "ConfigCreator/Config_Default.txt"))
    config.set("files", "target_folder", str(tmp_path))
    with patch.object(helper_functions, "getConfig", return_value=(config, "test")), \
            patch.object(subprocess, "run", side_effect=subprocess.CalledProcessError(1, "record")), \
            contextlib.redirect_stdout(io.StringIO()), pytest.raises(subprocess.CalledProcessError):
        runpy.run_path(str(PACKAGE / "generate_record.py"))


@pytest.fixture
def editor_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    from leica_microscope.ConfigCreator import ConfigCreator as editor_module
    monkeypatch.setattr(editor_module, "tmp_config", str(tmp_path / "gui.tmp"))
    app = editor_module.QtWidgets.QApplication.instance() or editor_module.QtWidgets.QApplication([])
    options = SimpleNamespace(
        icon=None, program=None, config=str(tmp_path / "config.txt"),
        template=str(PACKAGE / "ConfigCreator/Config_Template.txt"),
        reset=str(PACKAGE / "ConfigCreator/Config_Default.txt"),
    )
    yield editor_module, options, app


def test_record_gui_selector_and_legacy_config_migration(editor_environment, tmp_path):
    module, options, app = editor_environment
    options_path = Path(options.config)
    options_path.write_text("[stack]\nprojection = True\nslice_start = -2\nslice_stop = 2\n")
    editor = module.ConfigEditor(options)
    try:
        fields = editor.fields["stack"]
        assert fields["projection_mode"].currentData() == "default"
        assert fields["projection_start_um"].isHidden()
        fields["projection_mode"].setCurrentIndex(2)
        assert not fields["projection_start_um"].isHidden()
        assert fields["slice_start"].isHidden()
        assert editor.config.get("stack", "projection_mode") == "optimized"
        assert not editor.config.has_option("stack", "projection")
        with options_path.open("w") as stream:
            editor.config.write(stream)
        editor.LoadConfig(str(options_path))
        assert fields["projection_mode"].currentData() == "optimized"
        editor.reset("stack", "projection_mode")
        assert fields["projection_mode"].currentData() == "off"
    finally:
        editor.close()


def test_standalone_stack_template_still_loads(editor_environment):
    module, options, app = editor_environment
    options.template = str(PACKAGE / "ConfigCreator/Record_ConfigStack_Template.txt")
    options.reset = str(PACKAGE / "ConfigCreator/Record_ConfigStack_Default.txt")
    editor = module.ConfigEditor(options)
    try:
        assert "projection" in editor.fields["stack"]
        assert editor.config.has_option("stack", "projection")
    finally:
        editor.close()
