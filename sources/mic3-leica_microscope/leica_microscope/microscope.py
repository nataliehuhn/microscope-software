import sys
import time
import socket
import numpy as np
from pathlib import Path
import tifffile
from typing import Tuple, Union

from leica_microscope.includes.comport import find_mic_port, send_command_and_wait, FlowError
from leica_microscope.camera import Camera
from leica_microscope.streamer import MemmapWriter
from leica_microscope.includes.config import getConfig, writeConfigChange
from leica_microscope.includes.helper_functions import format_partial, format_with_default, formatByteNumber


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
    first_iteration_time = None

    used_disk_space = 0

    def __init__(self, no_camera=False, no_init=False):
        self.config = getConfig(dict(microscope_name="Mic",
                                     coupler=1,
                                     port=None,
                                     stage_min_x=0,
                                     stage_max_x=26010000,
                                     stage_min_y=0,
                                     stage_max_y=17000000,
                                     stage_flip_x=False,
                                     stage_flip_y=False))

        self.port = find_mic_port(self.config["port"])
        if self.port is None:
            raise NoMicroscopeFound("No microscope was found, check if the microscope is running.")
        writeConfigChange(self.config, "port", '"'+self.port+'"')

        if not no_camera:
            self.cam = Camera()
            self.memmap_writer = MemmapWriter(self.cam)
        else:
            self.cam = None

        self.wait = True
        self.nowait = Nowait(self)
        self.verbose = False

        if no_init is True:
            return

        with self.nowait:
            # set the range of the stage according to the config
            self.send_command_and_wait(f"72026 {self.config['stage_min_x']}")
            self.send_command_and_wait(f"72027 {self.config['stage_max_x']}")
            self.send_command_and_wait(f"73026 {self.config['stage_min_y']}")
            self.send_command_and_wait(f"73027 {self.config['stage_max_y']}")

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

    def getAllProperties(self) -> dict:
        """ Get a dictionary of all important property values of the microscope. """
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
        # try again if nothing was returned...
        if result is None:
            result = self.send_command_and_wait(commands, formats)

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

        x, y, z = propertes["pos"]
        propertes["pos"] = [self.processXPos(x), self.processYPos(y), z]

        self.properties = propertes
        return propertes

    """ helpers """

    def loadPositions(self, filename: Union[str, Path]) -> np.ndarray:
        """ Load a positions file Nx3 of N positions. """
        positions = np.loadtxt(filename, dtype=int)
        if len(positions.shape) == 1:
            positions = np.array([positions])
        return positions

    def getDefaultFilename(self, folder: Union[str, Path]) -> str:
        """ Get a default filename with placeholders for datetime, system, rep, pos, x, y, mode, z."""
        save_filename = r"{datetime}_{system}_rep{repetition:03}_pos{pos:02}_x{x:02}_y{y:02}_mode{mode}_z{z}.tif"
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

        Path(folder).mkdir(exist_ok=True)

        return str(Path(folder) / save_filename)

    """ positions """

    def getPos(self) -> np.ndarray:
        """ Get the XYZ position in steps. """
        x, y, z = self.send_command_and_wait(["72023", "73023", "71023"], [int, int, int])
        x = self.processXPos(x)
        y = self.processYPos(y)
        return np.array([x, y, z])

    def setPos(self, pos):
        """ Set the XYZ position in steps. """
        for i in range(3):
            try:
                x, y, z = pos
                x = self.processXPos(x)
                y = self.processYPos(y)
                # wait until the microscope has truly reached the position
                self.wait_for_stop(self.getMoving)
                try:
                    self.send_command_and_wait(["72022 %d" % x, "73022 %d" % y, "71022 %d" % z])
                except FlowError as err:
                    print("FlowError occurred, try to reinit", err.device)
                    self.send_command_and_wait(err.device+"020")
                    self.send_command_and_wait(["72022 %d" % x, "73022 %d" % y, "71022 %d" % z])
                # wait until the microscope has truly reached the position
                self.wait_for_stop(self.getMoving)
                # get the new position
                new_pos = self.getPos()
                print("pos", pos, "new_pos", new_pos)
                # check if the new position is the target position
                if np.all(pos != new_pos):
                    print("not equal")
                    # try again :-(
                    continue
                # if we have arrived stop the loop
                break
            # some flow error inbetween? well we nevertheless try again
            except FlowError as err:
                print(err, file=sys.stderr)
                time.sleep(1)

    def setXYPos(self, x, y):
        """ Set the XY position in steps. """
        x = self.processXPos(x)
        y = self.processYPos(y)
        try:
            self.send_command_and_wait(["72022 %d" % x, "73022 %d" % y])
        except FlowError as err:
            print("FlowError occurred, try to reinit", err.device)
            self.send_command_and_wait(err.device+"020")
            self.send_command_and_wait(["72022 %d" % x, "73022 %d" % y])
        # wait until the microscope has truly reached the position
        self.wait_for_stop(self.getMoving)

    def getMoving(self) -> np.array:
        """ Get the moving state for XYZ. """
        return np.array(self.send_command_and_wait(["72004", "73004", "71004"], [int, int, int])).astype(bool)

    def getXMoving(self) -> bool:
        """ Get whether the x stage is moving. """
        return self.send_command_and_wait("72004", int) == 1

    def getYMoving(self) -> bool:
        """ Get whether the y stage is moving. """
        return self.send_command_and_wait("73004", int) == 1

    def getZMoving(self) -> bool:
        """ Get whether the z drive is moving. """
        return self.send_command_and_wait("71004", int) == 1

    def getXPos(self) -> int:
        """ Get the x position in steps. """
        return self.processXPos(self.send_command_and_wait("72023", int))

    def setXPos(self, x: int):
        """ Set the x position in steps. """
        x = self.processXPos(x)
        try:
            self.send_command_and_wait("72022 %d" % x)
        except FlowError:
            # wait for the x drive to finish its last command before we set a new z position
            while self.getXMoving():
                pass
            try:
                self.send_command_and_wait("72022 %d" % x)
            except FlowError:
                # in case a flow error occurs, maybe a reset can help
                self.send_command_and_wait("72020")
                self.send_command_and_wait("72022 %d" % x)

        # wait until the microscope has truly reached the position
        self.wait_for_stop(self.getXMoving)

    def getYPos(self) -> int:
        """ Get the y position in steps. """
        return self.processYPos(self.send_command_and_wait("73023", int))

    def setYPos(self, y: int):
        """ Set the y position in steps. """
        y = self.processYPos(y)
        try:
            self.send_command_and_wait("73022 %d" % y)
        except FlowError:
            # wait for the z drive to finish its last command before we set a new z position
            while self.getYMoving():
                pass
            try:
                self.send_command_and_wait("73022 %d" % y)
            except FlowError:
                # in case a flow error occurs, maybe a reset can help
                self.send_command_and_wait("73020")
                self.send_command_and_wait("73022 %d" % y)

        # wait until the microscope has truly reached the position
        self.wait_for_stop(self.getYMoving)

    def getZPos(self) -> int:
        """ Get the z position in steps. """
        return self.send_command_and_wait("71023", int)

    def setZPos(self, z: int):
        """ Set the z position in steps. """
        for i in range(3):
            try:
                self.send_command_and_wait("71022 %d" % z)
            except FlowError:
                # wait for the z drive to finish its last command before we set a new z position
                while self.getZMoving():
                    pass
                try:
                    self.send_command_and_wait("71022 %d" % z)
                except FlowError:
                    # in case a flow error occurs, maybe a reset can help
                    self.send_command_and_wait("71020")
                    self.send_command_and_wait("71022 %d" % z)

            # wait until the microscope has truly reached the position
            self.wait_for_stop(self.getZMoving)

            if self.wait:
                new_z = self.getZPos()

                # check if the new position is the target position
                if z != new_z:
                    print("not equal", z, new_z)
                    # try again :-(
                    continue
            # we are done
            break

    def processXPos(self, x):
        if self.config["stage_flip_x"] is True:
            x = self.config["stage_max_x"]-x
        return x

    def processYPos(self, y):
        if self.config["stage_flip_y"] is True:
            y = self.config["stage_max_y"]-y
        return y

    """ speed adjustments """

    def getXSpeed(self) -> int:
        """ Get the speed of the x stage. """
        return self.send_command_and_wait("72033", int)

    def setXSpeed(self, speed: int):
        """ Set the speed of the x stage. """
        try:
            self.send_command_and_wait("72032 %d" % speed)
        except FlowError:
            while self.getXMoving():
                pass
            self.send_command_and_wait("72032 %d" % speed)

    def getYSpeed(self) -> int:
        """ Get the speed of the y stage. """
        return self.send_command_and_wait("73033", int)

    def setYSpeed(self, speed: int):
        """ Set the speed of the y stage. """
        try:
            self.send_command_and_wait("73032 %d" % speed)
        except FlowError:
            while self.getYMoving():
                pass
            self.send_command_and_wait("73032 %d" % speed)

    def getZSpeed(self) -> int:
        """ Get the speed of the z stage. """
        return self.send_command_and_wait("71033", int)

    def setZSpeed(self, speed: int):
        """ Set the speed of the z stage. """
        try:
            self.send_command_and_wait("71032 %d" % speed)
        except FlowError:
            while self.getZMoving():
                pass
            self.send_command_and_wait("71032 %d" % speed)

    def getXSpeedMax(self) -> int:
        """ Get the maximal speed of the x stage. """
        return self.send_command_and_wait("72059", int)

    def getYSpeedMax(self) -> int:
        """ Get the maximal speed of the y stage. """
        return self.send_command_and_wait("73059", int)

    def getZSpeedMax(self) -> int:
        """ Get the maximal speed of the z stage. """
        return self.send_command_and_wait("71059", int)

    def getXRange(self) -> Tuple[int, int]:
        """ Get the min and max position of the x stage. """
        return self.send_command_and_wait(["72028", "72029"], [int, int])

    def getYRange(self) -> Tuple[int, int]:
        """ Get the min and max position of the y stage. """
        return self.send_command_and_wait(["73028", "73029"], [int, int])

    def getZRange(self) -> Tuple[int, int]:
        """ Get the min and max position of the z stage. """
        return self.send_command_and_wait(["71028", "71056"], [int, int])

    """ resolutions"""

    def getXResolution(self) -> float:
        """ Get the resolution, e.g. steps to micrometer, of the x stage. """
        return self.send_command_and_wait("72034", float)

    def getYResolution(self) -> float:
        """ Get the resolution, e.g. steps to micrometer, of the y stage. """
        return self.send_command_and_wait("73034", float)

    def getZResolution(self) -> float:
        """ Get the resolution, e.g. steps to micrometer, of the z stage. """
        return self.send_command_and_wait("71042", float)

    """ main microscope """

    def getLampIntensity(self) -> int:
        """ Get the intensity of the lamp. """
        return self.send_command_and_wait("77021", int)

    def setLampIntensity(self, intensity: int):
        """ Set the intensity of the lamp. """
        self.send_command_and_wait("77020 %d" % intensity)

    def setApertureTL(self, intensity: int):
        """ Set the aperture. """
        self.send_command_and_wait("84022 %d" % intensity)

    def setFieldTL(self, intensity: int):
        """ Set the field diaphragm. """
        self.send_command_and_wait("94022 %d" % intensity)

    def isFluo(self) -> bool:
        """ Check whether the current mode is the fluo mode. """
        return self.send_command_and_wait("70028", int) == self.MODE_FLUO

    def getMode(self) -> Tuple[int, Tuple[int, str]]:
        """ Get the current mode. """
        return self.send_command_and_wait(["70028", "78023"], [int, [int, str]])

    def setMode(self, mode, fluo_channel=None):
        """ Set the mode. """
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
            # if target mode is POL, switch to BF first, otherwise a switch from
            # from FLUO to POL will leave some filter in the light path
            if mode == 4:
                self.send_command_and_wait("70029 %d" % self.mode_ids['BF'])
            self.send_command_and_wait("70029 %d" % mode)
            self.mode = self.send_command_and_wait("70028", int)

    def setShutter(self, shutter_open: int):
        """ Set the shutter to open or closed. """
        self.send_command_and_wait("77032 1 %d" % int(shutter_open))

    """ objective properties """

    def getMagnification(self) -> int:
        """ Get the magnification of the current objective. """
        return self.send_command_and_wait("76033 a 1", [None, None, int])

    def getObjectiveIndex(self) -> int:
        """ Get the index of the current objective. """
        return self.send_command_and_wait("76023", int)

    def getNumericalAperture(self) -> float:
        """ Get the numerical aperture of the current objective. """
        return self.send_command_and_wait("76033 a 2", [None, None, float])

    def getObjective(self) -> str:
        """ Get the serial number of the current objective. """
        return self.send_command_and_wait("76033 a 3", [None, None, str])

    def setObjective(self, pos: int):
        """ Set the objective by providing its position_index. """
        return self.send_command_and_wait("76022 %d" % pos)

    """"""

    def getEffectiveMagnification(self) -> float:
        """ Get the effective magnification (objective*coupler). """
        return self.getMagnification() * self.config["coupler"]

    def getCoupler(self) -> float:
        """ Get the magnification of the coupler (as defined by the config). """
        return self.config["coupler"]

    def setCoupler(self, value: float):
        """ Set the magnification of the coupler. """
        self.config["coupler"] = value
        writeConfigChange(self.config, "coupler", "%.2f" % value)

    def getMicroscopeName(self) -> str:
        """ Get the name of the microscope (as defined by the config). """
        return self.config["microscope_name"]

    def getMetadata(self):
        """ Get all meta data to be stored with the image. """
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
        self.metadata["Time"] = time.strftime("%Y%m%d-%H%M%S", time.localtime()) + "-%06d" % ((time.time() - int(time.time())) * 1e6)
        return self.metadata

    """ image saveing """

    def saveImage(self, filename: str, img: np.ndarray, add_metadata: dict = None):
        """ Save an image to the specified filename with meta data. """
        # ensure that the folder exists
        filename = Path(filename)
        filename.parent.mkdir(exist_ok=True)
        # gather the metadata
        metadata = self.getMetadata()
        if self.cam is not None:
            metadata.update(self.cam.getMetadata())
        if add_metadata is not None:
            metadata.update(add_metadata)
        # and save the file
        tifffile.imsave(filename, img, metadata=metadata)
        self.used_disk_space += filename.stat().st_size

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

    def rec_image(self, filename: str):
        """ Record a single image to a file. """
        # open the shutter before recording
        if self.isFluo():
            self.setShutter(True)

        # take the image
        im = self.cam.getImage()

        # close the shutter after recording
        if self.isFluo():
            self.setShutter(False)

        self.memmap_writer.store_image(im)
        self.saveImage(format_with_default(filename), im)
        print(f"[{formatByteNumber(self.used_disk_space)}] ", end="")

    def rec_stack(self, filename: str, n_below: int = 50, n_above: int = 250, slice_thickness_um: float = 5.0, fast_recording: bool = False, save_projection: bool = False):
        """
        Record a stack of images.

        It can be either in fast mode ("fast_recording=True") or precise mode
        ("fast_recording=False"). For fast mode, the microscope drives to the top position of the stack and continuously
        drives to the bottom position of the stack while the camera tracks images. Due to the lack of exact synchronisation
        between images and the z positions, the z positions are not reliable. Therefore, this mode is primarily used for
        projections where the exact z position is not very important. For the precise mode, the microscope moves to each
        stack position separately, and the camera waits for the microscope to arrive before it takes an image.

        The results can either be saved as a list of images or as a list of projections (min, max).

        Args:
            filename(str): the filename where to save the images. It needs to contain {z} which will be replaced by the
                index of the z slice.
            n_below: The number of slices below the current position.
            n_above: The number of slices above the current position.
            slice_thickness_um: The thickness of a slice in µm.
            fast_recording: Whether to use fast recording (True) or precise recording (False).
            save_projection: Whether to save the projections (True) or the single images (False).
        """
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

        # open the shutter before recording
        if self.isFluo():
            self.setShutter(True)

        # either move to every positions separately (precise stack) or move continuously while recording images
        if not fast_recording:
            buffer = self.recordPreciseStackToBuffer(z, z_start, z_stop, n_slices)
        else:
            buffer = self.recordFastStackToBuffer(z, z_start, z_stop, n_slices)

        # close the shutter after recording
        if self.isFluo():
            self.setShutter(False)

        if 1:
            if not save_projection:
                # save single images
                for i in range(n_slices):
                    self.saveImage(format_with_default(filename, z=i), buffer[i])
            else:
                # save projection
                dtype = np.uint8
                if n_slices > 256:
                    dtype = np.uint16
                #for i in range(n_slices):
                #    self.saveImage(format_with_default(filename, z=i), buffer[i])
                self.saveImage(format_with_default(filename, z='MinProj'), np.min(buffer, axis=0))
                self.saveImage(format_with_default(filename, z='MaxProj'), np.max(buffer, axis=0))
                self.saveImage(format_with_default(filename, z='MinIndices{}'.format(n_slices)), np.argmin(buffer, axis=0).astype(dtype))
                self.saveImage(format_with_default(filename, z='MaxIndices{}'.format(n_slices)), np.argmax(buffer, axis=0).astype(dtype))
            print(f"[{formatByteNumber(self.used_disk_space)}] ", end="")

    def rec_projection(self, filename: str, n_below: int = 50, n_above: int = 250, slice_thickness_um: float = 5.0,
                       fast_recording: bool = True, save_projection: bool = True):
        """
        The same as rec_stack but with the defaults set to fast recording and saving of prjections.

        Args:
            filename(str): the filename where to save the images. It needs to contain {z} which will be replaced by the
                index of the z slice.
            n_below: The number of slices below the current position.
            n_above: The number of slices above the current position.
            slice_thickness_um: The thickness of a slice in µm.
            fast_recording: Whether to use fast recording (True) or precise recording (False).
            save_projection: Whether to save the projections (True) or the single images (False).
        """
        self.rec_stack(filename, n_below, n_above, slice_thickness_um, fast_recording, save_projection)

    def rec_calibrate_stack_speed(self, n_below: int = 50, n_above: int = 250, slice_thickness_um: float = 5.0):
        """
        The same as rec_stack but with the defaults set to fast recording and saving of prjections.

        Args:
            filename(str): the filename where to save the images. It needs to contain {z} which will be replaced by the
                index of the z slice.
            n_below: The number of slices below the current position.
            n_above: The number of slices above the current position.
            slice_thickness_um: The thickness of a slice in µm.
            fast_recording: Whether to use fast recording (True) or precise recording (False).
            save_projection: Whether to save the projections (True) or the single images (False).
        """
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

        self.calibrateZSpeedForStack(z, z_start, z_stop, n_slices)

    def recordPreciseStackToBuffer(self, z: int, z_start: int, z_stop: int, n_slices: int) -> np.ndarray:
        """
        Record a stack of images in precise mode, e.g. moving to each position separatedly and taking a image when the
        zdrive arrived to the given position.

        Args:
            z: The current z position.
            z_start: The z position where to start.
            z_stop: The z position where to end.
            n_slices: The number of slices to take.

        Returns:
            buffer: An ndarray of shape [n_slices, height, width] of the recorded images.
        """
        slice_thickness_steps = (z_stop-z_start) // n_slices
        # prepare the video buffer (a numpy array the size to hold all images)
        buffer = self.cam.getVideoBuffer(n_slices)

        with self.cam.fast_recording:
            for i in range(n_slices):
                self.setZPos(z + z_start + slice_thickness_steps * i)
                buffer[i] = self.cam.getImage()
                self.memmap_writer.store_image(buffer[i])

        # reset position
        self.setZPos(z)

        return buffer

    def recordFastStackToBuffer(self, z: int, z_start: int, z_stop: int, n_slices: int) -> np.ndarray:
        """
        Record a stack of images in fast mode, e.g. moving continuously from start to end while recoding. Without precise
        synchronisation of z position and image.

        Args:
            z: The current z position.
            z_start: The z position where to start.
            z_stop: The z position where to end.
            n_slices: The number of slices to take.

        Returns:
            buffer: An ndarray of shape [n_slices, height, width] of the recorded images.
        """
        # Calculate the approximate speed to get the desired number of images using the current framerate
        if self.calibrated_proj_speed is None:
            self.calibrateZSpeedForStack(z, z_start, z_stop, n_slices)

        # move to start
        self.setZPos(z + z_start)

        # set the z speed so that the z-drive takes exactly the same time to travel the z distance as the
        # camera takes to record the images
        self.setZSpeed(self.calibrated_proj_speed)

        # prepare the video buffer (a numpy array the size to hold all images)
        buffer = self.cam.getVideoBuffer(n_slices)

        index = None
        def streaming(im):
            nonlocal index
            if index is not None:
                buffer[index] = im
                index += 1
            if index == buffer.shape[0]:
                self.cam.stopStreaming()

        #self.cam.startStreaming(streaming)

        # move to end (don't wait for command to finish) and record
        with self.nowait:
            #print("move")
            index = 0
            self.setZPos(z + z_stop)
            #while index < buffer.shape[0]:
            #    pass
            #self.cam.stopStreaming()
            self.cam.getVideo(buffer)

        self.memmap_writer.store_image(buffer[n_slices//2])

        # reset speed and position
        self.setZSpeed(8820000)

        self.setZPos(z)

        return buffer

    def calibrateZSpeedForStack(self, z: int, z_start: int, z_stop: int, n_slices: int):
        """
        Record a stack of images in fast mode, e.g. moving continuously from start to end while recoding. Without precise
        synchronisation of z position and image.

        Args:
            z: The current z position.
            z_start: The z position where to start.
            z_stop: The z position where to end.
            n_slices: The number of slices to take.

        Returns:
            buffer: An ndarray of shape [n_slices, height, width] of the recorded images.
        """
        # Calculate the approximate speed to get the desired number of images using the current framerate
        fps = self.cam.getFramerate()

        buffer = self.cam.getVideoBuffer(n_slices)
        start_time = time.time()
        self.cam.getVideo(buffer)
        duration_take_images = time.time() - start_time

        self.setZSpeed(8820000)
        for i in range(10):

            current_z_speed = self.getZSpeed()

            self.setZPos(z + z_start)

            while self.getZMoving():
                pass

            t = time.time()
            self.setZPos(z + z_stop)

            while self.getZMoving():
                pass

            duration_drive = time.time() - t
            duration_take_images2 = n_slices / fps

            self.calibrated_proj_speed = int(duration_drive / duration_take_images * current_z_speed)
            self.setZSpeed(self.calibrated_proj_speed)
            print("self.calibrated_proj_speed", self.calibrated_proj_speed, duration_drive / duration_take_images, n_slices, fps, duration_drive, duration_take_images, duration_take_images2, current_z_speed)
            if np.abs(duration_drive / duration_take_images - 1) < 0.01:
                break
        self.setZPos(z)

    """ time keeping """
    def waitSinceLast(self, wait_time: float):
        """ Ensure that at least wait_time has passed since the last call. If not wait accordingly. """
        if self.first_iteration_time is None:
            self.first_iteration_time = time.time()
        if self.iteration_time is not None:
            passed_time = time.time() - self.iteration_time
            if passed_time < wait_time:
                time.sleep(wait_time - passed_time)
        self.iteration_time = time.time()
        print(f"({int(self.iteration_time-self.first_iteration_time)}s) ", end="")

    def resetWaitTimer(self):
        self.first_iteration_time = time.time()
