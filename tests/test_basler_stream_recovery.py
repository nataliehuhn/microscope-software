"""Exercise the real stream loop with fake Pylon results, without hardware."""
import threading
from types import SimpleNamespace

import numpy as np
import pytest
from unittest.mock import Mock

from leica_microscope.camera_basler import Camera, genicam
from leica_microscope.recording_resilience import RecoverableAcquisitionError


class Result:
    def __init__(self, block_id, failed=False):
        self.block_id = block_id
        self.failed = failed
        self.released = False
        self.Array = np.full((3, 4), block_id, np.uint8)
        self.ChunkExposureTime = SimpleNamespace(Value=10000.0)

    def GrabSucceeded(self):
        return not self.failed

    def GetErrorDescription(self):
        return "incomplete USB buffer"

    def GetTimeStamp(self):
        return self.block_id * 20000000

    def GetBlockID(self):
        return self.block_id

    def Release(self):
        self.released = True
        self.Array[:] = 0  # Driver can reuse the memory immediately.


class Driver:
    def __init__(self, results):
        self.results = iter(results)
        self.MaxNumBuffer = SimpleNamespace(Value=10)
        self.PayloadSize = SimpleNamespace(Value=2048 * 2048)
        self.stopped = False
        self.buffer_settings = []

    def __setattr__(self, key, value):
        if key == "MaxNumBuffer" and isinstance(value, int):
            self.buffer_settings.append(value)
            self.MaxNumBuffer.Value = value
        else:
            object.__setattr__(self, key, value)

    def StartGrabbing(self, strategy):
        pass

    def StopGrabbing(self):
        self.stopped = True

    def IsGrabbing(self):
        return not self.stopped

    def RetrieveResult(self, timeout, handling):
        return next(self.results)


def camera_with_results(results):
    cam = Camera.__new__(Camera)
    cam.camera = Driver(results)
    cam.config = {"flip_y": True, "flip_x": False}
    cam.getStreamStatistics = lambda: {"Statistic_Missed_Frame_Count": 2}
    return cam


def test_failed_grab_timeout_and_reused_buffer_do_not_stop_stream(capsys):
    good1, failed, good2 = Result(30), Result(31, failed=True), Result(32)
    cam = camera_with_results([good1, failed, None, good2])
    stop = threading.Event()
    received = []

    def callback(image, ticks, exposure, block_id, host):
        assert (good1 if block_id == 30 else good2).released
        assert np.all(image == block_id)
        received.append(block_id)
        if len(received) == 2:
            stop.set()

    assert cam.streamFramesWithTimestamps(callback, stop) == 2
    assert received == [30, 32]
    assert failed.released and cam.camera.stopped
    assert cam.camera.buffer_settings == [32, 10]
    info = cam.last_stream_diagnostics
    assert info["failed_grab_count"] == info["retrieve_timeout_count"] == 1
    assert info["grab_errors"] == ["incomplete USB buffer"]
    assert info["transport_delta"]["Statistic_Missed_Frame_Count"] == 0
    assert "continuing recording" in capsys.readouterr().out


def test_unexpected_callback_error_still_releases_and_restores_camera():
    result = Result(1)
    cam = camera_with_results([result])

    def callback(*args):
        raise ValueError("invalid image processing")

    with pytest.raises(ValueError, match="invalid image processing"):
        cam.streamFramesWithTimestamps(callback, threading.Event())
    assert result.released and cam.camera.stopped
    assert cam.camera.MaxNumBuffer.Value == 10


def test_sdk_timeout_is_recoverable_only_after_camera_cleanup():
    cam = camera_with_results([])

    def fail(*args):
        raise genicam.GenericException("grab timeout")

    cam.camera.RetrieveResult = fail
    with pytest.raises(RecoverableAcquisitionError, match="grab timeout"):
        cam.streamFramesWithTimestamps(lambda *args: None, threading.Event())
    assert cam.camera.stopped
    assert cam.camera.MaxNumBuffer.Value == 10
    cam.camera.stopped = False
    cam.camera.StopGrabbing = fail
    with pytest.raises(RuntimeError, match="stop Basler acquisition safely") as caught:
        cam.streamFramesWithTimestamps(lambda *args: None, threading.Event())
    assert not isinstance(caught.value, RecoverableAcquisitionError)


def test_single_image_releases_driver_buffer_and_returns_owned_pixels():
    result = Result(7)
    cam = camera_with_results([])
    cam.camera.GrabOne = lambda timeout: result
    image = cam.getImage()
    assert result.released and np.all(image == 7)


def test_ordinary_burst_does_not_require_optional_timestamps_or_rate():
    results = [Result(i + 1) for i in range(3)]
    cam = camera_with_results(results)
    cam.camera.StartGrabbingMax = Mock()
    cam.getFramerate = Mock(side_effect=AssertionError("no rate query needed"))
    for result in results:
        result.GetTimeStamp = Mock(side_effect=AssertionError("no timestamp needed"))
        result.Array = np.arange(12, dtype=np.uint8).reshape(3, 4) + result.block_id
    expected = np.stack([r.Array[::-1].copy() for r in results])
    buffer = np.zeros_like(expected)
    assert cam.getVideo(buffer) is buffer
    np.testing.assert_array_equal(buffer, expected)
    assert all(r.released for r in results) and cam.camera.stopped


def test_ordinary_failed_burst_cleans_up_before_recovery():
    failed = Result(1, failed=True)
    cam = camera_with_results([failed])
    cam.camera.StartGrabbingMax = Mock()
    with pytest.raises(RecoverableAcquisitionError, match="stack frame"):
        cam.getVideo(np.zeros((1, 3, 4), np.uint8))
    assert failed.released and cam.camera.stopped
