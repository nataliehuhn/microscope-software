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


def generate(tmp_path, stack=None, positions=False, modes=False, grid=False,
             repetitions=1, duration_hours=0, sequence=None, cycles=None,
             separate=False, positions_data=None):
    config = helper_functions.Config(str(PACKAGE / "ConfigCreator/Config_Default.txt"))
    target = tmp_path / "images with spaces"
    if positions:
        np.savetxt(str(tmp_path / "positions.txt"),
                   [[10, 20, 500], [30, 40, 600]] if positions_data is None else positions_data,
                   fmt="%d")
    config.set("files", "target_folder", str(target))
    config.set("files", "positions_filename", str(tmp_path / "positions.txt") if positions else "None")
    config.set("repetition", "repetition_count", str(repetitions))
    config.set("repetition", "minimum_duration_hours", str(duration_hours))
    config.set("repetition", "repeat_positions_separately", str(separate))
    config.set("repetition", "repetition_time_delta", "15" if separate else "0")
    for section, values in (("position_sequence", sequence), ("cycles", cycles)):
        for key, value in (values or {}).items():
            config.set(section, key, str(value))
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


@pytest.mark.parametrize("mode", ["off", "optimized"])
def test_one_position_duration_ignores_repetition_count(tmp_path, mode):
    code = generate(tmp_path, stack={"projection_mode": mode},
                    repetitions=1, duration_hours=24)
    assert "duration_s=86400.0" in code if mode == "optimized" else \
        "duration_repetitions(mic.waitSinceLast, 86400.0" in code
    assert "bar(range(1)" not in code


def test_saved_single_position_duration_runs_until_elapsed_time(tmp_path):
    code = generate(tmp_path, stack={"projection_mode": "off"},
                    positions=True, positions_data=[[10, 20, 500]],
                    repetitions=1, duration_hours=0.001)
    mic = PlanMicroscope()
    elapsed = [0.0]
    starts = []

    def record_image(filename):
        starts.append(elapsed[0])
        elapsed[0] += 2.0

    mic.rec_image = record_image
    from leica_microscope import recording_schedule
    schedule = recording_schedule.duration_repetitions

    def fake_schedule(wait, duration_s, interval_s):
        return schedule(wait, duration_s, interval_s, clock=lambda: elapsed[0])

    with patch.object(microscope_module, "Microscope", return_value=mic), \
            patch.object(recording_schedule, "duration_repetitions", fake_schedule), \
            contextlib.redirect_stdout(io.StringIO()):
        exec(compile(code, "generated_record.py", "exec"), {})
    assert starts == [0.0, 2.0]
    assert elapsed[0] >= 3.6
    assert len(mic.position_changes) == 1


def test_duration_rejects_multiple_cycles(tmp_path):
    with pytest.raises(ValueError, match="one full cycle"):
        generate(tmp_path, duration_hours=24, cycles={"cycle_count": 2})


def test_duration_rejects_multiple_saved_positions_before_hardware(tmp_path):
    with pytest.raises(ValueError, match="Set Positions filename to None"):
        generate(tmp_path, positions=True, duration_hours=24)
    assert not (tmp_path / "images with spaces" / "test_record.py").exists()


def test_duration_rejects_multiple_modes_before_acquisition(tmp_path):
    with pytest.raises(ValueError, match="one mode"):
        generate(tmp_path, modes=True, duration_hours=24)


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
        assert editor.fields["repetition"]["minimum_duration_hours"].value() == 0
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


def test_duration_gui_explains_multiple_saved_positions_before_launch(editor_environment, tmp_path):
    module, options, app = editor_environment
    options.program = "generate_record.py"
    positions = tmp_path / "positions.txt"
    np.savetxt(str(positions), [[10, 20, 500], [30, 40, 600]], fmt="%d")
    editor = module.ConfigEditor(options)
    try:
        editor.fields["files"]["positions_filename"].setText(str(positions))
        editor.fields["repetition"]["minimum_duration_hours"].setValue(2)
        with patch.object(module.QtWidgets.QMessageBox, "warning") as warning, \
                patch.object(module.subprocess, "run") as launch:
            editor.ButtonSave()
        launch.assert_not_called()
        assert "2 saved positions" in warning.call_args.args[2]
        assert "current stage position" in warning.call_args.args[2]
    finally:
        editor.close()


def test_recording_plan_buttons_switch_schedule_and_position_source(editor_environment, tmp_path):
    module, options, app = editor_environment
    positions = tmp_path / "one-position.txt"
    np.savetxt(str(positions), [[10, 20, 500]], fmt="%d")
    editor = module.ConfigEditor(options)
    try:
        editor.fields["stack"]["projection_stop_um"].setValue(120)
        with patch.object(module.QtWidgets.QFileDialog, "getOpenFileName",
                          return_value=(str(positions), "")):
            editor.button_repeated_saved.click()
        assert editor.fields["files"]["positions_filename"].text() == str(positions)
        assert editor.fields["repetition"]["minimum_duration_hours"].value() == 0
        assert "saved positions" in editor.plan_status.text()

        editor.button_timed_saved.click()
        assert editor.fields["repetition"]["minimum_duration_hours"].value() == 24
        assert "one saved position" in editor.plan_status.text()

        editor.button_single_position_preset.click()
        assert editor.fields["files"]["positions_filename"].text() == "None"
        assert "current position" in editor.plan_status.text()

        editor.button_repeated_current.click()
        assert editor.fields["repetition"]["minimum_duration_hours"].value() == 0
        assert "Fixed repetition count" in editor.plan_status.text()
        assert editor.fields["stack"]["projection_stop_um"].value() == 120
    finally:
        editor.close()


def test_assay_preset_is_editable_and_preserves_sample_settings(editor_environment, tmp_path):
    module, options, app = editor_environment
    positions = tmp_path / "positions.txt"
    np.savetxt(str(positions), np.arange(30).reshape(10, 3), fmt="%d")
    editor = module.ConfigEditor(options)
    try:
        editor.fields["files"]["positions_filename"].setText(str(positions))
        editor.fields["stack"]["projection_start_um"].setValue(0)
        editor.fields["stack"]["projection_stop_um"].setValue(70)
        editor.fields["stack"]["projection_time_s"].setValue(2.0)
        editor.button_assay_preset.click()
        settings, rows = editor.sequencePreviewData()
        assert settings.positions_per_condition == 5
        assert settings.cycle_interval_hours == 3
        assert settings.cycle_count == 5
        assert [row["saved_position"] for row in rows] == [1, 6, 2, 7, 3, 8, 4, 9, 5, 10]
        assert editor.fields["stack"]["projection_stop_um"].value() == 70
        assert editor.fields["stack"]["projection_time_s"].value() == 2
        assert editor.fields["stack"]["projection_mode"].currentData() == "optimized"
        assert editor.fields["repetition"]["repetition_count"].value() == 22
        assert editor.fields["repetition"]["repeat_positions_separately"].isChecked()
        editor.fields["position_sequence"]["positions_per_condition"].setValue(2)
        editor.fields["cycles"]["cycle_interval_hours"].setValue(1.5)
        with Path(options.config).open("w") as handle:
            editor.config.write(handle)
        editor.LoadConfig(options.config)
        settings, rows = editor.sequencePreviewData()
        assert settings.positions_per_condition == 2
        assert settings.cycle_interval_hours == 1.5
    finally:
        editor.close()


def test_single_position_preset_sets_duration_and_keeps_scan_settings(editor_environment, tmp_path):
    module, options, app = editor_environment
    editor = module.ConfigEditor(options)
    try:
        editor.fields["files"]["positions_filename"].setText(str(tmp_path / "many.txt"))
        editor.fields["stack"]["projection_start_um"].setValue(-20)
        editor.fields["stack"]["projection_stop_um"].setValue(80)
        editor.button_single_position_preset.click()
        assert editor.fields["repetition"]["minimum_duration_hours"].value() == 24
        assert editor.fields["repetition"]["repetition_time_delta"].value() == 15
        assert editor.fields["files"]["positions_filename"].text() == "None"
        assert editor.fields["cycles"]["cycle_count"].value() == 1
        assert editor.fields["stack"]["projection_start_um"].value() == -20
        assert editor.fields["stack"]["projection_stop_um"].value() == 80
        editor.button_assay_preset.click()
        assert editor.fields["repetition"]["minimum_duration_hours"].value() == 0
    finally:
        editor.close()


def test_full_assay_runs_all_repeats_then_jumps_and_restarts_route_after_three_hours(tmp_path):
    from leica_microscope import recording_sequence
    positions = np.array([[10 * i, 20 * i, 10000 + i] for i in range(10)])
    code = generate(
        tmp_path, positions=True, positions_data=positions, repetitions=22, separate=True,
        sequence=dict(position_order="interleaved", positions_per_condition=5,
                      settle_pattern_s="5,5,0.5,0.5"),
        cycles=dict(cycle_count=2, cycle_interval_hours=3),
    )
    clock = SimpleNamespace(now=0.0)
    starts = []

    class TimedPlan(PlanMicroscope):
        def rec_timed_continuous_projection(self, *args, **kwargs):
            starts.append(clock.now)
            result = super().rec_timed_continuous_projection(*args, **kwargs)
            clock.now += 1.0
            return result

    mic = TimedPlan()
    with patch.object(microscope_module, "Microscope", return_value=mic), \
            patch.object(recording_sequence.time, "monotonic", lambda: clock.now), \
            patch.object(recording_sequence.time, "sleep", lambda delay: setattr(clock, "now", clock.now + delay)), \
            contextlib.redirect_stdout(io.StringIO()):
        exec(compile(code, "assay_record.py", "exec"), {})
    assert len(mic.records) == 440
    order = [0, 5, 1, 6, 2, 7, 3, 8, 4, 9]
    for cycle in range(2):
        records = mic.records[cycle * 220:(cycle + 1) * 220]
        assert [record[1] for record in records[::22]] == [10000 + index for index in order]
        assert [int(Path(record[0]).name.split("_")[0]) for record in records[::22]] == order
        assert [int(Path(record[0]).name.split("_")[1]) for record in records[:22]] == list(range(22))
        np.testing.assert_allclose(np.diff(starts[cycle * 220:cycle * 220 + 22]), 15)
    assert starts[0] == 5
    assert starts[220] == 10800 + 5
    assert len({record[0] for record in mic.records}) == 440
    assert mic.getZPos() == mic.origin
    manifest = __import__("json").loads((tmp_path / "images with spaces/test_position_sequence.json").read_text())
    assert [row["saved_position"] for row in manifest["visits"]] == [index + 1 for index in order]


def test_invalid_condition_grouping_fails_before_connecting_to_microscope(tmp_path):
    code = generate(tmp_path, positions=True,
                    sequence=dict(position_order="interleaved", positions_per_condition=5))
    with patch.object(microscope_module, "Microscope") as connect, \
            pytest.raises(ValueError, match="cannot be split"):
        exec(compile(code, "invalid_assay.py", "exec"), {})
    connect.assert_not_called()
