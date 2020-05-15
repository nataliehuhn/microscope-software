from pypylon import pylon
from pypylon import genicam
import numpy as np

from leica_microscope.includes.config import getConfig

class Fast:
    def __init__(self, cam, lucam):
        pass

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def __call__(self, *args, **kwargs):
        pass

class Camera:
    def __init__(self):
        self.config = getConfig(dict(PixelSize=4.0954))

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

        self.fast_recording = Fast(self, self.lucam)
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
                buffer[i] = grabResult.Array

    def getImage(self):
        return self.camera.GrabOne(100)

    """ properties """

    def roi(self):
        return None

    def setROI(self, x, y, w, h):
        print("WARNING: roi is currently not supported")

    def exposure(self) -> float:
        return self.camera.ExposureTime

    def setExposure(self, exposure: float):
        self.camera.ExposureTime = exposure

    def gain(self) -> float:
        return None

    def setGain(self, gain: float):
        print("WARNING: gain is automatically adjusted")

    def binning(self) -> int:
        return None

    def setBinning(self, binning: int):
        print("WARNING: binning is currently not supported")

    def getFramerate(self) -> float:
        return self.camera.AcquisitionFrameRate

    def getWidth(self) -> int:
        return self.camera.Width

    def getHeight(self) -> int:
        return self.camera.Height

    def getMaxValue(self) -> int:
        return np.iinfo(np.uint16).max

    def getDtype(self):
        return np.uint16

    """ meta data """

    def getPixelSize(self) -> float:
        """ returns the pixel size of the camera (defined by the config.txt) """
        return self.config["PixelSize"]

    def getMetadata(self):
        """ return the meta data for the current image """
        metadata = dict(Exposure=str(self.exposure()), Gain=str(self.gain()),
                        PixelSize=self.config["PixelSize"] * self.binning(),
                        BitDepth=self.lucam.GetTruePixelDepth())
        return metadata
