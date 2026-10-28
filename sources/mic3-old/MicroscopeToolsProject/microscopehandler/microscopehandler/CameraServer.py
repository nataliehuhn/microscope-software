# -*- coding: utf-8 -*-
from __future__ import print_function, division

import logging
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime

import numpy as np
import psutil
from qtpy import QtCore, QtGui, QtWidgets

sys.path.insert(0, r"C:\Software\old\Micro-Manager-1.4")

from microscopehandler.includes import print_revert, restart, killOldInstance, CamMemMap, deserialize, serialize, getCamLogFile


logging.basicConfig(filename=getCamLogFile(), level=logging.DEBUG,
                    format='%(asctime)s: ' + os.path.basename(__file__) + ' %(message)s')

excepthook = sys.excepthook
# Set the exception hook to our wrapping function
def hook(*args):
    excepthook(*args)
sys.excepthook = hook

STATE_Empty = 0
STATE_Written = 1
STATE_Sent = 2
STATE_Received = 3

class CameraException(Exception):
    pass


class Camera:
    test_connection_process = None
    mmc = None

    fps = None
    last_time = None

    flatfield = None
    flatfield_preprocessed = None
    darkfield = None

    def __init__(self, memmap, config):
        # store memmap and config
        self.memmap = memmap
        self.config = config

        # store time (for fps calculation)
        self.last_time = time.time()

        # list of commands
        self.commandsCam = {"setExposure": self.setExposure,
                            "setGainValue": self.setGainValue,
                            "startContinuousSequenceAcquisition": self.startContinuousSequenceAcquisition,
                            "stopSequenceAcquisition": self.stopSequenceAcquisition,
                            "setBinning": self.setBinning,
                            "clearROI": self.clearROI,
                            "setROI": self.setROI,
                            "getROI": self.getROI,
                            "snapImage": self.snapImage,
                            "getImage": self.getImage,
                            "setProperty": self.setProperty,
                            "getProperty": self.getProperty,
                            "recordFlatField": self.recordFlatField,
                            "recordDarkField": self.recordDarkField,
                            }

        try:
            self.flatfield = np.load("flatfield.npy")
            self.updatePreprocessedFlatfield()
        except IOError:
            pass
        try:
            self.darkfield = np.load("darkfield.npy")
            self.updatePreprocessedFlatfield()
        except IOError:
            pass

    def sequencePaused(self):
        camera = self
        
        class SequencePaused:
            def __enter__(self):
                if camera.memmap.sequence:
                    camera.mmc.stopSequenceAcquisition()

            def __exit__(self, type, value, traceback):
                if camera.memmap.sequence:
                    camera.startContinuousSequenceAcquisition(camera.memmap.sequence, force=True)
        
        return SequencePaused()

    def cameraConnected(self):
        """ test if a connection to the camera is established """
        return self.mmc is not None

    def cameraConnectionAvailable(self):
        """ use an external script which tests if the camera is available
            using an external script has the advantage that in case of failure the main script doesn't have to be restarted
        """
        # print status
        print(self.test_connection_process,
              self.test_connection_process.poll() if self.test_connection_process is not None else "")
        # if no test process is running, start one
        if self.test_connection_process is None:
            self.test_connection_process = subprocess.Popen(
                [sys.executable, os.path.join(os.path.dirname(__file__), "TestCameraConnection.py"), self.config["Module"], self.config["Adapter"]])
            self.test_connection_process.start_time = time.time()
            return 0
        else:
            # if the process is finished or a timeout has occurred
            if self.test_connection_process.poll() is not None or time.time() - self.test_connection_process.start_time > 10:
                # test if the process was successful (return == 0) or if it has failed (return != 0)
                result = (self.test_connection_process.poll() == 0)
                # kill the process and reset the variable
                self.test_connection_process.kill()
                self.test_connection_process = None
                return result

    def connectToCamera(self, trayicon):
        """ try to connect to the camera. Normally this should not fail, as cameraConnectionAvailable has already tested
            if a connection is possible. """
        if self.mmc is not None:
            return
        logging.info("Connecting to camera ...")
        # try to connect to the camera and initialize the device
        try:
            self.mmc = MMCorePy.CMMCore()
            self.mmc.loadDevice('Camera', self.config["Module"], self.config["Adapter"])
            self.mmc.initializeAllDevices()
            self.mmc.setCameraDevice('Camera')
            logging.info("... done")
            # show a message
            trayicon.showMessage("Camera Connection", "Connected to camera.")
            # and initialize the camera settings
            self.cameraConnectionEstablished()
        # if not we have to restart the whole script
        except MMCorePy.CMMError as err:
            print("Restart?", err)
            logging.info("Could not connect to camera")
            trayicon.showMessage("No Camera Connection", "Could not connect to camera. Is it turned off?")
            time.sleep(2)
            restart()

    def cameraConnectionEstablished(self):
        """ after the camera has been connected reset the parameters according to memmap """
        sequence = self.memmap.sequence
        self.memmap.sequence = 0
        self.stopSequenceAcquisition()
        if 1:
            self.memmap.exposure = self.mmc.getExposure()
            self.memmap.gain = self.mmc.getProperty("Camera", self.config["GainProperty"])
            self.memmap.binning = self.mmc.getProperty("Camera", "Binning")[0]
            self.memmap.roi[:] = self.getROI()
        else:
            self.setExposure(self.memmap.exposure)
            self.setGainValue(max(self.memmap.gain, self.mmc.getPropertyLowerLimit("Camera", self.config["GainProperty"])))
            self.setBinning(self.memmap.binning)
            self.setROI(*self.memmap.roi)
        if self.config["Adapter"] == "LuCam":
            self.mmc.setProperty("Camera", "PixelType", "16bit-MONO")
        if sequence:
            self.startContinuousSequenceAcquisition(sequence)

    def recordFlatField(self, N):
        with self.sequencePaused():
            print(0)
            self.mmc.snapImage()
            image = self.mmc.getImage()
            dtype = image.dtype
            image = image.astype(float)
            for i in range(1, N):
                print(i)
                self.mmc.snapImage()
                image += self.mmc.getImage()
            self.flatfield = (image / N).astype(dtype)
            np.save("flatfield.npy", self.flatfield)
            self.updatePreprocessedFlatfield()

    def updatePreprocessedFlatfield(self):
        image = self.flatfield.astype(float)
        if self.darkfield is not None:
            self.flatfield_preprocessed = (image - self.darkfield) / np.mean(image - self.darkfield)
        else:
            self.flatfield_preprocessed = image / np.mean(image)

    def recordDarkField(self, N):
        with self.sequencePaused():
            print(0)
            self.mmc.snapImage()
            image = self.mmc.getImage()
            dtype = image.dtype
            image = image.astype(float)
            for i in range(1, N):
                print(i)
                self.mmc.snapImage()
                image += self.mmc.getImage()
            self.darkfield = (image/N).astype(dtype)
            np.save("darkfield.npy", self.darkfield)
            self.updatePreprocessedFlatfield()

    def applyFlatfield(self, im):
        if self.flatfield_preprocessed is not None:
            dtype = im.dtype
            x, y, dx, dy = self.memmap.roi
            if self.darkfield is not None:
                im = (im - self.darkfield[y:y+dy, x:x+dx]) / self.flatfield_preprocessed[y:y+dy, x:x+dx]
            else:
                im = im / self.flatfield_preprocessed[y:y+dy, x:x+dx]
            im[im > np.iinfo(dtype).max] = np.iinfo(dtype).max
            im[im < 0] = 0
            return im.astype(dtype)
        return im


    def updateFps(self):
        """ update the framerate with the new frame """
        # get the time since the last frame
        dt = time.time() - self.last_time
        # if no fps is given reset it with the current value
        if self.fps is None:
            self.fps = 1 / dt
        # if a fps is given, update it with a floating update
        else:
            a = np.exp(-dt)
            self.fps = a * self.fps + (1 - a) * 1 / dt
        # store the frame rate
        self.memmap.fps = self.fps
        # store the time of this update
        self.last_time = time.time()

    def sequenceStorage(self):
        # if the sequence is running and images are available
        if self.mmc.isSequenceRunning() and self.mmc.getRemainingImageCount() > 0:
            # get the image
            if self.popNextImage() is not None:
                self.updateFps()
                #print_revert("fps: %.2f" % self.fps)
                print("fps: %.2f" % self.fps)

    def call(self, function, *args):
        """ calls a camera function """
        # check if the camera is connected
        if self.mmc is None:
            raise CameraException("Camera not connected")
        # check if the function is valid
        if function not in self.commandsCam:
            raise CameraException(function, "unknown command")
        # execute the function
        return self.commandsCam[function](*args)

    """ Some camera functions which are overloaded """

    def snapImage(self):
        """ Records a single image """
        # stop sequence acquisition when snap image is used
        if self.memmap.sequence:
            self.stopSequenceAcquisition()
        # call snap image
        self.mmc.snapImage()

    def getImage(self):
        try:
            img = self.mmc.getImage()
        except:
            logging.info("ERROR recoding image")
        else:
            if self.config["FlipY"]:
                img = img[::-1, :]
            if self.config["FlipX"]:
                img = img[:, ::-1]
            self.memmap.saveToRingbuffer(self.applyFlatfield(img))
            return img.shape
        return None

    def popNextImage(self):
        try:
            img = self.mmc.popNextImage()
        except:
            logging.info("ERROR recoding image")
        else:
            if self.config["FlipY"]:
                img = img[::-1, :]
            if self.config["FlipX"]:
                img = img[:, ::-1]
            self.memmap.saveToRingbuffer(self.applyFlatfield(img))
            return img.shape
        return None

    def setProperty(self, device, prop, value):
        """ set the a property for a device """
        # find the memmap entry for the property to later set the current value
        for i in range(self.memmap.property_count):
            if self.memmap.properties[i].name == prop:
                prop_entry = self.memmap.properties[i]
                break
        # pause sequence while property is set
        with self.sequencePaused():
            self.mmc.setProperty(device, prop, value)
            # set the new value in the memmap
            prop_entry.value = value

    def getProperty(self, device, prop):
        """ get the a property for a device """
        return self.mmc.getProperty(device, prop)

    def getPropertyList(self, device):
        names = self.mmc.getDevicePropertyNames(device)
        properties = []
        for name in names:
            allowed_values = self.mmc.getAllowedPropertyValues(device, name)
            allowed_range = [self.mmc.getPropertyLowerLimit(device, name), self.mmc.getPropertyUpperLimit(device, name)]
            properties.append([name, allowed_values, allowed_range])

        return properties

    def setExposure(self, value):
        """ changes the exposure time """
        # ensure the exposure time is an integer
        value = float(value)
        logging.info("Set Exposure %f" % value)
        # set the exposure time while the sequence is paused
        with self.sequencePaused():
            self.mmc.setExposure(value)
        # store the exposure time in the memmap
        self.memmap.exposure = value

    def setGainValue(self, value):
        """ change the gain value """
        # ensure that the gain value is an integer
        value = int(value)
        logging.info("Set GainValue %d" % value)
        # change the gain value while the sequence is paused
        with self.sequencePaused():
            self.mmc.setProperty("Camera", self.config["GainProperty"], value)
        # store the gain value in the memmap
        self.memmap.gain = value

    def setBinning(self, value):
        """ set the binning of the camera """
        # accept an int or a string
        try:
            value = int(value)
            value = "%dx%d" % (value, value)
        except ValueError:
            pass
        value = str(value)
        # don't allow 0x0 binning
        if value == "0x0":
            value = "1x1"
        logging.info("Set Binning %s" % value)
        # change the binning state while the sequence is paused
        with self.sequencePaused():
            self.mmc.setProperty("Camera", "Binning", value)
        self.memmap.binning = value[0]

    def setROI(self, x, y, dx, dy):
        """ change the region of the camera to readout """
        # ensure that every value is an integer
        x, y, dx, dy = int(x), int(y), int(dx), int(dy)
        # if all is 0, reset roi
        if x == 0 and y == 0 and dx == 0 and dy == 0:
            return self.clearROI()
        # flip y
        if self.config["FlipY"]:
            y = self.config["Height"] - y - dy
        # adjust the roi while the sequence is paused
        with self.sequencePaused():
            self.mmc.setROI(x, y, dx, dy)
        # save the roi in the memmap
        self.memmap.roi[:] = self.getROI()

    def getROI(self):
        """ get the current roi """
        # get the roi from the camera
        x, y, dx, dy = self.mmc.getROI()
        print("ROI", x, y, dx, dy)
        # flit y if necessary
        if self.config["FlipY"]:
            y = self.config["Height"] - y - dy
        # return values
        return [x, y, dx, dy]

    def clearROI(self):
        """ clear the region of interest """
        # clear the roi while the sequence is paused
        with self.sequencePaused():
            self.mmc.clearROI()
        # store the roi in the memmap
        self.memmap.roi[:] = self.getROI()

    def startContinuousSequenceAcquisition(self, value, force=False):
        """ start a sequence acquisition """
        # if according to the memmap a sequence is running do nothing
        if self.memmap.sequence == value and not force:
            return None
        # stop the sequence
        if self.memmap.sequence:
            self.mmc.stopSequenceAcquisition()
        # reset the frame rate
        self.fps = None
        # store the sequence value in the memmap
        self.memmap.sequence = max(value, 1)
        return self.mmc.startContinuousSequenceAcquisition(value)

    def stopSequenceAcquisition(self):
        """ stop the sequence acquisition """
        # reset the sequence value in the memmap
        self.memmap.sequence = 0
        # stop the sequence
        return self.mmc.stopSequenceAcquisition()


class CameraServer(QtWidgets.QWidget):
    memmap = None
    current_command_index = 0

    def __init__(self, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.setWindowTitle('Camera Server')

        # read the config file
        self.config_file = os.path.join(os.path.dirname(__file__), "Microscope_Config.txt")
        self.config = dict(Coupler=1, MicroscopeName="Microscope", PixelSize=6.45, FlipY=False)
        if os.path.exists(self.config_file):
            try:
                execfile(self.config_file, globals(), self.config)
            except NameError:
                exec(self.config_file, globals(), self.config)
        print("config", self.config_file, self.config)

        # create the memmap
        self.createMemMap()

        # initialize the camera
        self.camera = Camera(self.memmap, self.config)

        # create the context menu for the tray icon
        self.trayIconMenu = QtWidgets.QMenu(self)

        showLogAction = QtWidgets.QAction("Show Log", self)
        showLogAction.triggered.connect(self.trayActionShowLog)
        self.trayIconMenu.addAction(showLogAction)
        self.log_process = None

        quitAction = QtWidgets.QAction("Quit", self)
        quitAction.triggered.connect(self.trayActionClose)
        self.trayIconMenu.addAction(quitAction)

        # initialize the tray icon
        self.trayIcon = QtWidgets.QSystemTrayIcon(self)
        self.trayIcon.setToolTip("Camera Server")
        self.trayIcon.setIcon(QtGui.QIcon("icons/CameraServer.ico"))
        self.trayIcon.setContextMenu(self.trayIconMenu)
        self.trayIcon.show()

        # kill the old instance
        if killOldInstance(__file__, "camera_server", "camera_server_noconsole"):
            self.trayIcon.showMessage("Restart Camera Server", "Shut down old server and start new one.")
            logging.info("Killed old server")
            time.sleep(1)

        self.last_time = time.time()
        self.fps = None

        # start server loop
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.loop)
        self.timer.start(1)
        logging.info("serving ...")

    def trayActionShowLog(self):
        # kill the old log view
        if self.log_process is not None and self.log_process.pid in psutil.pids():
            self.log_process.kill()
        # start a new log view
        self.log_process = subprocess.Popen([sys.executable, "LogView.py", getCamLogFile(), "Camera Log"])

    def trayActionClose(self):
        # kill the old log view
        if self.log_process is not None and self.log_process.pid in psutil.pids():
            self.log_process.kill()
        # hide the icon and terminate the script
        self.trayIcon.hide()
        sys.exit()

    def closeEvent(self, event):
        self.trayIcon.hide()

    def createMemMap(self):
        logging.info("Create Mem Map ...")

        self.memmap = CamMemMap(self.config["Height"], self.config["Width"])

        if self.memmap.isNewMemmap():
            print("new memmap")
            self.memmap.current_index = 0
            self.memmap.sequence = 0
            self.memmap.exposure = 5
            self.memmap.binning = 1
            self.memmap.roi[:] = [0, 0, self.memmap.width, self.memmap.height]
            self.memmap.gain = 0
            self.memmap.blocking_process = 0
            for i in range(len(self.memmap.commands)):
                command = self.memmap.commands[i]
                with self.memmap.editLock:
                    command.index = i
                    command.state = STATE_Empty
                    command.function = ""
                    command.args = "[]"
                    command.error = 0
                    command.response = ""

        self.memmap.current_index = 0
        self.memmap.current_command_index = 0

        logging.info("... done")

    def setError(self, command, text):
        """ set the status of the command to error with text as error message """
        with self.memmap.editLock:
            command.status = STATE_Received
            command.error = 1
            command.response = "Error: " + text

    def setResponse(self, command, res):
        """ set the status of the command as received with res as the result """
        with self.memmap.editLock:
            command.status = STATE_Received
            command.error = 0
            command.response = serialize(res)

    def processCommand(self, command):

        print(datetime.now(), "command", command.function)
        logging.info("Received: %s", command.function)
        # change the status of the command
        with self.memmap.editLock:
            command.status = STATE_Written
        # get command function and args
        function, args = command.function, command.args
        try:
            # try to split args and kwargs
            args = deserialize(args)
            # try to call the function
            result = self.camera.call(function, *args)
        except MMCorePy.CMMError as err:
            print(err.__str__())
            if err.__str__().startswith('Error in device "Camera"'):
                self.setError(command, err.__str__() + traceback.format_exc() + "\nrestarting camera server")
                print("Restart Server")
                restart()
            else:
                self.setError(command, err.__str__() + traceback.format_exc())
                return
        except Exception as err:
            # set the return of the command to the error code
            self.setError(command, err.__str__() + traceback.format_exc())
        else:
            # set the response of the command to the return value
            self.setResponse(command, result)
        logging.info("done")
        return

    def loop(self):
        while self.memmap.current_command_index > self.current_command_index:
            self.current_command_index = self.current_command_index + 1
            self.processCommand(self.memmap.commands[self.current_command_index % len(self.memmap.commands)])

        if not self.camera.cameraConnected():
            if self.camera.cameraConnectionAvailable():
                self.camera.connectToCamera(self.trayIcon)
                # list properties
                names = self.camera.mmc.getDevicePropertyNames("Camera")
                # properties are set to 0? then query them
                if self.memmap.property_count == 0:
                    self.memmap.property_count = 0
                    for i, name in enumerate(names):
                        self.memmap.properties[i].name = name
                        self.memmap.properties[i].allowed_values = serialize(self.camera.mmc.getAllowedPropertyValues("Camera", name))
                        self.memmap.properties[i].min = self.camera.mmc.getPropertyLowerLimit("Camera", name)
                        self.memmap.properties[i].max = self.camera.mmc.getPropertyUpperLimit("Camera", name)
                        self.memmap.properties[i].value = self.camera.mmc.getProperty("Camera", name)
                        self.memmap.property_count = self.memmap.property_count + 1
                # if not, set them
                else:
                    for i in range(self.memmap.property_count):
                        prop = self.memmap.properties[i]
                        try:
                            self.camera.mmc.setProperty("Camera", prop.name, prop.value)
                        except:
                            prop.value = self.camera.mmc.getProperty("Camera", prop.name)

                # framerate-hack: initially change ROI twice to get higher framerate
                x, y, dx, dy = self.camera.getROI()
                self.camera.setROI(x, y, dx, int(dy / 8))
                self.camera.setROI(x, y, dx, dy)
            else:
                time.sleep(0.5)
                return

        self.camera.sequenceStorage()

        time.sleep(0.001)


def main():
    global MMCorePy
    import MMCorePy
    app = QtWidgets.QApplication(sys.argv)
    window = CameraServer()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
