# -*- coding: utf-8 -*-
"""
Created on Mon Aug 17 13:26:58 2015

@author: Richard
"""

from __future__ import print_function, division

import os
import sys
import tifffile
import psutil
import time
import datetime
import threading

PY3 = sys.version_info[0] == 3

sys.path.append(os.path.join(os.path.dirname(__file__), "includes"))
from .includes import CamMemMap, ensureScriptIsRunning, serialize, deserialize

config_file = os.path.join(os.path.dirname(__file__), "Microscope_Config.txt")


class CameraError(Exception):
    """ Error class for camera exceptions"""
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


STATE_Empty = 0
STATE_Written = 1
STATE_Sent = 2
STATE_Received = 3

class Camera:
    ring_buffer_index = 0

    timeout_value = 0.5
    no_exceptions = False

    sequence_is_running = None

    trigger = None

    retry_count = 0

    nowait = False

    def __init__(self):
        # Check if the server is running, if not start it
        ensureScriptIsRunning(["CameraServer.py", "camera_server"], "CameraServer.bat")
        #ensureScriptIsRunning("FlaskTestSimple.py", os.path.join("Flask", "FlaskTestSimple.bat"))
        
        # Load config
        self.config = dict(PixelSize=6.45, BitDepth=12)
        if os.path.exists(config_file):
            if PY3:
                with open(config_file, "r") as fp:
                    code = compile(fp.read(), config_file, 'exec')
                    exec(code, globals(), self.config)
            else:
                execfile(config_file, globals(), self.config)
        # set the trigger
        if "Trigger" in self.config and self.config["Trigger"] == "NiDAQ":
            print("Using NiDAQ Trigger")
            from .CameraTrigger import NiDAQ_Trigger
            self.trigger = NiDAQ_Trigger()
        elif "Trigger" in self.config and self.config["Trigger"] == "Arduino":
            print("Using Arduino Trigger")
            from .CameraTrigger import Arduino_Trigger
            self.trigger = Arduino_Trigger()

        # Path to store status
        self.web_server_path = os.path.join(os.path.dirname(__file__), "Flask")

        # initialize the memory map
        self.memmap = CamMemMap(self.config["Height"], self.config["Width"])
        self.ring_buffer_index = self.memmap.current_index

    def _askServer(self, function, *args, **kwargs):
        """ communication with the server """
        # get callback kwarg
        if "callback" in kwargs:
            callback = kwargs["callback"]
            del kwargs["callback"]
        else:
            callback = None
        # fill slot
        with self.memmap.editLock:
            next_command = self.memmap.current_command_index + 1
            cmd = self.memmap.commands[next_command % len(self.memmap.commands)]

            cmd.status = STATE_Written
            cmd.function = function
            cmd.args = serialize(args)
            # increase command index
            self.memmap.current_command_index = next_command

        # only if we should wait
        if self.nowait or callback:
            t = threading.Thread(target=lambda: self.waitForCommand(function, args, cmd, callback))
            t.start()
            return

        return self.waitForCommand(function, args, cmd)

    def waitForCommand(self, function, args, cmd, callback=None):
        # wait for the command to return and check timeout
        start_time = time.time()
        timeout_value = self.timeout_value + self.memmap.exposure
        while cmd.status != STATE_Received and time.time() - start_time < timeout_value:
            time.sleep(0.01)

        # is the command not finished? -> timeout
        if cmd.status != STATE_Received:
            self.retry_count += 1
            # try tree times
            if self.retry_count < 3:
                return self._askServer(function, *args)
            self.retry_count = 0
            # raise exception or ignore
            if self.no_exceptions:
                print("Timeout")
                return None
            raise CameraError(" ".join(str(a) for a in (
            "Timeout", "Command", function, datetime.datetime.fromtimestamp(start_time),
            datetime.timedelta(seconds=timeout_value))))
        # reset retry count
        self.retry_count = 0

        # set the command to received
        with self.memmap.editLock:
            cmd.status = STATE_Empty
            received = cmd.response

        # check if the response is an error message
        if cmd.error:
            error_praefix = "Error:"
            if self.no_exceptions:
                print(received[len(error_praefix):])
                return None
            print(received[len(error_praefix):])
            raise CameraError(received[len(error_praefix):])

        # if a callback is defined
        if callback is not None:
            callback([received, deserialize(received)])

        # return the result converted back from json
        return deserialize(received)

    """ process blocking """

    def setBlockingProcess(self, pid=None):
        """ set a process as blocking for the camera """
        if pid is None:
            pid = os.getpid()
        self.memmap.blocking_process = pid

    def getBlockingProcess(self):
        """ check if a process is blocking the camera and if that process is still running
        """
        if self.memmap.blocking_process:
            try:
                p = psutil.Process(self.memmap.blocking_process)
                if p.status() != "running":
                    self.memmap.blocking_process = 0
            except psutil.NoSuchProcess:
                self.memmap.blocking_process = 0
        return self.memmap.blocking_process

    """ gain settings """

    def setGainValue(self, gain):
        """ set the gain value of the camera """
        if self.memmap.gain == gain:
            return True
        res = self._askServer("setGainValue", gain)
        self.memmap.gain = gain
        return res
        
    def getGainValue(self):
        """ get the current gain value of the camera """
        return self.memmap.gain

    """ exposure settings """

    def setExposure(self, exp, force=False, callback=None):
        """ set the exposure time of the camera in ms """
        exp = float(max(0.1, exp))  # minimum exposure time is 0.1 ms
        if self.memmap.exposure == exp and not force:
            return True
        #self.memmap.exposure = 0
        return self._askServer('setExposure', exp, callback=callback)
    
    def getExposure(self):
        """ get the current exposure time of the caera """
        return self.memmap.exposure

    """ binning settings """

    def setBinning(self, value=None):
        """ set the binning value. Possible values are 1, 2, 4, 8 """
        if value == 1 or value is None:
            binning = "1x1"
        elif value == 2:
            binning = "2x2"
        elif value == 4:
            binning = "4x4"
        elif value == 8:
            binning = "8x8"
        else:
            raise ValueError("Binning should be 1, 2, 4 or 8. %s is no valid binning value" % str(value))
        self.memmap.binning = value
        self._askServer("setBinning", binning)
        
    def getBinning(self):
        """ get the current binning value """
        return self.memmap.binning

    """ roi settings """

    def setROI(self, x, y, dx, dy):
        """ set a region of interset to crop the recorded area of the camera. results in an increased frame rate """
        if x < 0 or y < 0 or x+dx > self.config["Width"] or y+dy > self.config["Height"]:
            raise ValueError("ROI has to be inside the image of 0, 0, %s, %s"%(self.config["Width"], self.config["Height"]))
        x = int(x); y = int(y); dx = int(dx); dy = int(dy)
        return self._askServer('setROI', x, y, dx, dy)

    def getROI(self):
        """ get the currently set ROI """
        return self._askServer('getROI')

    def clearROI(self):
        """ clear the ROI. back to uncropped view """
        return self._askServer('clearROI')

    def getImageWidth(self):
        """ get the currently set image width """
        return self.memmap.roi[2]

    def getImageHeight(self):
        """ get the currently set image height """
        return self.memmap.roi[3]

    """ properties """
    def setProperty(self, device, name, value, callback=None):
        self._askServer("setProperty", device, name, value, callback=callback)

    def getProperty(self, device, name, callback=None):
        return self._askServer("getProperty", device, name, callback=callback)

    def getPropertyList(self):
        properties = []
        for i in range(self.memmap.property_count):
            prop = self.memmap.properties[i]
            properties.append(prop)
        return properties

    """ flatfield """
    def recordFlatField(self, N):
        # set the timeout to wait for N pictures  (plus extra factor because it takes quite long)
        timeout = self.timeout_value
        self.timeout_value = timeout * N * 10
        # start recording
        self._askServer('recordFlatField', N)
        # reset the timeout
        self.timeout_value = timeout

    def recordDarkField(self, N):
        # set the timeout to wait for N pictures  (plus extra factor because it takes quite long)
        timeout = self.timeout_value
        self.timeout_value = timeout * N * 10
        # start recording
        self._askServer('recordDarkField', N)
        # reset the timeout
        self.timeout_value = timeout

    """ sequence recording """

    def startContinuousSequenceAcquisition(self, value):
        """ let the camera take pictures continuously """
        if self.trigger:
            if value == 1:  # 1 means as fast as possible, free running == internal trigger
                self.setProperty('Camera', 'TRIGGER SOURCE', 'INTERNAL')
                self.setExposure(self.memmap.exposure, force=True)  # safety to keep the exposure time (without this mic2 has problems)
                self.trigger.Stop()
            if value > 1:  # a fixed delta? -> external trigger
                self.setProperty('Camera', 'TRIGGER SOURCE', 'EXTERNAL')
                self.setExposure(self.memmap.exposure, force=True)  # safety to keep the exposure time (without this mic2 has problems)
                self.trigger.Trigger(delta=(value*1E-3))
            self.sequence_is_running = True

        if self.memmap.sequence:
            return None
        return self._askServer('startContinuousSequenceAcquisition', value)

    def stopSequenceAcquisition(self):
        """ stop a sequence acquisition """
        if self.trigger:  # if we have a trigger just
            self.trigger.Stop()
            self.setProperty('Camera', 'TRIGGER SOURCE', 'EXTERNAL')
            self.setExposure(self.memmap.exposure, force=True)  # safety to keep the exposure time (without this mic2 has problems)
            self.sequence_is_running = False
            if self.memmap.sequence:
                return None
            return self._askServer('startContinuousSequenceAcquisition', 1)
        return self._askServer('stopSequenceAcquisition')

    def isSequenceRunning(self):
        """ if a sequence acquisition is running """
        if self.trigger:
            return self.sequence_is_running
        return self.memmap.sequence

    def getLastImage(self):
        """ get the last image from the buffer """
        self.ring_buffer_index = self.memmap.current_index
        return self.memmap.getImageAtPosition(self.memmap.current_index)

    def popNextImage(self):
        """ get the next image form the buffer """
        if self.ring_buffer_index > self.memmap.current_index or self.memmap.current_index-self.ring_buffer_index > len(self.memmap.images):
            self.ring_buffer_index = self.memmap.current_index
            raise ValueError("Images dropped")
        if self.ring_buffer_index == self.memmap.current_index:
            return None
        self.ring_buffer_index += 1
        return self.memmap.getImageAtPosition(self.ring_buffer_index)

    def clearImages(self):
        """ clear the buffer """
        self.ring_buffer_index = self.memmap.current_index

    def getRemainingImageCount(self):
        """ get the number of unread images in the buffer """
        if self.ring_buffer_index > self.memmap.current_index:
            self.ring_buffer_index = self.memmap.current_index
        return self.memmap.current_index - self.ring_buffer_index

    def getCurrentImageNumber(self):
        """ get the current image number of the buffer """
        return self.memmap.current_index

    """ Single image recording """

    def snapImage(self):
        """ ask the camera to take a picture """
        self.clearImages()
        if self.trigger:
            if self.sequence_is_running is None or self.sequence_is_running:
                self.stopSequenceAcquisition()
            self.trigger.TriggerOnce()
            time_start = time.time()
            timeout = max(self.memmap.exposure*1e-3*2, 2)  # two times the exposure time or two seconds
            while not self.getRemainingImageCount():
                if time.time()-time_start > timeout:
                    print("Camera didn't react on trigger signal, retrying. If it does't work switch to untriggered mode")
                    self.trigger.TriggerOnce()
                    time_start = time.time()
                pass
            return True
        return self._askServer('snapImage')

    def getImage(self):
        """ get the picture the camera has taken """
        if self.trigger:
            return self.popNextImage()
        shape = self._askServer("getImage")
        return self.memmap.getImageAtPosition(self.memmap.current_index)

    """ meta data """

    def getPixelSize(self):
        """ returns the pixel size of the camera (defined by the config.txt) """
        return self.config["PixelSize"]
        
    def getMetadata(self):
        """ return the meta data for the current image """
        metadata = dict(Exposure=str(self.memmap.exposure), Gain=str(self.memmap.gain), PixelSize=self.config["PixelSize"]*self.memmap.binning)
        return metadata

    """ image saveing """
    
    def saveImage(self, name, img, add_metadata=None, microscope=None):
        """ save an image with meta data """
        metadata = self.getMetadata()
        if microscope:
            metadata.update(microscope.getMetadata())
        if add_metadata is not None:
            metadata.update(add_metadata)
        tifffile.imsave(name, img, metadata=metadata)
        
    def saveStatus(self, text, percent="", useBot=False):
        """ write a status to the web server """
        with open(os.path.join(self.web_server_path, "status.txt"), 'w') as fp:
            fp.write(datetime.datetime.now().strftime("Last Update: %a, %d %b %Y %H:%M:%S"))
            fp.write("<br>\n")
            fp.write(text)
        with open(os.path.join(self.web_server_path, "percent.txt"), 'w') as fp:
            fp.write(percent)
# commit your shit guys!

if __name__ == '__main__':
    """ for use as a stand alone script
        start it with a console that stays open and call commends
        e.g. mmc.setExposure(100)
    """
    mmc = Camera()
