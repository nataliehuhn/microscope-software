from leica_microscope.includes.config import getConfig
import importlib
import numpy as np
from typing import List


def Camera():
    config = getConfig()
    module = importlib.import_module(f"leica_microscope.camera_{config['camera']}")
    return module.Camera()



class Fast:
    def __init__(self):
        pass

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def __call__(self, *args, **kwargs):
        pass


class CameraBase:
    def __init__(self):
        self.config = getConfig(dict())

        self.fast_recording = Fast()
        self.fast_enabled = False

    def resetFormat(self):
        """ reset the camera """
        pass

    """ recording """

    def getVideoBuffer(self, count) -> np.ndarray:
        """
        Get a buffer object to store a video with 'count' frames.

        Args:
            count (int): The number of frames.

        Returns:
            buffer: An ndarray of shape [count, height, width].
        """
        return np.zeros([count, self.getHeight(), self.getWidth()], dtype=self.getDtype())

    def getVideo(self, buffer: np.ndarray) -> np.ndarray:
        """
        Record a video into the provided buffer (buffer can be created with getVideoBuffer).
        The video length is determined by the buffer.

        Args:
            buffer: The buffer of shape [count, height, width]

        Returns:
            buffer: The buffer.
        """
        raise NotImplementedError

    def getImage(self) -> np.ndarray:
        """
        Snap a single image.

        Returns:
            image: The image in an ndarray of shape [height, width]
        """
        raise NotImplementedError

    """ properties """

    def roi(self) -> List[int]:
        """ Get the currently active region of interest (roi). """
        return None

    def setROI(self, x: int, y: int, w: int, h: int):
        """ Set the region of interest to record (roi). """
        print("WARNING: roi is currently not supported")

    def exposure(self) -> float:
        """ Get the exposure time in ms. """
        return None

    def setExposure(self, exposure: float):
        """ Set the exposure time in ms. """
        # exposure is in ms but the camera wants microseconds
        print("WARNING: set exposure is currently not supported")

    def get_exposure_range(self) -> List[int]:
        """ Get the range of allowed exposure times. """
        return [0, 10000]

    def gain(self) -> float:
        """ Get the gain value. """
        return None

    def setGain(self, gain: float):
        """ Set the gain value. """
        print("WARNING: set gain is currently not supported")

    def get_gain_range(self) -> List[int]:
        """ Get the range of allowed gain values. """
        return [0, 10000]

    def binning(self) -> int:
        """ Get the binning. """
        return 1

    def setBinning(self, binning: int):
        """ Set the binning. """
        print("WARNING: binning is currently not supported")

    def getFramerate(self) -> float:
        """ Get the framerate of the camera. """
        return None

    def getWidth(self) -> int:
        """ Get the width of the camera image. """
        return None

    def getHeight(self) -> int:
        """ Get the height of the camera image. """
        return None

    def getMaxValue(self) -> int:
        """ Get the maximum value defined by the bit depth of the recording. """
        return 255

    def getDtype(self):
        """ Get the data type that can store the images. """
        return np.uint8

    """ meta data """

    def getPixelSize(self) -> float:
        """ Get the pixel size of the camera (defined by the config.txt). """
        return 1

    def getMetadata(self) -> dict:
        """ Get the meta data for the current image. """
        metadata = dict(Exposure=str(self.exposure()), Gain=str(self.gain()),
                        PixelSize=self.config["pixel_size"] * self.binning(),
                        BitDepth=self.getMaxValue())
        return metadata
