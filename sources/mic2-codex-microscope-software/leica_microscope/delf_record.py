from lucam import Lucam, API, LucamEnumCameras
import numpy as np
import time

def getImage(ex):
    global shape, dtype
    lucam.set_properties(exposure=ex, gain=0)

    running = True
    image = None

    # define a callback to copy the image data into the buffer

    def streaming_callback(context, data, size):
        nonlocal running, image
        print("got image")
        # check how many frames are recorded yet
        image = np.ctypeslib.as_array(data, shape=(size,)).view(dtype=dtype).reshape(*shape).copy() << 2
        running = False

    # add the callback
    callbackid = lucam.AddStreamingCallback(streaming_callback)
    t = time.time()
    # start the streaming
    lucam.StreamVideoControl('start_streaming')
    # wait for the callback to count enough frames
    while running:
        time.sleep(0.01)
    # stop the streaming
    lucam.StreamVideoControl('stop_streaming')
    # and remove the callback
    lucam.RemoveStreamingCallback(callbackid)
    return image


def testExtendedExposure():
    lucam.set_properties(exposure=1000, gain=0)
    try:
        image = lucam.TakeSnapshot()
    except:
        return
    raise TypeError("Extended Exposure is not active. Enable it in the Infinity Analyze.")

def initializeLucam():
    global shape, dtype, lucam
    lucam = Lucam()
    frameformat, framerate = lucam.GetFormat()
    lucam.SetFormat(
        Lucam.FrameFormat(0, 0, frameformat.width, frameformat.height, API.LUCAM_PF_16,
                          binningX=1, flagsX=1, binningY=1, flagsY=1),
        framerate=1000.0)

    lucam.set_properties(exposure=1, gain=0)
    im = lucam.TakeSnapshot()
    shape = im.shape
    dtype = im.dtype
    return lucam

lucam = initializeLucam()
testExtendedExposure()

im = getImage(1000)
print(im)

