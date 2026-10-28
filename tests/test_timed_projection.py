"""Fast-scan integration tests using simulated hardware only."""
import importlib
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pytest
import tifffile

from leica_microscope.microscope import Microscope
from leica_microscope.projection_motion import (
    exposure_coverage, prepare_projection_extrema_indices,
    update_projection_extrema,
)

microscope_module = importlib.import_module("leica_microscope.microscope")


class SimulatedCamera:
    def __init__(self):
        self.exposure_ms = 3.0
        self.fail = False
        self.stopped = False

    def exposure(self):
        return self.exposure_ms

    def setExposure(self, exposure):
        self.exposure_ms = exposure

    def getMaximumFramerateAtShortExposure(self):
        return 50.0

    getFramerate = getMaximumFramerateAtShortExposure

    def latchTimestampClock(self):
        self.epoch = time.perf_counter()
        return dict(host_time_s=self.epoch, camera_ticks=0,
                    tick_frequency_hz=1e9, offset_uncertainty_s=0)

    def streamFramesWithTimestamps(self, callback, stop, started, first):
        started.set()
        try:
            for i in range(500):
                if stop.is_set():
                    return i
                exposure_start = self.epoch + i / 50.0
                delay = exposure_start + self.exposure_ms / 1000 - time.perf_counter()
                if delay > 0 and stop.wait(delay):
                    return i
                first.set()
                if self.fail and i == 3:
                    raise RuntimeError("simulated dropped camera frame")
                callback(np.full((3, 4), i % 255, np.uint8),
                         int(i * 1e9 / 50), self.exposure_ms * 1000,
                         i + 1, time.perf_counter())
        finally:
            self.stopped = True


class SimulatedMicroscope(Microscope):
    def __init__(self):
        self.config = {"camera": "basler", "microscope_name": "Mic3"}
        self.port = "SIMULATED"
        self.cam = SimulatedCamera()
        self.position = 500
        self.speed = 123
        self.motion = None
        self.moves = []
        self.preaccelerated_projection_model = {
            "microscope_name": "Mic3", "z_resolution_um_per_step": 1.0,
            "samples": [dict(speed=100, velocity_steps_s=100,
                             acceleration_steps=1)],
        }

    def getZPos(self):
        if self.motion:
            start, target, started = self.motion
            direction = 1 if target > start else -1
            distance = min(abs(target - start),
                           (time.perf_counter() - started) * self.speed)
            self.position = start + direction * distance
        return int(round(self.position))

    def setZPos(self, position):
        self.motion = None
        self.position = position
        self.moves.append(position)

    def getZSpeed(self):
        return self.speed

    def setZSpeed(self, speed):
        self.speed = speed

    def getZSpeedMax(self):
        return 1000

    def getZSpeedMin(self):
        return 1

    def getZResolution(self):
        return 1.0

    def getZRange(self):
        return 0, 10000

    def getMoving(self):
        return [False, False, False]

    def command_session(self, port):
        mic = self
        assert port == "SIMULATED"

        class Session:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def send(self, command):
                assert command.startswith("71022 ")
                mic.motion = (mic.position, int(command.split()[1]), time.perf_counter())

            def query(self, command, result_type):
                assert command == "71023"
                time.sleep(0.002)
                return result_type(mic.getZPos())

        return Session()


@pytest.mark.parametrize("start,stop", [(-10, 10), (10, -10)])
def test_timed_acquisition_tracks_both_directions_and_restores_state(start, stop):
    mic = SimulatedMicroscope()
    with patch.object(microscope_module, "PersistentCommandSession", mic.command_session):
        minimum, maximum, min_index, max_index, diagnostics = (
            mic.recordTimedContinuousProjection(start, stop, 0.5, return_indices=True)
        )
    assert mic.getZPos() == 500
    assert mic.speed == 123
    assert mic.cam.exposure() == 3.0
    assert mic.cam.stopped
    assert diagnostics["actual_endpoints_steps"] == [500 + start, 500 + stop]
    assert diagnostics["actual_scan_time_s"] == pytest.approx(0.5, abs=0.04)
    assert diagnostics["coverage_fraction"] > 0.95
    assert diagnostics["selected_frame_count"] >= 20
    assert np.all(minimum <= maximum)
    assert np.all(min_index == 0)
    assert np.all(max_index == diagnostics["selected_frame_count"] - 1)


def test_camera_failure_restores_z_speed_exposure_even_in_edge_mode():
    mic = SimulatedMicroscope()
    mic.cam.fail = True
    with patch.object(microscope_module, "PersistentCommandSession", mic.command_session):
        with pytest.raises(RuntimeError, match="projection failed"):
            mic.recordTimedContinuousProjection(-10, 10, 0.5, leave_at_edge=True)
    assert (mic.getZPos(), mic.speed, mic.cam.exposure()) == (500, 123, 3.0)
    assert mic.cam.stopped


def test_wrong_microscope_model_and_out_of_range_scan_never_move_stage():
    mic = SimulatedMicroscope()
    mic.preaccelerated_projection_model["microscope_name"] = "Mic2"
    with pytest.raises(RuntimeError, match="another microscope"):
        mic.recordTimedContinuousProjection(-10, 10, 0.5)
    mic.preaccelerated_projection_model["microscope_name"] = "Mic3"
    with pytest.raises(ValueError, match="Insufficient Z range"):
        mic.recordTimedContinuousProjection(-500, 10, 0.5)
    assert mic.moves == []


def test_projection_indices_match_numpy_including_ties_and_flipped_images():
    prepare_projection_extrema_indices()
    frames = np.random.RandomState(4).randint(0, 8, (20, 7, 11)).astype(np.uint8)
    frames = frames[:, ::-1, ::-1]
    minimum = maximum = min_indices = max_indices = None
    for index, image in enumerate(frames):
        minimum, maximum, min_indices, max_indices = update_projection_extrema(
            minimum, maximum, image, index, min_indices, max_indices,
            track_indices=True,
        )
    np.testing.assert_array_equal(minimum, frames.min(axis=0))
    np.testing.assert_array_equal(maximum, frames.max(axis=0))
    np.testing.assert_array_equal(min_indices, frames.argmin(axis=0))
    np.testing.assert_array_equal(max_indices, frames.argmax(axis=0))
    coverage = exposure_coverage(0, 10, [(-2, 4), (3, 6), (8, 12)])
    assert coverage["coverage_fraction"] == 0.8
    assert coverage["gaps"] == [(6, 8)]


def recorder_result(duration=1.0, coverage=0.999, count=30):
    image = np.arange(12, dtype=np.uint8).reshape(3, 4)
    indices = np.full((3, 4), count - 1, np.uint32)
    return image, image + 1, indices, indices.copy(), {
        "actual_scan_time_s": duration, "coverage_fraction": coverage,
        "selected_speed": 100, "selected_frame_count": count,
        "camera_exposure_ms": 19.74,
    }


def recording_microscope():
    mic = SimulatedMicroscope()
    mic.send_command_and_wait = Mock(return_value=[1, 0])
    mic.setShutter = Mock()
    mic.getMetadata = Mock(return_value={"MicroscopeName": "Mic3"})
    mic.cam.getMetadata = Mock(return_value={"Exposure": "3.0"})
    mic.memmap_writer = SimpleNamespace(store_image=Mock())
    mic.recordTimedContinuousProjection = Mock(return_value=recorder_result())
    mic.used_disk_space = 0
    return mic


@pytest.mark.parametrize("frame_count,dtype", [(30, np.uint8), (257, np.uint16)])
def test_saves_four_raw_tiffs_with_mic3_metadata(tmp_path, frame_count, dtype):
    mic = recording_microscope()
    mic.recordTimedContinuousProjection.return_value = recorder_result(count=frame_count)
    result = mic.rec_timed_continuous_projection(
        str(tmp_path / "image_{z}.tif"), -10, 10, 1.0,
        cached_preflight={"p99": 100, "saturated_fraction": 0.0},
    )
    paths = sorted(tmp_path.glob("*.tif"))
    assert len(paths) == 4
    with tifffile.TiffFile(str(tmp_path / "image_MaxProj.tif")) as tif:
        metadata = json.loads(tif.pages[0].description)
        assert metadata["MicroscopeName"] == "Mic3"
        assert metadata["Exposure"] == "19.74"
        np.testing.assert_array_equal(tif.asarray(), recorder_result()[1])
    index_image = tifffile.imread(str(tmp_path / ("image_MaxIndices%d.tif" % frame_count)))
    assert index_image.dtype == dtype
    assert np.all(index_image == frame_count - 1)
    assert result["attempts"][0]["accepted"]
    assert mic.used_disk_space == sum(path.stat().st_size for path in paths)
    assert mic.setShutter.call_args.args == (0,)


def test_retries_keep_origin_and_only_save_accepted_scan(tmp_path):
    mic = recording_microscope()
    mic.recordTimedContinuousProjection.side_effect = [recorder_result(1.2), recorder_result()]
    mic.saveImage = Mock()
    mic.rec_timed_continuous_projection(
        str(tmp_path / "retry_{z}.tif"), -10, 10, 1.0, leave_at_edge=True,
        cached_preflight={"p99": 100, "saturated_fraction": 0.0},
    )
    calls = mic.recordTimedContinuousProjection.call_args_list
    assert [c.kwargs["center_z_steps"] for c in calls] == [500, 500]
    assert calls[1].kwargs["speed_override"] == 120
    assert mic.saveImage.call_count == 4


def test_failed_coverage_saves_nothing_and_restores_shutter(tmp_path):
    mic = recording_microscope()
    mic.recordTimedContinuousProjection.return_value = recorder_result(coverage=0.8)
    mic.saveImage = Mock()
    with pytest.raises(RuntimeError, match="timing/coverage limits"):
        mic.rec_timed_continuous_projection(
            str(tmp_path / "bad_{z}.tif"), -10, 10, 1.0,
            cached_preflight={"p99": 100, "saturated_fraction": 0.0},
        )
    mic.saveImage.assert_not_called()
    assert mic.setShutter.call_args.args == (0,)


def test_session_alternates_direction_restores_origin_and_reports_write_errors():
    mic = recording_microscope()
    mic.rec_timed_continuous_projection = Mock(return_value={"preflight": {}})
    with mic.timed_projection_session() as session:
        session.record("a_{z}.tif", -10, 20, 1.0)
        mic.position = 525
        session.record("b_{z}.tif", -10, 20, 1.0)
        mic.position = 480
    calls = mic.rec_timed_continuous_projection.call_args_list
    assert calls[0].args[1:3] == (-10, 20)
    assert calls[1].args[1:3] == (20, -10)
    assert [c.kwargs["center_z_steps"] for c in calls] == [500, 500]
    assert (mic.position, mic.speed) == (500, 123)
    mic._save_timed_projection_files = Mock(side_effect=OSError("disk full"))
    with pytest.raises(OSError, match="disk full"):
        with mic.timed_projection_session() as session:
            session.record("a_{z}.tif", -10, 20, 1.0)
            mic.position = 525
            session._queue_files([])
    assert (mic.position, mic.speed) == (500, 123)


@pytest.mark.parametrize("settings", [
    {"scan_time_s": float("nan")}, {"scan_time_s": 0.1},
    {"z_start_um": 10}, {"maximum_attempts": 1.5},
])
def test_invalid_scan_fails_before_hardware_access(settings):
    mic = recording_microscope()
    arguments = dict(filename="a_{z}.tif", z_start_um=-10, z_stop_um=10,
                     scan_time_s=1.0)
    arguments.update(settings)
    with pytest.raises(ValueError):
        mic.rec_timed_continuous_projection(**arguments)
    mic.send_command_and_wait.assert_not_called()
    mic.setShutter.assert_not_called()
