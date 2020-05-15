from lucam import Lucam, API
import numpy as np

from leica_microscope.includes.config import getConfig

class Fast:
    def __init__(self, cam, lucam):
        self.cam = cam
        self.lucam = lucam

    def __enter__(self):
        self.cam.fast_enabled = True
        frameformat, framerate = self.lucam.GetFormat()
        snapshot = Lucam.Snapshot(exposure=self.lucam.exposure, gain=self.lucam.gain,
                                  timeout=1000.0, format=frameformat)
        self.lucam.EnableFastFrames(snapshot)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cam.fast_enabled = False
        self.lucam.DisableFastFrames()

    def __call__(self, *args, **kwargs):
        pass

class Camera:
    def __init__(self):
        self.config = getConfig(dict(PixelSize=4.0954))
        self.lucam = Lucam()
        self.resetFormat()

        self.fast_recording = Fast(self, self.lucam)
        self.fast_enabled = False

    def resetFormat(self):
        frameformat, framerate = self.lucam.GetFormat()
        self.lucam.SetFormat(
                Lucam.FrameFormat(0, 0, frameformat.width, frameformat.height, API.LUCAM_PF_16,
                                  binningX=1, flagsX=1, binningY=1, flagsY=1),
                framerate=1000.0)

    """ recording """

    def getVideoBuffer(self, count) -> np.ndarray:
        frameformat, framerate = self.lucam.GetFormat()
        pixeldepth = self.lucam.GetTruePixelDepth()
        format = np.uint8
        if pixeldepth > 8:
            format = np.uint16
        return np.zeros([count, frameformat.height, frameformat.width], dtype=format)

    def getVideo(self, buffer):
        self.lucam.StreamVideoControl('start_streaming')  # streaming without display
        self.lucam.TakeVideo(None, out=buffer)
        self.lucam.StreamVideoControl('stop_streaming')
        if self.config["flip_y"]:
            buffer[:] = buffer[::-1]
        return buffer

    def getImage(self):
        if self.fast_enabled is True:
            im = self.lucam.TakeFastFrame()
        else:
            im = self.lucam.TakeSnapshot()
        if self.config["flip_y"]:
            im = im[::-1]
        return im

    """ properties """

    def roi(self):
        frameformat, framerate = self.lucam.GetFormat()
        return [frameformat.xOffset, frameformat.yOffset, frameformat.width, frameformat.height]

    def setROI(self, x, y, w, h):
        frameformat, framerate = self.lucam.GetFormat()
        self.lucam.SetFormat(
            Lucam.FrameFormat(x, y, w, h, API.LUCAM_PF_16,
                              binningX=frameformat.binningX, flagsX=1, binningY=frameformat.binningY, flagsY=1),
            framerate=1000.0)

    def exposure(self) -> float:
        return self.lucam.GetProperty('exposure')[0]

    def setExposure(self, exposure: float):
        self.lucam.set_properties(exposure=exposure)

    def gain(self) -> float:
        return self.lucam.GetProperty('gain')[0]

    def setGain(self, gain: float):
        self.lucam.set_properties(gain=gain)

    def binning(self) -> int:
        return self.lucam.GetFormat()[0].binningX

    def setBinning(self, binning: int):
        self.lucam.SetFormat(
            Lucam.FrameFormat(0, 0, self.getWidth(), self.getHeight(), API.LUCAM_PF_16,
                              binningX=binning, flagsX=1, binningY=binning, flagsY=1),
            framerate=1000.0)

    def getFramerate(self) -> float:
        frameformat, framerate = self.lucam.GetFormat()
        return framerate

    def getWidth(self) -> int:
        frameformat, framerate = self.lucam.GetFormat()
        return frameformat.width

    def getHeight(self) -> int:
        frameformat, framerate = self.lucam.GetFormat()
        return frameformat.height

    def getMaxValue(self) -> int:
        pixeldepth = self.lucam.GetTruePixelDepth()
        return 2**pixeldepth

    def getDtype(self):
        pixeldepth = self.lucam.GetTruePixelDepth()
        if pixeldepth > 8:
            return np.uint16
        return np.uint8

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
