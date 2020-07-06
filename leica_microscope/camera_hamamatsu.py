from leica_microscope.includes.hamamatsu_camera import HamamatsuCamera
import numpy as np

from leica_microscope.includes.config import getConfig
from leica_microscope.camera import CameraBase

class Fast:
    def __init__(self, cam, camera):
        self.cam = cam
        self.camera = camera

    def __enter__(self):
        self.cam.fast_enabled = True
        self.camera.startAcquisition()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cam.fast_enabled = False
        self.camera.stopAcquisition()

    def __call__(self, *args, **kwargs):
        pass

class Camera(CameraBase):
    def __init__(self):
        super().__init__()
        self.config = getConfig(dict(PixelSize=6.45))
        self.camera = HamamatsuCamera(0)
        self.camera.initCamera()
        self.camera.setPropertyValue("readout_speed", 1)
        self.camera.setPropertyValue("defect_correct_mode", 1)

        self.fast_recording = Fast(self, self.camera)

    """ recording """

    def getVideoBuffer(self, count) -> np.ndarray:
        width = self.getWidth()
        height = self.getHeight()
        format = self.getDtype()
        return np.zeros([count, height, width], dtype=format)

    def getVideo(self, buffer):
        self.camera.startAcquisition()
        cnt = 0
        while cnt < buffer.shape[0]:
            [frames, dims] = self.camera.getFrames()
            for aframe in frames:
                buffer[cnt] = aframe.getData().reshape(dims[1], dims[0])
                cnt += 1

        self.camera.stopAcquisition()

        if self.config["flip_y"]:
            buffer[:] = buffer[::-1]
        return buffer >> 2

    def getImage(self):
        if self.fast_enabled is True:
            [frames, dims] = self.camera.getFrames()
            im = frames[-1].getData().reshape(dims[1], dims[0])
        else:
            self.camera.startAcquisition()
            [frames, dims] = self.camera.getFrames()
            im = frames[-1].getData().reshape(dims[1], dims[0])
            self.camera.stopAcquisition()

        if self.config["flip_y"]:
            im = im[::-1]
        return im

    """ properties """

    def roi(self):
        return [
            self.camera.getPropertyValue("subarray_hpos")[0],
            self.camera.getPropertyValue("subarray_vpos")[0],
            self.camera.getPropertyValue("subarray_hsize")[0],
            self.camera.getPropertyValue("subarray_vsize")[0],
        ]

    def setROI(self, x, y, w, h):
        # First needs to go full frame, if not, throws an error of subframe not valid
        self.camera.setPropertyValue("subarray_vpos", 0)
        self.camera.setPropertyValue("subarray_hpos", 0)
        self.camera.setPropertyValue("subarray_vsize", self.camera.max_height)
        self.camera.setPropertyValue("subarray_hsize", self.camera.max_width)
        self.camera.setSubArrayMode()

        X = [x, w]
        Y = [y, h]
        # Because of how Orca Flash 4 works, all the ROI parameters have to be multiple of 4.
        hsize = int(abs(X[0] - X[1]) / 4) * 4
        hpos = int(X[0] / 4) * 4
        vsize = int(abs(Y[0] - Y[1]) / 4) * 4
        vpos = int(Y[0] / 4) * 4
        self.camera.setPropertyValue("subarray_vpos", vpos)
        self.camera.setPropertyValue("subarray_hpos", hpos)
        self.camera.setPropertyValue("subarray_vsize", vsize)
        self.camera.setPropertyValue("subarray_hsize", hsize)
        self.camera.setSubArrayMode()

    def exposure(self) -> float:
        return self.camera.getPropertyValue('exposure_time')[0]

    def setExposure(self, exposure: float):
        self.camera.setPropertyValue("exposure_time", exposure)

    def get_exposure_range(self):
        return self.camera.getPropertyRange("exposure_time")

    def gain(self) -> float:
        return self.camera.getPropertyValue('contrast_gain')[0]

    def setGain(self, gain: float):
        self.camera.setPropertyValue('contrast_gain', gain)

    def get_gain_range(self):
        return self.camera.getPropertyRange("contrast_gain")

    def binning(self) -> int:
        return self.camera.getPropertyValue('binning')[0]

    def setBinning(self, binning: int):
        self.camera.setPropertyValue('binning', binning)

    def getFramerate(self) -> float:
        return self.camera.getPropertyValue("internal_frame_rate")[0]

    def getWidth(self) -> int:
        return self.camera.getPropertyValue("subarray_hsize")[0]

    def getHeight(self) -> int:
        return self.camera.getPropertyValue("subarray_vsize")[0]

    def getMaxValue(self) -> int:
        pixeldepth = self.camera.getPropertyValue("bit_per_channel")[0]
        return 2**pixeldepth

    def getDtype(self):
        pixeldepth = self.camera.getPropertyValue("bit_per_channel")[0]
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
                        BitDepth=self.camera.getPropertyValue("bit_per_channel")[0])
        return metadata
