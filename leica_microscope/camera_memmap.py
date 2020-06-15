import numpy as np
import time

from leica_microscope.includes.MemMap import MemMap
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
    counter_last = -1
    fast_recording = Fast()
    fast_enabled = False

    def __init__(self):
        self.config = getConfig(dict())
        self.mmap = MemMap(self.config["memmap"])

        self.getNewestImage()

    def resetFormat(self):
        print("WARNING: memmap cannot reset the format")

    """ recording """

    def getVideoBuffer(self, count) -> np.ndarray:
        height, width, channels = self.mmap.rbf[0].image.shape
        format = self.mmap.rbf[0].image.dtype
        return np.zeros([count, height, width], dtype=format)

    def getVideo(self, buffer):
        im = self.getNewestImage()
        buffer[0] = im[:, :, 0]
        for i in range(1, buffer.shape[0]):
            im = self.getNextImage()
            buffer[i] = im[:, :, 0]
        if self.config["flip_y"]:
            buffer[:] = buffer[::-1]
        return buffer

    def getImage(self):
        im, timestamp = self.getNextImage()
        while im is None:
            im, timestamp = self.getNextImage()
            time.sleep(0.01)
        im = im[:, :, 0]
        if self.config["flip_y"]:
            im = im[::-1]
        return im

    """ properties """

    def roi(self):
        height, width, channels = self.mmap.rbf[0].image.shape
        return [0, 0, width, height]

    def setROI(self, x, y, w, h):
        print("WARNING: memmap cannot reset the roi")

    def exposure(self) -> float:
        return None

    def setExposure(self, exposure: float):
        print("WARNING: memmap cannot reset the exposure")

    def gain(self) -> float:
        return None

    def setGain(self, gain: float):
        print("WARNING: memmap cannot reset the gain")

    def binning(self) -> int:
        return 1

    def setBinning(self, binning: int):
        print("WARNING: memmap cannot reset the binning")

    def getFramerate(self) -> float:
        return None

    def getWidth(self) -> int:
        height, width, channels = self.mmap.rbf[0].image.shape
        return width

    def getHeight(self) -> int:
        height, width, channels = self.mmap.rbf[0].image.shape
        return height

    def getMaxValue(self) -> int:
        return np.iinfo(self.mmap.rbf[0].image.dtype).max

    def getDtype(self):
        return self.mmap.rbf[0].image.dtype

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

    def getNewestImage(self):
        # get newest counter
        counters = [slot.counter for slot in self.mmap.rbf]
        counter_max = np.max(counters)
        counter_max_idx = np.argmax(counters)
        # return if there is no new one
        if counter_max == self.counter_last:
            # print("not new!")
            return None
        image = self.mmap.rbf[counter_max_idx].image
        # print(image.shape, image.dtype)
        self.counter_last = counter_max
        self.last_slot_index = counter_max_idx
        # print("img type:", image.dtype)
        return image

    def getNextImage(self):
        next_slot_index = (self.last_slot_index + 1) % len(self.mmap.rbf)
        if self.counter_last < self.mmap.rbf[next_slot_index].counter:
            # if self.counter_last+1 != self.mmap.rbf[next_slot_index].counter:
            # raise ValueError("Skipped Frames")
            self.last_slot_index = next_slot_index
            self.counter_last = self.mmap.rbf[next_slot_index].counter
            image = self.mmap.rbf[next_slot_index].image
            return image
        else:
            return None
