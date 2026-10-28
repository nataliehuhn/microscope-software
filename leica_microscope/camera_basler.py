from pypylon import pylon
from pypylon import genicam
import numpy as np
import time

from leica_microscope.includes.config import getConfig
from leica_microscope.camera import CameraBase


class Camera(CameraBase):
    def __init__(self):
        super().__init__()
        self.config = getConfig(dict())

        self.camera = pylon.InstantCamera(pylon.TlFactory.GetInstance().CreateFirstDevice())
        self.camera.Open()

        # activate chunkmode for frame timestamps, gain and exposure values
        self.camera.ChunkModeActive = True
        self.camera.ChunkSelector = "Timestamp"
        self.camera.ChunkEnable = True
        self.camera.ChunkSelector = "Gain"
        self.camera.ChunkEnable = True
        self.camera.ChunkSelector = "ExposureTime"
        self.camera.ChunkEnable = True

        # set camera parameters for Exposure and Gain control
        # camera.ExposureAuto = "Continuous"
        # TODO we need to expose these values if we want to change them during runtime
        self.camera.AutoExposureTimeLowerLimit = 30.0  # micro seconds
        self.camera.AutoExposureTimeUpperLimit = 1800  # micro seconds
        self.camera.GainAuto = "Off"  # "Continuous"
        self.camera.AutoTargetBrightness = 0.5
        self.camera.AutoGainLowerLimit = 0
        self.camera.AutoGainUpperLimit = 1#36
        self.camera.AcquisitionFrameRateEnable = True
        # camera.AcquisitionFrameRate = 500
        #self.camera.ExposureTime = 30

        self.camera.OffsetX = 0
        self.camera.OffsetY = 0
        self.camera.Width = self.camera.Width.Max
        self.camera.Height = self.camera.Height.Max

        self.callbackid = None
        self.streaming_callback = None

        class PauseStreaming:
            def __init__(self, cam):
                self.cam = cam

            def __enter__(self):
                self.do_streaming = self.cam.do_streaming
                self.streaming_callback = self.cam.streaming_callback

                if self.do_streaming is True:
                    self.cam.stopStreaming()

            def __exit__(self, exc_type, exc_val, exc_tb):
                if self.do_streaming is True:
                    self.cam.startStreaming(self.streaming_callback)

            def __call__(self, *args, **kwargs):
                return self

        self.pause_streaming = PauseStreaming(self)

    def resetFormat(self):
        pass

    """ recording """

    def getVideoBuffer(self, count) -> np.ndarray:
        return np.zeros([count, self.getHeight(), self.getWidth()], dtype=self.getDtype())

    def getVideo(self, buffer):
        self.getVideoWithTimestamps(buffer)
        return buffer

    def getVideoWithTimestamps(
            self, buffer, started_event=None, first_frame_event=None):
        frame_count = buffer.shape[0]
        camera_ticks = np.zeros(frame_count, dtype=np.uint64)
        host_times = np.zeros(frame_count, dtype=np.float64)
        grab_succeeded = np.zeros(frame_count, dtype=bool)
        capture_start = time.perf_counter()
        self.camera.StartGrabbingMax(buffer.shape[0])
        if started_event is not None:
            started_event.set()
        for i in range(buffer.shape[0]):
            grabResult = self.camera.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
            try:
                host_times[i] = time.perf_counter()
                camera_ticks[i] = grabResult.GetTimeStamp()
                grab_succeeded[i] = grabResult.GrabSucceeded()
                if i == 0 and first_frame_event is not None:
                    first_frame_event.set()
                if grab_succeeded[i]:
                    im = grabResult.Array
                    if self.config["flip_y"]:
                        im = im[::-1]
                    if self.config.get("flip_x", self.config.get("filp_x", False)):
                        im = im[:, ::-1]
                    buffer[i] = im
            finally:
                grabResult.Release()
        capture_end = time.perf_counter()

        if not np.all(grab_succeeded):
            failed = np.flatnonzero(~grab_succeeded).tolist()
            raise RuntimeError("Basler failed to grab frames {}".format(failed))

        tick_frequency = None
        if frame_count > 1:
            tick_delta = float(np.median(np.diff(camera_ticks.astype(np.float64))))
            fps = float(self.getFramerate())
            if tick_delta > 0 and fps > 0:
                tick_frequency = tick_delta * fps

        return {
            "host_times_s": host_times,
            "camera_ticks": camera_ticks,
            "camera_tick_frequency_hz": tick_frequency,
            "capture_start_host_s": capture_start,
            "capture_end_host_s": capture_end,
        }

    def latchTimestampClock(self, samples=8):
        """Align the Basler nanosecond clock to the host monotonic clock.

        A timestamp latch is bracketed by host timestamps.  The shortest
        transaction gives the tightest bound on the host/camera offset.
        Basler ace USB camera timestamps are in nanoseconds.
        """
        if self.camera.IsGrabbing():
            raise RuntimeError("Timestamp clock must be latched before grabbing")
        observations = []
        for _ in range(samples):
            before = time.perf_counter()
            self.camera.TimestampLatch.Execute()
            ticks = int(self.camera.TimestampLatchValue.Value)
            after = time.perf_counter()
            observations.append((after - before, (before + after) / 2.0, ticks))
        delay, host_time, ticks = min(observations)
        return {
            "host_time_s": host_time,
            "camera_ticks": ticks,
            "tick_frequency_hz": 1000000000.0,
            "offset_uncertainty_s": delay / 2.0,
        }


    def getMaximumFramerateAtShortExposure(self):
        """Measure the configured full-resolution readout limit, then restore exposure."""
        if self.camera.IsGrabbing():
            raise RuntimeError("Cannot probe frame rate while grabbing")
        original_exposure_us = float(self.camera.ExposureTime.Value)
        try:
            self.camera.ExposureTime = 1000.0
            return float(self.getFramerate())
        finally:
            self.camera.ExposureTime = original_exposure_us


    def streamFramesWithTimestamps(
            self, on_frame, stop_event, started_event=None,
            first_frame_event=None):
        """Stream frames to a callback without allocating a video stack.

        The callback must finish using the image before returning; the Pylon
        buffer is released immediately afterward.  Chunk timestamps identify
        acquisition start, not host retrieval time.
        """
        self.camera.StartGrabbing(pylon.GrabStrategy_OneByOne)
        if started_event is not None:
            started_event.set()
        count = 0
        try:
            while not stop_event.is_set():
                result = self.camera.RetrieveResult(
                    5000, pylon.TimeoutHandling_ThrowException
                )
                try:
                    retrieved_at = time.perf_counter()
                    if not result.GrabSucceeded():
                        raise RuntimeError(
                            "Basler frame grab failed: {}".format(
                                result.GetErrorDescription()
                            )
                        )
                    if count == 0 and first_frame_event is not None:
                        first_frame_event.set()
                    image = result.Array
                    if self.config["flip_y"]:
                        image = image[::-1]
                    if self.config.get("flip_x", self.config.get("filp_x", False)):
                        image = image[:, ::-1]
                    try:
                        exposure_us = float(result.ChunkExposureTime.Value)
                    except (AttributeError, genicam.GenericException):
                        exposure_us = float(self.camera.ExposureTime.Value)
                    on_frame(
                        image, int(result.GetTimeStamp()), exposure_us,
                        int(result.GetBlockID()), retrieved_at,
                    )
                    count += 1
                finally:
                    result.Release()
        finally:
            self.camera.StopGrabbing()
        return count


    do_streaming = False
    def startStreaming(self, callback):
        self.streaming_callback = callback
        self.do_streaming = True

        # start the streaming
        self.camera.StartGrabbing(pylon.GrabStrategy_OneByOne)
        from threading import Thread
        def streaming():
            while self.do_streaming:
                try:
                    grabResult = self.camera.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)

                    if grabResult.GrabSucceeded():
                        TimeStampCam = grabResult.GetTimeStamp()
                        im = grabResult.Array
                        if self.config["flip_y"]:
                            im = im[::-1]
                        if self.config.get("flip_x", self.config.get("filp_x", False)):
                            im = im[:, ::-1]
                        #print(time.time(), im.min(), im.max())
                        callback(im, TimeStampCam)
                except:
                    break
        self.stream_thread = Thread(target=streaming)
        self.stream_thread.start()

    def stopStreaming(self):
        self.camera.StopGrabbing()
        self.do_streaming = False


    def getImage(self):
        im = self.camera.GrabOne(11000).Array
        if self.config["flip_y"]:
            im = im[::-1]
        return im

    """ properties """

    def roi(self):
        return [0, 0, self.getWidth(), self.getHeight()]

    def setROI(self, x, y, w, h):
        if w > self.camera.Width():
            self.camera.OffsetX = x
            self.camera.Width = w
        else:
            self.camera.Width = w
            self.camera.OffsetX = x

        if h > self.camera.Height():
            self.camera.OffsetY = y
            self.camera.Height = h
        else:
            self.camera.Height = h
            self.camera.OffsetY = y

    def exposure(self) -> float:
        return self.camera.ExposureTime() / 1000

    def setExposure(self, exposure: float):
        # exposure is in ms but the camera wants microseconds
        self.camera.ExposureTime = exposure * 1000

    def get_exposure_range(self):
        return [0, 10000]

    def gain(self) -> float:
        return float(self.camera.Gain.Value)

    def setGain(self, gain: float):
        gain = float(gain)
        minimum, maximum = self.get_gain_range()
        if not np.isfinite(gain) or not minimum <= gain <= maximum:
            raise ValueError(
                "Basler gain must be between {:g} and {:g} dB; got {!r}".format(
                    minimum, maximum, gain
                )
            )
        self.camera.GainAuto.Value = "Off"
        self.camera.Gain.Value = gain

    def get_gain_range(self):
        return [float(self.camera.Gain.Min), float(self.camera.Gain.Max)]

    def binning(self) -> int:
        return 0

    def setBinning(self, binning: int):
        print("WARNING: binning is currently not supported")

    def setFramerate(self, framerate: float):
        self.camera.AcquisitionFrameRate = framerate

    def getFramerate(self) -> float:
        return self.camera.ResultingFrameRate.Value

    def getWidth(self) -> int:
        return self.camera.Width()

    def getHeight(self) -> int:
        return self.camera.Height()

    def getMaxValue(self) -> int:
        return np.iinfo(np.uint8).max

    def getDtype(self):
        return np.uint8

    """ meta data """

    def getPixelSize(self) -> float:
        """ returns the pixel size of the camera (defined by the config.txt) """
        return self.config["pixel_size"]

    def getMetadata(self):
        """ return the meta data for the current image """
        metadata = dict(Exposure=str(self.exposure()), Gain=str(self.gain()),
                        PixelSize=self.config["pixel_size"] * self.binning(),
                        BitDepth=self.getMaxValue())
        return metadata
