from __future__ import print_function, division
import sys
import time
import socket
import numpy as np
from pathlib import Path
import tifffile
from typing import Tuple

from leica_microscope.includes.comport import find_mic_port, send_command_and_wait, FlowError
from leica_microscope.camera import Camera
from leica_microscope.includes.config import getConfig, writeConfigChange
from leica_microscope.includes.helper_functions import format_partial, format_with_default


class Nowait:
    def __init__(self, mic):
        self.mic = mic

    def __enter__(self):
        self.mic.wait = False

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.mic.wait = True

    def __call__(self, *args, **kwargs):
        return self


class Timeit:
    def __init__(self, name):
        self.name = name

    def __enter__(self):
        self.time = time.time()

    def __exit__(self, exc_type, exc_val, exc_tb):
        print("TIMEIT", self.name, time.time()-self.time)


class NoMicroscopeFound(Exception):
    pass


class Microscope:
    MODE_TL_BF = 0
    MODE_TL_PH = 1
    MODE_TL_DF = 2
    MODE_TL_DIC = 3
    MODE_TL_POL = 4
    MODE_IL_BF = 5
    MODE_IL_OBL = 6
    MODE_IL_DF = 7
    MODE_IL_DIC = 8
    MODE_IL_POL = 9
    MODE_FLUO = 10
    MODE_FLUO_PH = 11
    MODE_FLUO_DIC = 12
    MODE_BF_BF = 13
    mode_ids = {"TL_BF": 0, "BF": 0, "TL_PH": 1, "PH": 1, "TL_DF": 2, "DF": 2, "TL_DIC": 3, "DIC": 3, "TL_POL": 4,
                "POL": 4,
                "IL_BF": 5, "IL_OBL": 6, "IL_DF": 7, "IL_DIC": 8, "IL_POL": 9, "FLUO": 10, "FLUO_PH": 11,
                "FLUO_DIC": 12, "BF_BF": 13,
                "FLUO1": [10, 1], "FLUO2": [10, 2], "FLUO3": [10, 3], "FLUO4": [10, 4], "FLUO5": [10, 5],
                "FLUO6": [10, 6]}

    calibrated_proj_speed = None
    iteration_time = None

    def __init__(self):
        self.config = getConfig(dict(microscope_name="Mic",
                                     coupler=1,
                                     port=None))

        self.port = find_mic_port(self.config["port"])
        if self.port is None:
            raise NoMicroscopeFound("No microscope was found, check if the microscope is running.")
        writeConfigChange(self.config, "port", '"'+self.port+'"')

        self.cam = Camera()

        self.wait = True
        self.nowait = Nowait(self)
        self.verbose = False

        self.properties = self.getAllProperties()
        self.magnification, self.numerical_aperture, self.objective, self.mode, self.channel = \
                self.send_command_and_wait([
                    "76033 a 1",
                    "76033 a 2",
                    "76033 a 3",
                    "70028",
                    "78023",
                ],
                    [
                        [None, None, int],
                        [None, None, float],
                        [None, None, int],
                        int,
                        [None, str],
                    ])

    def mode_id_to_name(self, id):
        for k, v in self.mode_ids.items():
            if v == id:
                return k

    def send_command_and_wait(self, command, format=None):
        # if we don't want to wait and we do not expect a return value, just send the command
        # if not, send the command and wait for the answer
        wait = self.wait is True or format is not None
        return send_command_and_wait(command, self.port, format, verbose=self.verbose, wait=wait)

    def wait_for_stop(self, function, timeout=5):
        start_time = time.time()
        while self.wait and np.any(function()) and time.time() - start_time < timeout:
            time.sleep(0.0001)

    def getAllProperties(self):
        commands = []
        formats = []
        names = []
        def addCommand(cmd, format, name):
            commands.append(cmd)
            formats.append(format)
            names.append(name)

        # objectives
        for i in range(6):
            addCommand("76033 %d 1" % (i+1), [None, None, str], "objectives")
        addCommand("76023", [int], "current_objective")
        # filters
        for i in range(6):
            addCommand("78027 %d" % (i+1), [None, str], "filters")
        addCommand("78023", [int], "current_filter")
        # possible modes
        addCommand("70026", [str], "modes")
        # mode
        addCommand("70028", [int], "current_mode")
        # lamp
        addCommand("77021", [int], "intensity")
        # aperture
        addCommand("84023", [int], "aperture")
        # field
        addCommand("94023", [int], "field")
        # shutter
        addCommand("77033", [int, int], "shutter")
        # position
        addCommand("72023", [int], "pos")
        addCommand("73023", [int], "pos")
        addCommand("71023", [int], "pos")
        # speed
        addCommand("72033", [int], "speed")
        addCommand("73033", [int], "speed")
        addCommand("71033", [int], "speed")
        # ramp
        addCommand("72031", [int], "ramp")
        addCommand("73031", [int], "ramp")
        addCommand("71031", [int], "ramp")
        # resolution
        addCommand("72034", [float], "resolution")
        addCommand("73034", [float], "resolution")
        addCommand("71042", [float], "resolution")
        # get the answer to all these commands
        result = self.send_command_and_wait(commands, formats)
        propertes = {}
        for v, n in zip(result, names):
            if n not in propertes:
                propertes[n] = v
            else:
                if isinstance(propertes[n], list):
                    propertes[n].append(v)
                else:
                    propertes[n] = [propertes[n], v]

        # the modes response is a string with 0's and 1's corresponding which modes are enabled
        all_modes = propertes["modes"]
        propertes["modes"] = []
        # we here convert it to a list of names
        for i, m in enumerate(all_modes[::-1]):
            if m == "1":
                for k, v in self.mode_ids.items():
                    if v == i:
                        propertes["modes"].append(k)
                        break

        self.properties = propertes
        return propertes

    """ helpers """

    def loadPositions(self, filename) -> np.ndarray:
        positions = np.loadtxt(filename, dtype=int)
        if len(positions.shape) == 1:
            positions = np.array([positions])
        return positions

    def getDefaultFilename(self, folder):
        save_filename = r"{datetime}_{system}_rep{repetition}_pos{pos}_x{x}_y{y}_mode{mode}_z{z}.tif"
        # if the timestamp is defined by the command line arguments, take that
        # this is used to ensure that the config and the recode file have the same timestamp as the images
        for arg in sys.argv:
            if arg.startswith("--timestamp="):
                timestamp = arg[len("--timestamp="):]
                break
        # if not take a current timestamp
        else:
            timestamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
        save_filename = format_partial(save_filename, datetime=timestamp, system=self.getMicroscopeName())
        return str(Path(folder) / save_filename)

    """ positions """

    def getPos(self):
        return np.array(self.send_command_and_wait(["72023", "73023", "71023"], [int, int, int]))

    def setPos(self, pos):
        x, y, z = pos
        try:
            self.send_command_and_wait(["72022 %d" % x, "73022 %d" % y, "71022 %d" % z])
        except FlowError as err:
            print("FlowError occurred, try to reinit", err.device)
            self.send_command_and_wait(err.device+"020")
            self.send_command_and_wait(["72022 %d" % x, "73022 %d" % y, "71022 %d" % z])
        # wait until the microscope has truly reached the position
        self.wait_for_stop(self.getMoving)

    def getMoving(self) -> np.array:
        return np.array(self.send_command_and_wait(["72004", "73004", "71004"], [int, int, int])).astype(bool)

    def getXMoving(self) -> bool:
        return self.send_command_and_wait("72004", int) == 1

    def getYMoving(self) -> bool:
        return self.send_command_and_wait("73004", int) == 1

    def getZMoving(self) -> bool:
        return self.send_command_and_wait("71004", int) == 1

    def getXPos(self):
        return self.send_command_and_wait("72023", int)

    def setXPos(self, x: int):
        try:
            self.send_command_and_wait("72022 %d" % x)
        except FlowError:
            # in case a flow error occurs, maybe a reset can help
            self.send_command_and_wait("71020")
            self.send_command_and_wait("72022 %d" % x)
        # wait until the microscope has truly reached the position
        self.wait_for_stop(self.getXMoving)

    def getYPos(self):
        return self.send_command_and_wait("73023", int)

    def setYPos(self, y: int):
        try:
            self.send_command_and_wait("73022 %d" % y)
        except FlowError:
            # in case a flow error occurs, maybe a reset can help
            self.send_command_and_wait("71020")
            self.send_command_and_wait("73022 %d" % y)
        # wait until the microscope has truly reached the position
        self.wait_for_stop(self.getYMoving)

    def getZPos(self):
        return self.send_command_and_wait("71023", int)

    def setZPos(self, z):
        try:
            self.send_command_and_wait("71022 %d" % z)
        except FlowError:
            # in case a flow error occurs, maybe a reset can help
            self.send_command_and_wait("71020")
            self.send_command_and_wait("71022 %d" % z)
        # wait until the microscope has truly reached the position
        self.wait_for_stop(self.getZMoving)

    """ speed adjustments """

    def getXSpeed(self) -> int:
        return self.send_command_and_wait("72033", int)

    def setXSpeed(self, speed: int):
        self.send_command_and_wait("72032 %d" % speed)

    def getYSpeed(self) -> int:
        return self.send_command_and_wait("73033", int)

    def setYSpeed(self, speed: int):
        self.send_command_and_wait("73032 %d" % speed)

    def getZSpeed(self) -> int:
        return self.send_command_and_wait("71033", int)

    def setZSpeed(self, speed: int):
        self.send_command_and_wait("71032 %d" % speed)

    def getXSpeedMax(self) -> int:
        return self.send_command_and_wait("72059", int)

    def getYSpeedMax(self) -> int:
        return self.send_command_and_wait("73059", int)

    def getZSpeedMax(self) -> int:
        return self.send_command_and_wait("71059", int)

    def getXRange(self) -> Tuple[int, int]:
        return self.send_command_and_wait(["72028", "72029"], [int, int])

    def getYRange(self) -> Tuple[int, int]:
        return self.send_command_and_wait(["73028", "73029"], [int, int])

    def getZRange(self) -> Tuple[int, int]:
        return self.send_command_and_wait(["71028", "71056"], [int, int])

    """ resolutions"""

    def getXResolution(self) -> float:
        return self.send_command_and_wait("72034", float)

    def getYResolution(self) -> float:
        return self.send_command_and_wait("73034", float)

    def getZResolution(self) -> float:
        return self.send_command_and_wait("71042", float)

    """ main microscope """

    def getLampIntensity(self) -> int:
        return self.send_command_and_wait("77021", int)

    def setLampIntensity(self, intensity: int):
        self.send_command_and_wait("77020 %d" % intensity)

    def setApertureTL(self, intensity: int):
        self.send_command_and_wait("84022 %d" % intensity)

    def setFieldTL(self, intensity: int):
        self.send_command_and_wait("94022 %d" % intensity)

    def getMode(self) -> Tuple[int, Tuple[int, str]]:
        return self.send_command_and_wait(["70028", "78023"], [int, [int, str]])

    def setMode(self, mode, fluo_channel=None):
        # if the mode is a string, convert it to an id
        if isinstance(mode, str):
            mode = self.mode_ids[mode.upper()]

        # if both parameters are as a list in the mode
        if isinstance(mode, (list, tuple)) and fluo_channel is None:
            mode, fluo_channel = mode

        # if there is also a fluo channel, set mode and fluochannel in parallel
        if fluo_channel is not None:
            self.send_command_and_wait(["70029 %d" % mode, "78022 %d" % fluo_channel])
            self.mode, self.channel = self.send_command_and_wait(["70028", "78023"], [int, [int, str]])
        # if not, just set the mode
        else:
            self.send_command_and_wait("70029 %d" % mode)
            self.mode = self.send_command_and_wait("70028", int)

    def setShutter(self, shutter_open: int):
        self.send_command_and_wait("77032 1 %d" % int(shutter_open))

    """ objective properties """

    def getMagnification(self):
        return self.send_command_and_wait("76033 a 1", [None, None, int])

    def getObjectiveIndex(self):
        return self.send_command_and_wait("76023", int)

    def getNumericalAperture(self):
        return self.send_command_and_wait("76033 a 2", [None, None, float])

    def getObjective(self):
        return self.send_command_and_wait("76033 a 3", [None, None, str])

    def setObjective(self, pos):
        return self.send_command_and_wait("76022 %d" % pos)

    """"""

    def getEffectiveMagnification(self):
        return self.getMagnification() * self.config["coupler"]

    def getCoupler(self):
        return self.config["coupler"]

    def setCoupler(self, value):
        self.config["coupler"] = value
        writeConfigChange(self.config, "coupler", "%.1f" % value)

    def getMicroscopeName(self):
        return self.config["microscope_name"]

    def getMetadata(self):
        self.metadata = {}
        self.metadata["Coupler"] = float(self.config["coupler"])

        self.metadata["Mode"] = self.mode
        self.metadata["Channel"] = self.channel

        # self.metadata["StagePosition"] = self.memmap.stage_pos.tolist()

        # Objective
        self.metadata["Magnification"] = self.magnification
        self.metadata["NumericalAperture"] = self.numerical_aperture
        self.metadata["Objective"] = self.objective

        # System
        self.metadata["ComputerName"] = socket.gethostname()
        self.metadata["MicroscopeName"] = self.config["microscope_name"]
        self.metadata["Time"] = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-%06d" % (
                    (time.time() - int(time.time())) * 1e6)
        return self.metadata

    """ image saveing """

    def saveImage(self, name, img, add_metadata=None):
        """ save an image with meta data """
        # ensure that the folder exists
        name = Path(name)
        name.parent.mkdir(exist_ok=True)
        # gather the metadata
        metadata = self.getMetadata()
        metadata.update(self.cam.getMetadata())
        if add_metadata is not None:
            metadata.update(add_metadata)
        # and save the file
        tifffile.imsave(name, img, metadata=metadata)

    """ set multiple things at once """

    def setProperties(self, mode=None, exposure=None, gain=None, intensity=None, binning=None):
        """ microscope things """
        if mode is not None:
            self.setMode(mode)
        if intensity is not None:
            self.setLampIntensity(intensity)
        """ camera properties """
        if exposure is not None:
            self.cam.setExposure(exposure)
        if gain is not None:
            self.cam.setGain(gain)
        if binning is not None:
            self.cam.setBinning(binning)

    """ recoding functions """

    def rec_image(self, filename):
        self.saveImage(format_with_default(filename), self.cam.getImage())

    def rec_stack(self, filename, n_below=50, n_above=250, slice_thickness_um=5, fast_recording=False, save_projection=False):
        slice_thickness_um = slice_thickness_um
        slice_start = n_below
        slice_stop = n_above

        # ensure that stack is always recorded from bottom to top
        if slice_start > slice_stop:
            slice_start, slice_stop = (slice_stop, slice_start)

        # convert thickness to steps
        slice_thickness_steps = int(slice_thickness_um / self.getZResolution())

        # convert start/end to steps
        z_start = slice_start * slice_thickness_steps
        z_stop = (slice_stop + 2) * slice_thickness_steps
        n_slices = np.abs(slice_stop - slice_start)

        # get position and move to start
        z = self.getZPos()

        # either move to every positions separately (precise stack) or move continuously while recording images
        if not fast_recording:
            buffer = self.recordPreciseStackToBuffer(z, z_start, z_stop, n_slices)
        else:
            buffer = self.recordFastStackToBuffer(z, z_start, z_stop, n_slices)

        if not save_projection:
            # save single images
            for i in range(n_slices):
                self.saveImage(format_with_default(filename, z=i), buffer[i])
        else:
            # save projection
            dtype = np.uint8
            if n_slices > 256:
                dtype = np.uint16
            self.saveImage(format_with_default(filename, z='MinProj'), np.min(buffer, axis=0))
            self.saveImage(format_with_default(filename, z='MaxProj'), np.max(buffer, axis=0))
            self.saveImage(format_with_default(filename, z='MinIndices{}'.format(n_slices)), np.argmin(buffer, axis=0).astype(dtype))
            self.saveImage(format_with_default(filename, z='MaxIndices{}'.format(n_slices)), np.argmax(buffer, axis=0).astype(dtype))

    def rec_projection(self, filename, n_below=50, n_above=250, slice_thickness_um=5, fast_recording=True, save_projection=True):
        return self.rec_stack(filename, n_below, n_above, slice_thickness_um, fast_recording, save_projection)

    def recordPreciseStackToBuffer(self, z, z_start, z_stop, n_slices):
        slice_thickness_steps = (z_stop-z_start) // n_slices
        # prepare the video buffer (a numpy array the size to hold all images)
        buffer = self.cam.getVideoBuffer(n_slices)

        with self.cam.fast_recording:
            for i in range(n_slices):
                self.setZPos(z + z_start + slice_thickness_steps * i)
                buffer[i] = self.cam.getImage()

        # reset position
        self.setZPos(z)

        return buffer

    def recordFastStackToBuffer(self, z, z_start, z_stop, n_slices):
        # Calculate the approximate speed to get the desired number of images using the current framerate
        if self.calibrated_proj_speed is None:
            fps = self.cam.getFramerate()

            self.setZSpeed(88200)
            current_z_speed = self.getZSpeed()

            self.setZPos(z + z_start)
            t = time.time()
            self.setZPos(z + z_stop)
            duration_drive = time.time() - t
            duration_take_images = n_slices / fps

            self.calibrated_proj_speed = int(duration_drive / duration_take_images * current_z_speed)

        # move to start
        self.setZPos(z + z_start)

        # set the z speed so that the z-drive takes exactly the same time to travel the z distance as the
        # camera takes to record the images
        self.setZSpeed(self.calibrated_proj_speed)

        # prepare the video buffer (a numpy array the size to hold all images)
        buffer = self.cam.getVideoBuffer(n_slices)
        # move to end (don't wait for command to finish) and record
        with self.nowait:
            self.setZPos(z + z_stop)
            self.cam.getVideo(buffer)

        # reset speed and position
        self.setZSpeed(8820000)
        self.setZPos(z)

        return buffer

    """ time keeping """
    def waitSinceLast(self, wait_time: float):
        if self.iteration_time is not None and time.time() - self.iteration_time < wait_time:
            time.sleep(wait_time - (time.time() - self.iteration_time))
        self.iteration_time = wait_time


