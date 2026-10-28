from lucam import Lucam, API
import time
import numpy as np

from leica_microscope.includes.config import getConfig
from leica_microscope.camera import CameraBase

class Fast:
    def __init__(self, cam, lucam):
        self.cam = cam
        self.lucam = lucam

    def __enter__(self):
        self.cam.fast_enabled = True
        frameformat, framerate = self.lucam.GetFormat()
        snapshot = Lucam.Snapshot(exposure=self.lucam.exposure, gain=self.lucam.gain,
                                  timeout=60000.0, format=frameformat)
        self.lucam.EnableFastFrames(snapshot)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cam.fast_enabled = False
        self.lucam.DisableFastFrames()

    def __call__(self, *args, **kwargs):
        pass


class Camera(CameraBase):
    def __init__(self):
        super().__init__()
        self.config = getConfig(dict(PixelSize=4.0954, filp_y=False, flip_x=False))
        self.lucam = Lucam()
        self.resetFormat()

        self.fast_recording = Fast(self, self.lucam)

        self.callbackid = None
        self.streaming_callback = None
        class PauseStreaming:
            def __init__(self, cam):
                self.cam = cam

            def __enter__(self):
                self.callbackid = self.cam.callbackid
                self.streaming_callback = self.cam.streaming_callback

                if self.callbackid is not None:
                    self.cam.stopStreaming()

            def __exit__(self, exc_type, exc_val, exc_tb):
                if self.callbackid is not None:
                    self.cam.startStreaming(self.streaming_callback)

            def __call__(self, *args, **kwargs):
                return self

        self.pause_streaming = PauseStreaming(self)

    def resetFormat(self):
        frameformat, framerate = self.lucam.GetFormat()
        self.lucam.SetFormat(
                Lucam.FrameFormat(0, 0, frameformat.width, frameformat.height, API.LUCAM_PF_16,
                                  binningX=1, flagsX=1, binningY=1, flagsY=1),
                framerate=1000.0)

    """ recording """

    def getVideoBuffer(self, count) -> np.ndarray:
        # alternative code to generate a buffer
        """
        # get the buffer where to store the images
        lucam.StreamVideoControl('start_streaming')
        buffer, pdata = ndarray(lucam._streaming, lucam._byteorder, None, True, numframes)
        lucam.StreamVideoControl('stop_streaming')
        return buffer
        """
        frameformat, framerate = self.lucam.GetFormat()
        pixeldepth = self.lucam.GetTruePixelDepth()
        format = np.uint8
        if pixeldepth > 8:
            format = np.uint16
        return np.zeros([count, frameformat.height, frameformat.width], dtype=format)
    
    def getVideo(self, buffer):
        # the TakeVideo unfortunately does cause a timeout
        """
        self.lucam.StreamVideoControl('start_streaming')  # streaming without display
        self.lucam.SetTimeout(False, 600000)
        self.lucam.SetTimeout(True, 600000)
        self.lucam.TakeVideo(None, out=buffer)
        self.lucam.StreamVideoControl('stop_streaming')
        """
        # so we now use the streamer callback
        numframes = buffer.shape[0]
        N = 0
        running = True
        dtype = self.getDtype()

        # define a callback to copy the image data into the buffer
        def streaming_callback(context, data, size):
            nonlocal N, running
            # check how many frames are recorded yet
            if N < numframes:
                # copy the data to the buffer
                buffer[N, :, :] = np.ctypeslib.as_array(data, shape=(size,)).view(dtype=dtype).reshape(*buffer[0].shape)
            else:
                running = False
            N += 1

        # add the callback
        callbackid = self.lucam.AddStreamingCallback(streaming_callback)

        # start the streaming
        self.lucam.StreamVideoControl('start_streaming')
        # wait for the callback to count enough frames
        while running:
            time.sleep(0.01)
        # stop the streaming
        self.lucam.StreamVideoControl('stop_streaming')
        # and remove the callback
        self.lucam.RemoveStreamingCallback(callbackid)

        if self.config["flip_y"]:
            buffer = buffer[::-1]
        if self.config["flip_x"]:
            buffer = buffer[:, ::-1]
        return buffer >> 2

    def startStreaming(self, callback):
        if self.callbackid is not None:
            print("stop previous")
            self.stopStreaming()
        # get the shape of the images
        print("getFormat")
        frameformat, framerate = self.lucam.GetFormat()
        shape = (frameformat.height, frameformat.width)
        print("getDtype")
        dtype = self.getDtype()

        # define a callback to transform the data into a numpy image
        def streaming_callback(context, data, size):
            im = np.ctypeslib.as_array(data, shape=(size,)).view(dtype=dtype).reshape(*shape)
            if self.config["flip_y"]:
                im = im[::-1]
            if self.config["flip_x"]:
                im = im[:, ::-1]
            callback(im >> 2)
        print("add callback")
        # add the callback
        self.callbackid = self.lucam.AddStreamingCallback(streaming_callback)
        self.streaming_callback = callback
        print("startVideoStreamControl")
        # start the streaming
        self.lucam.StreamVideoControl('start_streaming')
        print("done")

    def stopStreaming(self):
        if self.callbackid is None:
            return
        # stop the streaming
        print("stop streaming")
        self.lucam.StreamVideoControl('stop_streaming')
        # and remove the callback
        print("remove allback")
        self.lucam.RemoveStreamingCallback(self.callbackid)
        print("set callback id to None")
        self.callbackid = None

    def getImage(self):
        if self.fast_enabled is True:
            im = self.lucam.TakeFastFrame() >> 2
        else:
            im = self.lucam.TakeSnapshot() >> 2
        if self.config["flip_y"]:
            im = im[::-1]
        if self.config["flip_x"]:
            im = im[:, ::-1]
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

    def get_exposure_range(self):
        return [0, 10000]

    def gain(self) -> float:
        return self.lucam.GetProperty('gain')[0]

    def setGain(self, gain: float):
        self.lucam.set_properties(gain=gain)

    def get_gain_range(self):
        return [0, 10000]

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
