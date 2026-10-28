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
        self.camera.GainAuto = "Off"  #"Continuous"
        self.camera.AutoTargetBrightness = 0.5
        self.camera.AutoGainLowerLimit = 0
        self.camera.AutoGainUpperLimit = 1  #36
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
        self.camera.StartGrabbingMax(buffer.shape[0])
        for i in range(buffer.shape[0]):
            grabResult = self.camera.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)

            if grabResult.GrabSucceeded():
                im = grabResult.Array
                if self.config["flip_y"]:
                    im = im[::-1]
                buffer[i] = im

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
                        if self.config["flip_x"]:
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
        im = self.camera.GrabOne(1000).Array
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
        return None

    def setGain(self, gain: float):
        print("WARNING: gain is automatically adjusted")

    def get_gain_range(self):
        return [0, 10000]

    def binning(self) -> int:
        return 1

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
