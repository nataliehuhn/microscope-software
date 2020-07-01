from pypylon import pylon
from pypylon import genicam
import numpy as np

from leica_microscope.includes.config import getConfig

class Fast:
    def __init__(self):
        pass

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def __call__(self, *args, **kwargs):
        pass

class Camera:
    def __init__(self):
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
        self.camera.GainAuto = "Continuous"
        self.camera.AutoTargetBrightness = 0.5
        self.camera.AutoGainLowerLimit = 0
        self.camera.AutoGainUpperLimit = 36
        self.camera.AcquisitionFrameRateEnable = True
        # camera.AcquisitionFrameRate = 500
        self.camera.ExposureTime = 30

        self.fast_recording = Fast()
        self.fast_enabled = False

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

    def getImage(self):
        im = self.camera.GrabOne(100).Array
        if self.config["flip_y"]:
            im = im[::-1]
        return im

    """ properties """

    def roi(self):
        return None

    def setROI(self, x, y, w, h):
        print("WARNING: roi is currently not supported")

    def exposure(self) -> float:
        return self.camera.ExposureTime()

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

    def getFramerate(self) -> float:
        return self.camera.AcquisitionFrameRate()

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
