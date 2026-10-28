import sys
import time
import socket
import warnings
import json
import threading
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from pathlib import Path
import tifffile
from typing import Tuple, Union

from leica_microscope.includes.comport import (
    find_mic_port,
    send_command_and_wait,
    FlowError,
    PersistentCommandSession,
)
from leica_microscope.camera import Camera
from leica_microscope.streamer import MemmapWriter
from leica_microscope.includes.config import getConfig, writeConfigChange
from leica_microscope.includes.helper_functions import format_partial, format_with_default, formatByteNumber, bar
from leica_microscope.projection_motion import (
    aligned_camera_host_times,
    desired_velocity_steps_s,
    estimate_acceleration_steps,
    estimate_stage_speed,
    estimate_stage_velocity,
    exposure_coverage,
    interpolate_frame_positions,
    prepare_projection_extrema_indices,
    required_frame_count,
    select_frame_window,
    update_projection_extrema,
)


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


def _next_calibration_speed(trials, target_duration, min_speed, max_speed):
    """Choose the next stage speed from monotonic timing measurements.

    A lower numeric speed produces a longer move.  Logarithmic interpolation
    works well across the large Leica speed range, while the factor-of-four
    safeguard prevents an unreliable early measurement from requesting an
    excessively slow move.
    """
    too_slow = [trial for trial in trials if trial["duration_s"] > target_duration]
    too_fast = [trial for trial in trials if trial["duration_s"] < target_duration]

    if too_slow and too_fast:
        lower = max(too_slow, key=lambda trial: trial["speed"])
        upper = min(too_fast, key=lambda trial: trial["speed"])
        lower_speed = int(lower["speed"])
        upper_speed = int(upper["speed"])

        # Timing noise can invert an otherwise monotonic bracket. Fall back to
        # the numeric midpoint rather than extrapolating through noisy data.
        if lower_speed >= upper_speed:
            return max(min_speed, min(max_speed, (lower_speed + upper_speed) // 2))

        log_lower_duration = np.log(lower["duration_s"])
        log_upper_duration = np.log(upper["duration_s"])
        if np.isclose(log_lower_duration, log_upper_duration):
            candidate = (lower_speed + upper_speed) // 2
        else:
            fraction = (
                (np.log(target_duration) - log_lower_duration)
                / (log_upper_duration - log_lower_duration)
            )
            candidate = int(
                np.exp(
                    np.log(lower_speed)
                    + fraction * (np.log(upper_speed) - np.log(lower_speed))
                )
            )
        return max(lower_speed + 1, min(upper_speed - 1, candidate))

    if too_fast:
        # We need a slower numeric speed. Estimate the local response in log
        # space when possible; otherwise use the original proportional step.
        current = min(too_fast, key=lambda trial: trial["speed"])
        current_speed = int(current["speed"])
        candidate = current_speed * current["duration_s"] / target_duration
        higher = [trial for trial in too_fast if trial["speed"] > current_speed]
        if higher:
            neighbor = min(higher, key=lambda trial: trial["speed"])
            log_speed_delta = np.log(current_speed) - np.log(neighbor["speed"])
            if not np.isclose(log_speed_delta, 0):
                elasticity = (
                    np.log(current["duration_s"])
                    - np.log(neighbor["duration_s"])
                ) / log_speed_delta
                if elasticity < -0.05:
                    candidate = np.exp(
                        np.log(current_speed)
                        + (
                            np.log(target_duration)
                            - np.log(current["duration_s"])
                        )
                        / elasticity
                    )
                else:
                    # The stage is on its acceleration-limited plateau: small
                    # speed changes do not measurably lengthen the move. Take
                    # one bounded large step to get below that plateau, after
                    # which the normal bracketed interpolation takes over.
                    candidate = current_speed / 4.0

        candidate = max(current_speed / 4.0, min(current_speed * 0.9, candidate))
        return max(min_speed, min(max_speed, int(candidate)))

    # This path is mainly useful when a caller seeds calibration below the
    # solution. The live calibration always measures max_speed first.
    current = max(too_slow, key=lambda trial: trial["speed"])
    candidate = current["speed"] * current["duration_s"] / target_duration
    candidate = min(current["speed"] * 4.0, max(current["speed"] * 1.1, candidate))
    return max(min_speed, min(max_speed, int(candidate)))


class NoMicroscopeFound(Exception):
    pass


class TimedProjectionSession:
    """Keep a Z origin across adjacent projections and pipeline TIFF writes."""

    def __init__(self, microscope):
        self.microscope = microscope
        self.center_z = None
        self.original_speed = None
        self.pass_index = 0
        self.preflight = None
        self.pending_write = None
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.closed = False
        self.last_start = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def invalidate_preflight(self):
        """Call after changing illumination, camera settings, or mode."""
        self.preflight = None

    def _queue_files(self, files):
        if self.pending_write is not None:
            self.pending_write.result()
        self.pending_write = self.executor.submit(
            self.microscope._save_timed_projection_files, files
        )

    def record(self, filename, z_start_um, z_stop_um, scan_time_s):
        if self.closed:
            raise RuntimeError("Timed projection session is closed")
        if self.pending_write is not None and self.pending_write.done():
            self.pending_write.result()
        if self.center_z is None:
            self.center_z = self.microscope.getZPos()
            self.original_speed = self.microscope.getZSpeed()
        started = time.perf_counter()
        start_interval = (
            None if self.last_start is None else started - self.last_start
        )
        self.last_start = started
        start_um, stop_um = (
            (z_start_um, z_stop_um) if self.pass_index % 2 == 0
            else (z_stop_um, z_start_um)
        )
        result = self.microscope.rec_timed_continuous_projection(
            filename, start_um, stop_um, scan_time_s,
            center_z_steps=self.center_z, leave_at_edge=True,
            cached_preflight=self.preflight, save_callback=self._queue_files,
        )
        self.preflight = result["preflight"]
        self.pass_index += 1
        if "actual_scan_time_s" in result:
            phase = result.get("phase_seconds", {})
            print("[scan {:.3f}s, lead {:.3f}s, setup {:.3f}s{}] ".format(
                result["actual_scan_time_s"],
                phase.get("position_to_lead_s", float("nan")),
                phase.get("setup_before_position_s", float("nan")),
                ", start-to-start {:.3f}s".format(start_interval)
                if start_interval is not None else "",
            ), end="")
        return result

    def finish_position(self):
        """Restore the reference Z before any XY-position change."""
        if self.center_z is None:
            return
        started = time.perf_counter()
        try:
            self.microscope.setZSpeed(self.microscope.getZSpeedMax())
            if self.microscope.getZPos() != self.center_z:
                self.microscope.setZPos(self.center_z)
        finally:
            self.microscope.setZSpeed(self.original_speed)
        print("[Z restore {:.3f}s] ".format(
            time.perf_counter() - started), end="")
        self.center_z = None
        self.original_speed = None
        self.pass_index = 0
        self.preflight = None
        self.last_start = None

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.finish_position()
        finally:
            self.executor.shutdown(wait=True)
        if self.pending_write is not None:
            self.pending_write.result()


class Microscope:
    # Empirically, five frames was marginal for 1 um endpoint accuracy while
    # six was reproducible over repeated 10 um sweeps on Mic2.
    PREACCELERATED_MINIMUM_FRAMES = 6
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
                                     port=None))

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
        # Calibration is specific to this camera/stage session. Keeping these
        # on the instance avoids accidentally reusing another microscope
        # object's class-level value.
        self.calibrated_proj_speed = None
        self.projection_calibration = None
        self.preaccelerated_projection_model = self.loadPreacceleratedProjectionModel()

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

    def getZSpeedMin(self) -> int:
        """ Get the minimum accepted speed command of the z stage. """
        return self.send_command_and_wait("71058", int)

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
            # FLUO to POL leaves some filter in the light path
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
        if slice_thickness_steps <= 0:
            raise ValueError("slice_thickness_um is smaller than one Z-stage step")

        # convert start/end to steps
        z_start = slice_start * slice_thickness_steps
        z_stop = (slice_stop + 2) * slice_thickness_steps
        n_slices = np.abs(slice_stop - slice_start)
        if n_slices <= 0:
            raise ValueError("A stack needs at least one slice")

        # get position and move to start
        z = self.getZPos()

        # open the shutter before recording
        is_fluo = self.isFluo()
        if is_fluo:
            self.setShutter(True)

        # either move to every positions separately (precise stack) or move continuously while recording images
        try:
            if not fast_recording:
                buffer = self.recordPreciseStackToBuffer(z, z_start, z_stop, n_slices)
            else:
                buffer = self.recordFastStackToBuffer(z, z_start, z_stop, n_slices)
        finally:
            # A camera, calibration, or stage failure must not leave the
            # fluorescence shutter open.
            if is_fluo:
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


    def rec_projection(
            self, filename: str, n_below: int = 50, n_above: int = 250,
            slice_thickness_um: float = 5.0, fast_recording: bool = True,
            save_projection: bool = True, minimum_frames: int = None,
            camera_margin_frames: int = 4):
        """
        Record a projection with the persistent pre-accelerated method.

        Passing non-default ``fast_recording`` or ``save_projection`` options
        retains the legacy ``rec_stack`` behavior for compatibility.

        Args:
            filename(str): the filename where to save the images. It needs to contain {z} which will be replaced by the
                index of the z slice.
            n_below: The number of slices below the current position.
            n_above: The number of slices above the current position.
            slice_thickness_um: The thickness of a slice in µm.
            fast_recording: Whether to use fast recording (True) or precise recording (False).
            save_projection: Whether to save the projections (True) or the single images (False).
        """
        if fast_recording and save_projection:
            return self.rec_preaccelerated_projection(
                filename,
                n_below=n_below,
                n_above=n_above,
                slice_thickness_um=slice_thickness_um,
                minimum_frames=minimum_frames,
                camera_margin_frames=camera_margin_frames,
            )
        return self.rec_stack(
            filename,
            n_below,
            n_above,
            slice_thickness_um,
            fast_recording,
            save_projection,
        )

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

        return self.calibrateZSpeedForStack(z, z_start, z_stop, n_slices)

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
        calibration = self.projection_calibration
        calibrated_geometry_matches = bool(
            calibration
            and calibration.get("n_slices") == int(n_slices)
            and calibration.get("travel_steps") == abs(z_stop - z_start)
        )
        if self.calibrated_proj_speed is None or (
            calibration is not None and not calibrated_geometry_matches
        ):
            calibration = self.calibrateZSpeedForStack(
                z, z_start, z_stop, n_slices
            )

        if calibration is not None and not calibration.get("success", False):
            raise RuntimeError(
                "Fast projection recording refused because calibration status "
                "is '{}'. The requested Z range cannot be covered reliably at "
                "the current camera rate.".format(calibration.get("status"))
            )

        original_speed = self.getZSpeed()
        max_speed = self.getZSpeedMax()

        # Prepare the large video buffer before moving the stage, so a memory
        # allocation failure cannot leave the sample displaced.
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

        try:
            # move to start and select the calibrated traversal speed
            self.setZPos(z + z_start)
            self.setZSpeed(self.calibrated_proj_speed)

            # move to end (don't wait for command to finish) and record
            with self.nowait:
                index = 0
                self.setZPos(z + z_stop)
                self.cam.getVideo(buffer)

            self.memmap_writer.store_image(buffer[n_slices//2])
        finally:
            # Restore even when camera acquisition or memmap publishing fails.
            self.setZSpeed(max_speed)
            self.setZPos(z)
            self.setZSpeed(original_speed)

        return buffer

    def _measureCameraDuration(self, n_slices: int) -> float:
        """Measure the same camera burst used by fast projection recording."""
        buffer = self.cam.getVideoBuffer(n_slices)
        start_time = time.perf_counter()
        self.cam.getVideo(buffer)
        duration = time.perf_counter() - start_time
        del buffer
        return duration

    def _measureZMoveDuration(self, z_start: int, z_stop: int, speed: int,
                              reposition_speed: int) -> float:
        """Time one stopped-to-stopped Z move, repositioning quickly first."""
        self.setZSpeed(reposition_speed)
        self.setZPos(z_start)
        self.setZSpeed(speed)
        start_time = time.perf_counter()
        self.setZPos(z_stop)
        return time.perf_counter() - start_time

    def calibrateZSpeedForStack(self, z: int, z_start: int, z_stop: int, n_slices: int,
                                tolerance: float = 0.01, max_iterations: int = 8):
        """
        Match stopped-to-stopped Z travel time to a real camera burst.

        Calibration begins at maximum speed, which both establishes the
        fastest physically reachable move and prevents an unnecessarily slow
        first trial. Further trials use bounded log interpolation. The stage
        position and its original speed are restored before this method exits.

        Args:
            z: The current z position.
            z_start: The z position where to start.
            z_stop: The z position where to end.
            n_slices: The number of slices to take.

        Returns:
            A dictionary containing status, selected speed, timing, and every
            measured trial. ``success`` is false when the timing is physically
            unreachable at maximum speed or the iteration limit is exhausted.
        """
        if n_slices <= 0:
            raise ValueError("Calibration needs at least one camera frame")
        if z_stop == z_start:
            raise ValueError("Calibration needs a non-zero Z travel distance")
        if tolerance <= 0:
            raise ValueError("tolerance must be positive")
        if max_iterations <= 0:
            raise ValueError("max_iterations must be positive")

        absolute_start = int(z + z_start)
        absolute_stop = int(z + z_stop)
        z_min, z_max = self.getZRange()
        if not (z_min <= absolute_start <= z_max and z_min <= absolute_stop <= z_max):
            raise ValueError(
                "Calibration travel [{}, {}] is outside the Z range [{}, {}]".format(
                    absolute_start, absolute_stop, z_min, z_max
                )
            )

        fps = float(self.cam.getFramerate())
        if not np.isfinite(fps) or fps <= 0:
            raise RuntimeError("Camera returned an invalid frame rate: {!r}".format(fps))

        original_z = self.getZPos()
        original_speed = self.getZSpeed()
        max_speed = int(self.getZSpeedMax())
        min_speed = 1
        trials = []
        previous_calibration = self.projection_calibration
        try:
            camera_duration = float(self._measureCameraDuration(n_slices))
            if not np.isfinite(camera_duration) or camera_duration <= 0:
                raise RuntimeError(
                    "Camera burst returned an invalid duration: {!r}".format(
                        camera_duration
                    )
                )

            # A fraction of one frame is a more realistic lower bound than a
            # strict percentage for very short stacks.
            tolerance_s = max(
                camera_duration * tolerance,
                0.5 / fps,
            )

            warm_start_speed = None
            current_travel_steps = abs(absolute_stop - absolute_start)
            if previous_calibration and previous_calibration.get("success"):
                previous_fps = previous_calibration.get("reported_fps", 0)
                previous_duration = previous_calibration.get("camera_duration_s", 0)
                previous_travel = previous_calibration.get("travel_steps", 0)
                if (
                    previous_fps > 0
                    and abs(previous_fps - fps) / fps <= 0.05
                    and previous_duration > 0
                    and previous_travel > 0
                ):
                    velocity_ratio = (
                        current_travel_steps / camera_duration
                    ) / (previous_travel / previous_duration)
                    if 0.5 <= velocity_ratio <= 2.0:
                        warm_start_speed = int(
                            previous_calibration["selected_speed"] * velocity_ratio
                        )
                        warm_start_speed = max(
                            min_speed, min(max_speed, warm_start_speed)
                        )

            candidate_speed = max_speed
            used_speeds = set()
            search_trials = []
            status = "max_iterations"
            for iteration in range(max_iterations):
                if candidate_speed in used_speeds:
                    unused_lower = max(min_speed, candidate_speed - 1)
                    unused_upper = min(max_speed, candidate_speed + 1)
                    if unused_lower not in used_speeds:
                        candidate_speed = unused_lower
                    elif unused_upper not in used_speeds:
                        candidate_speed = unused_upper
                    else:
                        break

                duration_drive = self._measureZMoveDuration(
                    absolute_start,
                    absolute_stop,
                    candidate_speed,
                    max_speed,
                )
                trial = {
                    "iteration": iteration + 1,
                    "sample": len(trials) + 1,
                    "speed": int(candidate_speed),
                    "duration_s": float(duration_drive),
                    "error_s": float(duration_drive - camera_duration),
                    "relative_error": float(
                        (duration_drive - camera_duration) / camera_duration
                    ),
                }
                trials.append(trial)
                used_speeds.add(int(candidate_speed))
                print(
                    "projection calibration trial {}/{}: speed={} stage={:.4f}s "
                    "camera={:.4f}s error={:+.1f}%".format(
                        iteration + 1,
                        max_iterations,
                        candidate_speed,
                        duration_drive,
                        camera_duration,
                        trial["relative_error"] * 100,
                    )
                )

                # Close to the physical boundary, serial/polling jitter is a
                # substantial fraction of the entire maximum-speed move. A
                # single slow sample must not reject an otherwise reachable
                # projection. Confirm with three samples and use their median.
                representative_trial = trial
                if (
                    iteration == 0
                    and candidate_speed == max_speed
                    and duration_drive >= camera_duration * 0.85
                ):
                    maximum_speed_durations = [duration_drive]
                    for confirmation_index in range(2):
                        confirmation_duration = self._measureZMoveDuration(
                            absolute_start,
                            absolute_stop,
                            candidate_speed,
                            max_speed,
                        )
                        confirmation = {
                            "iteration": iteration + 1,
                            "sample": len(trials) + 1,
                            "confirmation": confirmation_index + 1,
                            "speed": int(candidate_speed),
                            "duration_s": float(confirmation_duration),
                            "error_s": float(
                                confirmation_duration - camera_duration
                            ),
                            "relative_error": float(
                                (confirmation_duration - camera_duration)
                                / camera_duration
                            ),
                        }
                        trials.append(confirmation)
                        maximum_speed_durations.append(confirmation_duration)
                        print(
                            "projection calibration max-speed confirmation "
                            "{}/2: stage={:.4f}s error={:+.1f}%".format(
                                confirmation_index + 1,
                                confirmation_duration,
                                confirmation["relative_error"] * 100,
                            )
                        )

                    median_duration = float(np.median(maximum_speed_durations))
                    representative_trial = {
                        "iteration": iteration + 1,
                        "speed": int(candidate_speed),
                        "duration_s": median_duration,
                        "error_s": float(median_duration - camera_duration),
                        "relative_error": float(
                            (median_duration - camera_duration) / camera_duration
                        ),
                        "sample_count": len(maximum_speed_durations),
                        "aggregation": "median",
                    }
                    print(
                        "projection calibration max-speed median: "
                        "stage={:.4f}s camera={:.4f}s error={:+.1f}%".format(
                            median_duration,
                            camera_duration,
                            representative_trial["relative_error"] * 100,
                        )
                    )

                search_trials.append(representative_trial)

                if abs(representative_trial["error_s"]) <= tolerance_s:
                    status = "calibrated"
                    break

                # The first trial is always at maximum speed. If that move is
                # still slower than the camera burst, no numeric speed can
                # cover the requested distance before acquisition completes.
                if (
                    candidate_speed == max_speed
                    and representative_trial["error_s"] > tolerance_s
                ):
                    status = "max_speed_limited"
                    break

                if (
                    iteration == 0
                    and warm_start_speed is not None
                    and warm_start_speed not in used_speeds
                ):
                    candidate_speed = warm_start_speed
                else:
                    candidate_speed = _next_calibration_speed(
                        search_trials,
                        camera_duration,
                        min_speed,
                        max_speed,
                    )
            else:
                status = "max_iterations"

            best_trial = min(
                search_trials, key=lambda trial: abs(trial["error_s"])
            )
            self.calibrated_proj_speed = int(best_trial["speed"])
            result = {
                "status": status,
                "success": status == "calibrated",
                "selected_speed": self.calibrated_proj_speed,
                "camera_duration_s": camera_duration,
                "reported_fps": fps,
                "expected_duration_from_fps_s": n_slices / fps,
                "tolerance_s": tolerance_s,
                "z_start_steps": absolute_start,
                "z_stop_steps": absolute_stop,
                "travel_steps": abs(absolute_stop - absolute_start),
                "n_slices": int(n_slices),
                "warm_start_speed": warm_start_speed,
                "trials": trials,
                "representative_trials": search_trials,
            }
            self.projection_calibration = result

            if status == "max_speed_limited":
                warnings.warn(
                    "Projection timing is unreachable: even maximum Z speed "
                    "takes {:.4f}s, while the camera records {} frames in {:.4f}s. "
                    "The selected maximum speed is best-effort and will not cover "
                    "the full requested Z travel during acquisition.".format(
                        best_trial["duration_s"], n_slices, camera_duration
                    ),
                    RuntimeWarning,
                )
            elif status == "max_iterations":
                warnings.warn(
                    "Projection calibration did not reach its timing tolerance; "
                    "using the best measured speed {}.".format(
                        self.calibrated_proj_speed
                    ),
                    RuntimeWarning,
                )
            return result
        finally:
            # Calibration must never leave the stage displaced or change its
            # normal operating speed, including when camera/stage timing fails.
            active_exception = sys.exc_info()[0] is not None
            restoration_errors = []
            for description, restore in (
                ("set maximum return speed", lambda: self.setZSpeed(max_speed)),
                ("restore Z position", lambda: self.setZPos(original_z)),
                ("restore original Z speed", lambda: self.setZSpeed(original_speed)),
            ):
                try:
                    restore()
                except BaseException as error:
                    restoration_errors.append("{}: {!r}".format(description, error))
            if restoration_errors and not active_exception:
                raise RuntimeError(
                    "Calibration state restoration failed: {}".format(
                        "; ".join(restoration_errors)
                    )
                )

    """ pre-accelerated projection recording """

    def getPreacceleratedProjectionModelPath(self) -> Path:
        return Path(__file__).resolve().with_name("projection_velocity_model.json")

    def loadPreacceleratedProjectionModel(self):
        """Load the persistent speed-to-steady-velocity model, if available."""
        path = self.getPreacceleratedProjectionModelPath()
        if not path.exists():
            return None
        try:
            with path.open("r") as file_handle:
                model = json.load(file_handle)
            # Validate the fields used by interpolation before accepting it.
            if not model.get("samples"):
                raise ValueError("model contains no samples")
            for sample in model["samples"]:
                if sample["speed"] <= 0 or sample["velocity_steps_s"] <= 0:
                    raise ValueError("model contains a non-positive sample")
            return model
        except (OSError, ValueError, KeyError, TypeError) as error:
            warnings.warn(
                "Could not load pre-accelerated projection model {}: {}".format(
                    path, error
                ),
                RuntimeWarning,
            )
            return None

    def savePreacceleratedProjectionModel(self, model=None) -> Path:
        """Persist the session-independent stage velocity model atomically."""
        if model is None:
            model = self.preaccelerated_projection_model
        if model is None:
            raise ValueError("There is no pre-accelerated projection model to save")
        path = self.getPreacceleratedProjectionModelPath()
        temporary_path = path.with_suffix(path.suffix + ".tmp")
        temporary_path.write_text(
            json.dumps(model, indent=2, sort_keys=True), encoding="utf-8"
        )
        temporary_path.replace(path)
        return path

    def measureZSteadyVelocity(self, speed: int, z_start: int, z_stop: int,
                               timeout_s: float = 60.0) -> dict:
        """Measure constant-velocity Z motion using timestamped position polls."""
        speed = int(speed)
        z_start = int(z_start)
        z_stop = int(z_stop)
        if speed <= 0:
            raise ValueError("speed must be positive")
        if z_start == z_stop:
            raise ValueError("Velocity measurement needs non-zero Z travel")
        z_min, z_max = self.getZRange()
        if not (z_min <= z_start <= z_max and z_min <= z_stop <= z_max):
            raise ValueError("Velocity measurement is outside the Z range")

        original_z = self.getZPos()
        original_speed = self.getZSpeed()
        max_speed = self.getZSpeedMax()
        direction = 1 if z_stop > z_start else -1
        travel_steps = abs(z_stop - z_start)
        samples = []

        try:
            self.setZSpeed(max_speed)
            self.setZPos(z_start)
            self.setZSpeed(speed)

            command_start = time.perf_counter()
            with self.nowait:
                self.setZPos(z_stop)
            command_end = time.perf_counter()
            deadline = command_end + timeout_s

            with PersistentCommandSession(self.port) as session:
                while True:
                    before = time.perf_counter()
                    position = session.query("71023", int)
                    after = time.perf_counter()
                    samples.append(((before + after) / 2.0, int(position)))
                    if direction * (position - z_stop) >= 0:
                        break
                    if after >= deadline:
                        raise TimeoutError(
                            "Timed out measuring Z velocity at speed {}".format(speed)
                        )
                    time.sleep(0.001)

            # Ensure the controller has fully settled before fitting and return.
            self.setZPos(z_stop)

            sample_times = np.asarray([sample[0] for sample in samples], dtype=float)
            sample_positions = np.asarray(
                [sample[1] for sample in samples], dtype=float
            )
            progress = direction * (sample_positions - z_start)
            central = (progress >= 0.2 * travel_steps) & (
                progress <= 0.8 * travel_steps
            )
            if np.count_nonzero(central) < 3:
                central = (progress >= 0.1 * travel_steps) & (
                    progress <= 0.9 * travel_steps
                )
            if np.count_nonzero(central) < 3:
                raise RuntimeError(
                    "Too few central Z samples to measure steady velocity"
                )

            slope, intercept = np.polyfit(
                sample_times[central], sample_positions[central], 1
            )
            velocity_steps_s = abs(float(slope))
            fitted = slope * sample_times[central] + intercept
            residuals = sample_positions[central] - fitted
            rms_residual_steps = float(np.sqrt(np.mean(residuals ** 2)))

            time_delta = np.diff(sample_times)
            position_delta = direction * np.diff(sample_positions)
            valid_segments = (time_delta > 0) & (position_delta >= 0)
            segment_velocity = np.zeros_like(time_delta)
            segment_velocity[valid_segments] = (
                position_delta[valid_segments] / time_delta[valid_segments]
            )
            segment_progress = direction * (
                (sample_positions[:-1] + sample_positions[1:]) / 2.0 - z_start
            )
            steady_segments = np.flatnonzero(
                valid_segments
                & (segment_velocity >= 0.9 * velocity_steps_s)
                & (segment_progress <= 0.6 * travel_steps)
            )
            if len(steady_segments):
                acceleration_steps = max(
                    0, int(round(segment_progress[steady_segments[0]]))
                )
            else:
                # Conservative fallback if polling was too sparse to resolve
                # the acceleration transition.
                acceleration_steps = int(round(0.2 * travel_steps))

            relative_start = samples[0][0]
            return {
                "speed": speed,
                "velocity_steps_s": velocity_steps_s,
                "velocity_um_s": velocity_steps_s * self.getZResolution(),
                "acceleration_steps": acceleration_steps,
                "acceleration_um": acceleration_steps * self.getZResolution(),
                "travel_steps": travel_steps,
                "duration_s": samples[-1][0] - samples[0][0],
                "rms_residual_steps": rms_residual_steps,
                "sample_count": len(samples),
                "command_duration_s": command_end - command_start,
                "position_samples": [
                    [sample_time - relative_start, sample_position]
                    for sample_time, sample_position in samples
                ],
            }
        finally:
            self.setZSpeed(max_speed)
            self.setZPos(original_z)
            self.setZSpeed(original_speed)

    def calibratePreacceleratedProjectionModel(
            self,
            speeds=(10000, 20000, 40000, 75000, 150000, 300000, 500000, 750000),
            travel_um: float = 500.0,
            minimum_travel_um: float = 50.0,
            persist: bool = True) -> dict:
        """Measure and optionally persist a reusable steady-velocity model."""
        speeds = sorted(set(int(speed) for speed in speeds))
        if not speeds or speeds[0] <= 0:
            raise ValueError("At least one positive calibration speed is required")
        if travel_um <= 0 or minimum_travel_um <= 0:
            raise ValueError("Calibration travel distances must be positive")
        if minimum_travel_um > travel_um:
            raise ValueError("minimum_travel_um cannot exceed travel_um")
        max_speed = self.getZSpeedMax()
        if speeds[-1] > max_speed:
            raise ValueError("A calibration speed exceeds the Z speed maximum")
        z_resolution = self.getZResolution()
        maximum_travel_steps = int(round(float(travel_um) / z_resolution))
        minimum_travel_steps = int(
            round(float(minimum_travel_um) / z_resolution)
        )
        if maximum_travel_steps <= 0 or minimum_travel_steps <= 0:
            raise ValueError("travel_um is smaller than one Z step")
        start_z = self.getZPos()
        z_min, z_max = self.getZRange()

        samples = []
        for speed in speeds:
            scaled_steps = int(
                round(maximum_travel_steps * speed / speeds[-1])
            )
            sample_travel_steps = min(
                maximum_travel_steps,
                max(minimum_travel_steps, scaled_steps),
            )
            stop_z = start_z + sample_travel_steps
            if not (z_min <= stop_z <= z_max):
                stop_z = start_z - sample_travel_steps
            if not (z_min <= stop_z <= z_max):
                raise ValueError(
                    "Not enough Z range for velocity calibration at speed {}"
                    .format(speed)
                )
            print(
                "pre-acceleration velocity calibration: speed {} travel {:.1f} um"
                .format(speed, sample_travel_steps * z_resolution),
                flush=True,
            )
            samples.append(
                self.measureZSteadyVelocity(speed, start_z, stop_z)
            )

        model = {
            "version": 2,
            "created_local": time.strftime("%Y-%m-%d %H:%M:%S %z"),
            "microscope_name": self.getMicroscopeName(),
            "camera_backend": self.config.get("camera"),
            "camera_fps": self.cam.getFramerate() if self.cam is not None else None,
            "z_resolution_um_per_step": z_resolution,
            "maximum_calibration_travel_um": maximum_travel_steps * z_resolution,
            "minimum_calibration_travel_um": minimum_travel_steps * z_resolution,
            "samples": samples,
        }
        self.preaccelerated_projection_model = model
        if persist:
            model["path"] = str(self.savePreacceleratedProjectionModel(model))
            # Save again so the persisted document contains its own path.
            self.savePreacceleratedProjectionModel(model)
        return model

    def recordTimedContinuousProjection(
            self, z_start_um: float, z_stop_um: float,
            scan_time_s: float, exposure_ms: float = None,
            speed_override: int = None, return_indices: bool = False,
            center_z_steps: int = None, leave_at_edge: bool = False):
        """Stream min/max projections at a requested Z span and scan time.

        The stage is pre-accelerated outside the requested span.  A near-full
        frame-period exposure maximizes Z integration coverage while retaining
        the camera's full readout rate. Basler acquisition timestamps, latched
        to the host clock, and polled Z positions determine which exposure
        intervals intersect the requested span. No raw video stack is kept.

        Returns (minimum image, maximum image, diagnostics), or also the
        zero-based contributing-frame argmin/argmax maps immediately before
        diagnostics when ``return_indices`` is true.
        """
        model = self.preaccelerated_projection_model
        method_started = time.perf_counter()
        if model is None:
            raise RuntimeError("A pre-accelerated Z velocity model is required")
        if self.config.get("camera") != "basler" or not hasattr(
                self.cam, "streamFramesWithTimestamps"):
            raise NotImplementedError(
                "Timed continuous projection currently requires a Basler camera"
            )
        if model.get("microscope_name") not in (None, self.getMicroscopeName()):
            raise RuntimeError("The Z velocity model belongs to another microscope")
        if not np.isfinite(scan_time_s) or scan_time_s <= 0:
            raise ValueError("scan_time_s must be positive")
        if not np.isfinite(z_start_um) or not np.isfinite(z_stop_um):
            raise ValueError("Z offsets must be finite")
        if z_start_um == z_stop_um:
            raise ValueError("The Z span must be nonzero")
        if return_indices:
            prepare_projection_extrema_indices()
        if np.any(self.getMoving()):
            raise RuntimeError("The stage must be stationary before recording")

        current_z = self.getZPos()
        center_z = current_z if center_z_steps is None else int(center_z_steps)
        original_speed = self.getZSpeed()
        original_exposure_ms = self.cam.exposure()
        z_resolution = self.getZResolution()
        model_resolution = model.get("z_resolution_um_per_step")
        if model_resolution is not None and not np.isclose(
                float(model_resolution), z_resolution, rtol=0, atol=1e-9):
            raise RuntimeError("The Z velocity model has a different resolution")
        start = center_z + int(round(z_start_um / z_resolution))
        stop = center_z + int(round(z_stop_um / z_resolution))
        if start == stop:
            raise ValueError("The Z span rounds to zero stage steps")
        direction = 1 if stop > start else -1
        distance_steps = abs(stop - start)
        target_velocity = distance_steps / float(scan_time_s)
        max_speed = self.getZSpeedMax()
        min_speed = self.getZSpeedMin()
        selected_speed = max(
            min_speed,
            estimate_stage_speed(model, target_velocity, max_speed=max_speed),
        )
        if speed_override is not None:
            selected_speed = int(speed_override)
            if not min_speed <= selected_speed <= max_speed:
                raise ValueError("speed_override is outside the Z speed range")
        predicted_velocity = estimate_stage_velocity(model, selected_speed)
        acceleration_steps = estimate_acceleration_steps(model, selected_speed)
        initial_fps = float(self.cam.getMaximumFramerateAtShortExposure())
        if initial_fps <= 0:
            raise RuntimeError("The camera did not report a valid frame rate")
        if exposure_ms is None:
            # Leave a small guard for Basler's frame-period quantization while
            # keeping as many independent readouts as the camera can deliver.
            exposure_ms = 1000.0 / initial_fps - 0.26
        exposure_ms = float(exposure_ms)
        if exposure_ms <= 0:
            raise ValueError("exposure_ms must be positive")

        # Calculate travel before moving the microscope.  Six camera periods
        # beyond each edge also protect against stage/model uncertainty.
        lead_steps = int(np.ceil(max(
            1.5 * acceleration_steps,
            6.0 * predicted_velocity / initial_fps,
        )))
        pre_start = start - direction * lead_steps
        command_stop = stop + direction * lead_steps
        z_min, z_max = self.getZRange()
        if not (z_min <= pre_start <= z_max and z_min <= command_stop <= z_max):
            raise ValueError("Insufficient Z range for pre-acceleration")

        camera_started = threading.Event()
        camera_first_frame = threading.Event()
        stop_camera = threading.Event()
        samples_changed = threading.Condition()
        position_samples = []
        camera_errors = []
        frame_records = []
        images = {
            "min": None, "max": None, "min_indices": None,
            "max_indices": None, "selected_count": 0,
        }
        camera_count = []
        last_block_id = []
        camera_thread = None
        command_start = None
        command_end = None
        clock = None
        actual_fps = None
        actual_exposure_ms = None
        reached_stop_at = None
        scan_complete = False
        phase_seconds = {}

        def sample_z(session):
            before = time.perf_counter()
            position = int(session.query("71023", int))
            after = time.perf_counter()
            with samples_changed:
                position_samples.append(((before + after) / 2.0, position))
                samples_changed.notify_all()
            return position

        def on_frame(image, ticks, exposure_us, block_id, retrieved_at):
            if last_block_id and block_id != last_block_id[-1] + 1:
                raise RuntimeError(
                    "Basler frame sequence skipped from {} to {}".format(
                        last_block_id[-1], block_id
                    )
                )
            last_block_id.append(block_id)
            exposure_start = (
                clock["host_time_s"]
                + (ticks - clock["camera_ticks"]) / clock["tick_frequency_hz"]
            )
            exposure_end = exposure_start + exposure_us / 1000000.0
            with samples_changed:
                while (
                        position_samples[-1][0] < exposure_end
                        and not stop_camera.is_set()):
                    samples_changed.wait(timeout=0.1)
                if position_samples[-1][0] < exposure_end:
                    # The last frame can finish after the last serial poll.
                    # It is in the post-roll region and is not selected.
                    return
                sample_times = [item[0] for item in position_samples]
                sample_positions = [item[1] for item in position_samples]
            z_at_start, z_at_end = np.interp(
                [exposure_start, exposure_end], sample_times, sample_positions
            )
            signed_start = direction * z_at_start
            signed_end = direction * z_at_end
            in_span = (
                signed_end >= direction * start
                and signed_start <= direction * stop
            )
            frame_records.append({
                "block_id": block_id,
                "camera_ticks": ticks,
                "exposure_start_host_s": exposure_start,
                "exposure_end_host_s": exposure_end,
                "retrieved_host_s": retrieved_at,
                "z_start_steps": float(z_at_start),
                "z_end_steps": float(z_at_end),
                "selected": bool(in_span),
            })
            if in_span:
                selected_index = images["selected_count"]
                (images["min"], images["max"], images["min_indices"],
                 images["max_indices"]) = update_projection_extrema(
                    images["min"], images["max"], image, selected_index,
                    images["min_indices"], images["max_indices"],
                    track_indices=return_indices,
                )
                images["selected_count"] += 1

        def camera_recorder():
            try:
                camera_count.append(self.cam.streamFramesWithTimestamps(
                    on_frame, stop_camera, camera_started, camera_first_frame
                ))
            except BaseException as error:
                camera_errors.append(error)
                camera_started.set()
                camera_first_frame.set()

        try:
            self.cam.setExposure(exposure_ms)
            actual_exposure_ms = float(self.cam.exposure())
            actual_fps = float(self.cam.getFramerate())
            if actual_fps <= 0 or actual_exposure_ms * actual_fps / 1000.0 < 0.95:
                raise RuntimeError("Camera exposure duty cycle is below 95%")
            if actual_fps < 0.99 * initial_fps:
                raise RuntimeError(
                    "Near-continuous exposure reduced camera readout rate"
                )
            clock = self.cam.latchTimestampClock()
            phase_seconds["setup_before_position_s"] = (
                time.perf_counter() - method_started
            )
            positioning_start = time.perf_counter()
            if current_z != pre_start:
                self.setZSpeed(max_speed)
                self.setZPos(pre_start)
            if current_z != pre_start or original_speed != selected_speed:
                self.setZSpeed(selected_speed)
            phase_seconds["position_to_lead_s"] = (
                time.perf_counter() - positioning_start
            )
            camera_startup_started = time.perf_counter()
            with PersistentCommandSession(self.port) as session:
                sample_z(session)
                camera_thread = threading.Thread(
                    target=camera_recorder, name="timed-projection-camera",
                    daemon=True,
                )
                camera_thread.start()
                if not camera_started.wait(timeout=5.0) or camera_errors:
                    raise RuntimeError("Could not start Basler projection stream")
                if not camera_first_frame.wait(timeout=5.0) or camera_errors:
                    raise RuntimeError("No initial Basler projection frame")
                phase_seconds["camera_startup_s"] = (
                    time.perf_counter() - camera_startup_started
                )

                command_start = time.perf_counter()
                session.send("71022 {}".format(command_stop))
                command_end = time.perf_counter()
                predicted_motion_s = abs(command_stop - pre_start) / predicted_velocity
                deadline = command_end + max(6.0, 2.5 * predicted_motion_s)
                while True:
                    position = sample_z(session)
                    if camera_errors:
                        raise RuntimeError(
                            "Basler projection failed: {!r}".format(camera_errors[0])
                        )
                    if direction * (position - command_stop) >= 0:
                        reached_stop_at = time.perf_counter()
                        phase_seconds["lead_to_lead_motion_s"] = (
                            reached_stop_at - command_start
                        )
                        break
                    if time.perf_counter() >= deadline:
                        raise TimeoutError("Timed Z projection motion timed out")
                    time.sleep(0.001)

                # Keep stage samples ahead of all frame exposure endings.
                time.sleep(1.0 / actual_fps + 0.03)
                sample_z(session)
                stop_camera.set()
                with samples_changed:
                    samples_changed.notify_all()
                camera_thread.join(timeout=5.0)
                if camera_thread.is_alive():
                    raise TimeoutError("Basler projection stream did not stop")
                if camera_errors:
                    raise RuntimeError(
                        "Basler projection failed: {!r}".format(camera_errors[0])
                    )
                scan_complete = True
        finally:
            stop_camera.set()
            with samples_changed:
                samples_changed.notify_all()
            if camera_thread is not None and camera_thread.is_alive():
                camera_thread.join(timeout=6.0)
            restore_z = not leave_at_edge or not scan_complete
            try:
                return_start = time.perf_counter()
                if restore_z:
                    self.setZSpeed(max_speed)
                    self.setZPos(center_z)
                phase_seconds["return_to_center_s"] = (
                    time.perf_counter() - return_start
                )
            finally:
                try:
                    if restore_z:
                        self.setZSpeed(original_speed)
                finally:
                    self.cam.setExposure(original_exposure_ms)
        phase_seconds["acquisition_total_s"] = (
            time.perf_counter() - method_started
        )

        if images["min"] is None or images["max"] is None:
            raise RuntimeError("No camera exposures intersected the requested Z span")
        selected = [frame for frame in frame_records if frame["selected"]]
        coverage = exposure_coverage(
            direction * start, direction * stop,
            [(direction * frame["z_start_steps"],
              direction * frame["z_end_steps"]) for frame in selected],
        )

        def crossing_time(target):
            for (t0, z0), (t1, z1) in zip(
                    position_samples[:-1], position_samples[1:]):
                if (direction * z0 <= direction * target <= direction * z1
                        and z1 != z0):
                    return t0 + (target - z0) * (t1 - t0) / (z1 - z0)
            raise RuntimeError("Stage samples did not cross Z {}".format(target))

        start_crossing = crossing_time(start)
        stop_crossing = crossing_time(stop)
        diagnostics = {
            "method": "timed_continuous_projection",
            "center_z_steps": int(center_z),
            "requested_offsets_um": [float(z_start_um), float(z_stop_um)],
            "requested_scan_time_s": float(scan_time_s),
            "actual_endpoints_steps": [int(start), int(stop)],
            "z_resolution_um_per_step": float(z_resolution),
            "selected_speed": int(selected_speed),
            "maximum_positioning_speed": int(max_speed),
            "phase_seconds": phase_seconds,
            "speed_override": (
                None if speed_override is None else int(speed_override)
            ),
            "target_velocity_steps_s": float(target_velocity),
            "predicted_velocity_steps_s": float(predicted_velocity),
            "lead_steps": int(lead_steps),
            "pre_start_steps": int(pre_start),
            "command_stop_steps": int(command_stop),
            "camera_fps": float(actual_fps),
            "camera_exposure_ms": float(actual_exposure_ms),
            "camera_exposure_duty_fraction": (
                actual_exposure_ms * actual_fps / 1000.0
            ),
            "camera_clock": clock,
            "raw_frame_count": len(frame_records),
            "selected_frame_count": len(selected),
            "index_unit": "zero_based_contributing_frame_number",
            "command_duration_s": float(command_end - command_start),
            "stage_reached_stop_host_s": reached_stop_at,
            "actual_scan_time_s": stop_crossing - start_crossing,
            "coverage_fraction": coverage["coverage_fraction"],
            "maximum_unexposed_gap_um": coverage["maximum_gap"] * z_resolution,
            "total_unexposed_gap_um": coverage["total_gap"] * z_resolution,
            "unexposed_gaps_um": [
                [(left - direction * start) * z_resolution,
                 (right - direction * start) * z_resolution]
                for left, right in coverage["gaps"]
            ],
            "frames": frame_records,
            "stage_samples": position_samples,
        }
        if return_indices:
            return (
                images["min"], images["max"], images["min_indices"],
                images["max_indices"], diagnostics,
            )
        return images["min"], images["max"], diagnostics

    def rec_timed_continuous_projection(
            self, filename: str, z_start_um: float, z_stop_um: float,
            scan_time_s: float,
            timing_tolerance_fraction: float = 0.03,
            minimum_coverage_fraction: float = 0.98,
            maximum_attempts: int = 3, *,
            center_z_steps: int = None, leave_at_edge: bool = False,
            cached_preflight: dict = None, save_callback=None) -> dict:
        """Record a verified time-controlled projection from the record GUI.

        Save the same unmodified MinProj, MaxProj, MinIndices and MaxIndices
        image types as the existing projection recorder. Each acquisition is
        checked against the requested Z-crossing time; an out-of-tolerance
        attempt is discarded and the stage speed adjusted.
        """
        if "{z" not in str(filename):
            raise ValueError("Projection filename must contain a {z} field")
        if (not np.isfinite(timing_tolerance_fraction)
                or timing_tolerance_fraction <= 0):
            raise ValueError("timing_tolerance_fraction must be positive")
        if (not np.isfinite(minimum_coverage_fraction)
                or not 0 < minimum_coverage_fraction <= 1):
            raise ValueError("minimum_coverage_fraction must be within (0, 1]")
        if int(maximum_attempts) < 1:
            raise ValueError("maximum_attempts must be positive")

        original_shutter = self.send_command_and_wait("77033", [int, int])[-1]
        attempts = []
        speed_override = None
        minimum = maximum = min_indices = max_indices = diagnostics = None
        preflight = None
        self.setShutter(True)
        preflight_started = time.perf_counter()
        acquisition_started = None
        try:
            # The timed method lengthens exposure to nearly one frame period.
            # Check the actual image at that exposure before moving the stage,
            # especially to catch a closed camera light path or saturation.
            if cached_preflight is None:
                original_exposure = self.cam.exposure()
                try:
                    max_fps = self.cam.getMaximumFramerateAtShortExposure()
                    self.cam.setExposure(1000.0 / max_fps - 0.26)
                    preview = self.cam.getImage()
                finally:
                    self.cam.setExposure(original_exposure)
                preflight = {
                    "mean": float(preview.mean()),
                    "p99": float(np.quantile(preview, 0.99)),
                    "saturated_fraction": float(
                        np.mean(preview == self.cam.getMaxValue())
                    ),
                }
            else:
                preflight = dict(cached_preflight)
            mode = self.send_command_and_wait("70028", int)
            if mode == self.MODE_TL_BF and preflight["p99"] < 5:
                raise RuntimeError(
                    "Timed projection image is nearly black; check the "
                    "camera light path and illumination"
                )
            if preflight["saturated_fraction"] > 0.01:
                raise RuntimeError(
                    "Timed projection exposure saturates over 1% of pixels; "
                    "reduce illumination before recording"
                )
            preflight_elapsed = time.perf_counter() - preflight_started
            acquisition_started = time.perf_counter()
            for attempt_number in range(1, int(maximum_attempts) + 1):
                minimum, maximum, min_indices, max_indices, diagnostics = (
                    self.recordTimedContinuousProjection(
                        z_start_um, z_stop_um, scan_time_s,
                        speed_override=speed_override,
                        return_indices=True,
                        **({"center_z_steps": center_z_steps,
                            "leave_at_edge": leave_at_edge}
                           if leave_at_edge else {}),
                    )
                )
                actual_time = diagnostics["actual_scan_time_s"]
                relative_error = (actual_time - scan_time_s) / scan_time_s
                valid_timing = abs(relative_error) <= timing_tolerance_fraction
                valid_coverage = (
                    diagnostics["coverage_fraction"]
                    >= minimum_coverage_fraction
                )
                attempts.append({
                    "attempt": attempt_number,
                    "actual_scan_time_s": actual_time,
                    "relative_timing_error": relative_error,
                    "coverage_fraction": diagnostics["coverage_fraction"],
                    "selected_speed": diagnostics["selected_speed"],
                    "selected_frame_count": diagnostics["selected_frame_count"],
                    "accepted": bool(valid_timing and valid_coverage),
                })
                if valid_timing and valid_coverage:
                    break
                if attempt_number == int(maximum_attempts):
                    raise RuntimeError(
                        "Timed projection did not meet timing/coverage limits "
                        "after {} attempts".format(maximum_attempts)
                    )
                if valid_coverage:
                    speed_override = int(round(
                        diagnostics["selected_speed"]
                        * actual_time / scan_time_s
                    ))
                    speed_override = max(
                        self.getZSpeedMin(),
                        min(self.getZSpeedMax(), speed_override),
                    )
                else:
                    speed_override = diagnostics["selected_speed"]
        finally:
            self.setShutter(original_shutter)

        phase_seconds = diagnostics.setdefault("phase_seconds", {})
        phase_seconds["preflight_s"] = preflight_elapsed
        phase_seconds["verified_acquisition_s"] = (
            time.perf_counter() - acquisition_started
        )

        metadata = {
            "ProjectionMethod": "timed_continuous",
            "RequestedStartOffsetMicrometers": float(z_start_um),
            "RequestedStopOffsetMicrometers": float(z_stop_um),
            "RequestedScanTimeSeconds": float(scan_time_s),
            "ActualScanTimeSeconds": diagnostics["actual_scan_time_s"],
            "ExposureCoverageFraction": diagnostics["coverage_fraction"],
            "SelectedFrameCount": diagnostics["selected_frame_count"],
            "ProjectionAttempts": json.dumps(attempts, sort_keys=True),
            "ProjectionPreflight": json.dumps(preflight, sort_keys=True),
            "TimedContinuousProjection": json.dumps(
                diagnostics, sort_keys=True
            ),
            # saveImage first collects the current camera properties. The
            # acquisition method already restored the previous exposure, so
            # replace that field with the exposure actually used for scanning.
            "Exposure": str(diagnostics["camera_exposure_ms"]),
        }
        frame_count = diagnostics["selected_frame_count"]
        index_dtype = (
            np.uint8 if frame_count <= 256
            else np.uint16 if frame_count <= 65536
            else np.uint32
        )
        images_to_save = [
            (format_with_default(filename, z="MinProj"), minimum,
             dict(metadata, Projection="min")),
            (format_with_default(filename, z="MaxProj"), maximum,
             dict(metadata, Projection="max")),
            (format_with_default(
                filename, z="MinIndices{}".format(frame_count)),
             min_indices.astype(index_dtype, copy=False),
             dict(metadata, Projection="min_indices")),
            (format_with_default(
                filename, z="MaxIndices{}".format(frame_count)),
             max_indices.astype(index_dtype, copy=False),
             dict(metadata, Projection="max_indices")),
        ]
        if save_callback is None:
            for path, image, image_metadata in images_to_save:
                self.saveImage(path, image, image_metadata)
        else:
            # Snapshot camera properties on the acquisition thread. The TIFF
            # worker must never talk to the camera or microscope.
            base_metadata = dict(self.getMetadata())
            base_metadata.update(self.cam.getMetadata())
            save_callback([
                (path, image, dict(base_metadata, **image_metadata))
                for path, image, image_metadata in images_to_save
            ])
        if getattr(self, "memmap_writer", None) is not None:
            self.memmap_writer.store_image(maximum)
        if save_callback is None:
            print(f"[{formatByteNumber(self.used_disk_space)}] ", end="")
        else:
            print("[TIFFs queued] ", end="")
        result = dict(diagnostics)
        result["attempts"] = attempts
        result["preflight"] = preflight
        return result

    def _save_timed_projection_files(self, files):
        """Write a completed pass without accessing microscope or camera state."""
        for filename, image, metadata in files:
            path = Path(filename)
            path.parent.mkdir(exist_ok=True)
            tifffile.imsave(path, image, metadata=metadata)
            self.used_disk_space += path.stat().st_size

    def timed_projection_session(self):
        """Return a context for direction-alternating optimized projections."""
        return TimedProjectionSession(self)

    def rec_timed_continuous_projection_series(
            self, filename: str, z_start_um: float, z_stop_um: float,
            scan_time_s: float, repetition_count: int,
            repetition_time_delta: float = 0.0,
            wait_before_image_s: float = 0.0):
        """Record one-position repetitions, alternating direction at each edge.

        The origin is held fixed for all passes and restored at maximum Z speed
        on success or failure. One previous pass may be written in a background
        thread while the next is acquired; hardware access stays on this thread.
        """
        if int(repetition_count) != repetition_count or repetition_count < 1:
            raise ValueError("repetition_count must be a positive integer")
        if (not np.isfinite(repetition_time_delta)
                or repetition_time_delta < 0):
            raise ValueError("repetition_time_delta must be nonnegative")
        if not np.isfinite(wait_before_image_s) or wait_before_image_s < 0:
            raise ValueError("wait_before_image_s must be nonnegative")
        if repetition_count > 1 and "{repetition" not in str(filename):
            raise ValueError("Series filename must contain {repetition}")

        results = []
        with self.timed_projection_session() as session:
            for rep in bar(range(int(repetition_count)), desc="repetition"):
                self.waitSinceLast(repetition_time_delta)
                if wait_before_image_s:
                    time.sleep(wait_before_image_s)
                result = session.record(
                    format_partial(filename, repetition=rep),
                    z_start_um, z_stop_um, scan_time_s,
                )
                results.append(result)
        print("[{} saved] ".format(formatByteNumber(
            self.used_disk_space)), end="")
        return results

    def recordPreacceleratedStackToBuffer(
            self, z: int, z_start: int, z_stop: int,
            requested_spacing_um: float = 10.0, minimum_frames: int = None,
            camera_margin_frames: int = 4) -> Tuple[np.ndarray, dict]:
        """Pre-roll the camera and retain the exact frame window at the target."""
        model = self.preaccelerated_projection_model
        if model is None:
            raise RuntimeError(
                "No pre-accelerated projection velocity model is available. "
                "Run calibratePreacceleratedProjectionModel once first."
            )
        model_microscope = model.get("microscope_name")
        if model_microscope and model_microscope != self.getMicroscopeName():
            raise RuntimeError(
                "The projection velocity model belongs to microscope {}, not {}"
                .format(model_microscope, self.getMicroscopeName())
            )
        if minimum_frames is None:
            minimum_frames = self.PREACCELERATED_MINIMUM_FRAMES
        camera_margin_frames = int(camera_margin_frames)
        if camera_margin_frames < 2:
            raise ValueError("camera_margin_frames must be at least 2")

        absolute_start = int(z + z_start)
        absolute_stop = int(z + z_stop)
        if absolute_start == absolute_stop:
            raise ValueError("Pre-accelerated projection needs non-zero Z travel")
        direction = 1 if absolute_stop > absolute_start else -1
        distance_steps = abs(absolute_stop - absolute_start)
        z_resolution = self.getZResolution()
        model_resolution = model.get("z_resolution_um_per_step")
        if model_resolution is not None and not np.isclose(
            float(model_resolution), z_resolution, rtol=0.0, atol=1e-9
        ):
            raise RuntimeError(
                "The projection velocity model Z resolution does not match "
                "the current stage"
            )
        distance_um = distance_steps * z_resolution
        fps = float(self.cam.getFramerate())
        frame_count = required_frame_count(
            distance_um, requested_spacing_um, minimum_frames
        )
        requested_velocity = desired_velocity_steps_s(
            distance_steps, frame_count, fps
        )
        max_speed = self.getZSpeedMax()
        selected_speed = estimate_stage_speed(
            model, requested_velocity, max_speed=max_speed
        )
        selected_speed = max(self.getZSpeedMin(), selected_speed)
        predicted_velocity = estimate_stage_velocity(model, selected_speed)
        frame_step_steps = distance_steps / (frame_count - 1)
        acceleration_steps = estimate_acceleration_steps(model, selected_speed)

        # Six frame intervals ahead of the requested start comfortably covers
        # both the measured acceleration distance and Basler startup latency.
        # The camera is already acquiring before motion is commanded, so host
        # command latency changes only the number of discarded pre-roll frames.
        lead_steps = int(
            np.ceil(
                max(
                    1.5 * acceleration_steps,
                    6.0 * frame_step_steps,
                )
            )
        )
        pre_start = absolute_start - direction * lead_steps
        command_stop = absolute_stop + direction * lead_steps
        z_min, z_max = self.getZRange()
        if not (
            z_min <= pre_start <= z_max
            and z_min <= command_stop <= z_max
        ):
            raise ValueError(
                "Insufficient Z range for the required pre-acceleration lead-in"
            )

        original_speed = self.getZSpeed()
        motion_steps = abs(command_stop - pre_start)
        predicted_motion_s = motion_steps / max(predicted_velocity, 1.0)
        raw_frame_count = (
            int(np.ceil(predicted_motion_s * fps))
            + 1
            + 2 * camera_margin_frames
        )
        acquisition_buffer = self.cam.getVideoBuffer(raw_frame_count)
        position_samples = []
        camera_errors = []
        camera_started = threading.Event()
        camera_first_frame = threading.Event()
        camera_thread = None
        timing_holder = []
        timing = None
        command_start = None
        command_end = None

        def camera_recorder():
            try:
                timing_holder.append(
                    self.cam.getVideoWithTimestamps(
                        acquisition_buffer,
                        started_event=camera_started,
                        first_frame_event=camera_first_frame,
                    )
                )
            except BaseException as error:
                camera_errors.append(error)
                camera_started.set()
                camera_first_frame.set()

        try:
            self.setZSpeed(max_speed)
            self.setZPos(pre_start)
            self.setZSpeed(selected_speed)
            with PersistentCommandSession(self.port) as session:
                before = time.perf_counter()
                position = session.query("71023", int)
                after = time.perf_counter()
                position_samples.append(
                    ((before + after) / 2.0, int(position))
                )

                camera_thread = threading.Thread(
                    target=camera_recorder, name="projection-camera-preroll"
                )
                camera_thread.daemon = True
                camera_thread.start()
                if not camera_started.wait(timeout=5.0):
                    raise TimeoutError("Timed out starting projection camera")
                if camera_errors:
                    raise RuntimeError(
                        "Projection camera failed: {!r}".format(camera_errors[0])
                    )
                if not camera_first_frame.wait(timeout=5.0):
                    raise TimeoutError(
                        "Timed out waiting for the first projection frame"
                    )
                if camera_errors:
                    raise RuntimeError(
                        "Projection camera failed: {!r}".format(camera_errors[0])
                    )

                command_start = time.perf_counter()
                session.send("71022 {}".format(command_stop))
                command_end = time.perf_counter()
                deadline = command_end + max(5.0, 2.0 * predicted_motion_s)
                reached_command_stop = False
                while camera_thread.is_alive() or not reached_command_stop:
                    before = time.perf_counter()
                    position = session.query("71023", int)
                    after = time.perf_counter()
                    position_samples.append(
                        ((before + after) / 2.0, int(position))
                    )
                    reached_command_stop = (
                        direction * (position - command_stop) >= 0
                    )
                    if after >= deadline:
                        raise TimeoutError(
                            "Timed out during pre-accelerated projection motion"
                        )
                    time.sleep(0.001)

                camera_thread.join(timeout=1.0)
                if camera_thread.is_alive():
                    raise TimeoutError("Projection camera did not finish")
                if camera_errors:
                    raise RuntimeError(
                        "Projection camera failed: {!r}".format(camera_errors[0])
                    )
                timing = timing_holder[0]

                # One final sample guarantees that interpolation spans the
                # timestamp of the final frame.
                before = time.perf_counter()
                position = session.query("71023", int)
                after = time.perf_counter()
                position_samples.append(
                    ((before + after) / 2.0, int(position))
                )
        finally:
            if camera_thread is not None and camera_thread.is_alive():
                camera_thread.join(timeout=2.0)
            self.setZSpeed(max_speed)
            self.setZPos(z)
            self.setZSpeed(original_speed)

        frame_times = aligned_camera_host_times(timing)
        raw_frame_positions = interpolate_frame_positions(
            frame_times, position_samples
        )
        selected_start_index = select_frame_window(
            raw_frame_positions,
            frame_count,
            absolute_start,
            absolute_stop,
        )
        selected_stop_index = selected_start_index + frame_count
        frame_positions = raw_frame_positions[
            selected_start_index:selected_stop_index
        ]
        buffer = acquisition_buffer[selected_start_index:selected_stop_index]
        signed_frame_positions = direction * frame_positions
        signed_start = direction * absolute_start
        signed_stop = direction * absolute_stop
        signed_raw_positions = direction * raw_frame_positions
        if (
            np.min(signed_raw_positions) > signed_start
            or np.max(signed_raw_positions) < signed_stop
        ):
            raise RuntimeError(
                "Camera pre-roll did not span the requested projection range"
            )
        frame_spacings = np.diff(signed_frame_positions)
        diagnostics = {
            "method": "preaccelerated_preroll_window",
            "frame_count": frame_count,
            "raw_frame_count": raw_frame_count,
            "minimum_frames": int(minimum_frames),
            "nominal_frame_count": int(
                np.ceil(distance_um / requested_spacing_um)
            ) + 1,
            "requested_distance_um": distance_um,
            "requested_spacing_um": float(requested_spacing_um),
            "effective_spacing_um": distance_um / (frame_count - 1),
            "fps": fps,
            "selected_speed": selected_speed,
            "requested_velocity_steps_s": requested_velocity,
            "predicted_velocity_steps_s": predicted_velocity,
            "lead_steps": lead_steps,
            "lead_um": lead_steps * z_resolution,
            "acceleration_steps": acceleration_steps,
            "pre_start_steps": pre_start,
            "command_stop_steps": command_stop,
            "command_duration_s": command_end - command_start,
            "camera_margin_frames": camera_margin_frames,
            "selected_start_index": selected_start_index,
            "discarded_preroll_frames": selected_start_index,
            "discarded_postroll_frames": raw_frame_count - selected_stop_index,
            "raw_first_position_steps": float(raw_frame_positions[0]),
            "raw_last_position_steps": float(raw_frame_positions[-1]),
            "frame_positions_steps": frame_positions.tolist(),
            "first_frame_error_um": (
                signed_frame_positions[0] - signed_start
            ) * z_resolution,
            "last_frame_error_um": (
                signed_frame_positions[-1] - signed_stop
            ) * z_resolution,
            "covered_distance_um": (
                signed_frame_positions[-1] - signed_frame_positions[0]
            ) * z_resolution,
            "coverage_error_um": (
                signed_frame_positions[-1]
                - signed_frame_positions[0]
                - distance_steps
            ) * z_resolution,
            "mean_frame_spacing_um": float(np.mean(frame_spacings) * z_resolution),
            "std_frame_spacing_um": float(np.std(frame_spacings) * z_resolution),
            "camera_tick_frequency_hz": timing.get(
                "camera_tick_frequency_hz"
            ),
            "position_sample_count": len(position_samples),
        }
        return buffer, diagnostics

    def rec_preaccelerated_projection(
            self, filename: str, n_below: int = 0, n_above: int = 100,
            slice_thickness_um: float = 10.0, minimum_frames: int = None,
            camera_margin_frames: int = 4) -> dict:
        """Record min/max projections after a reusable pre-acceleration model."""
        slice_start = int(n_below)
        slice_stop = int(n_above)
        if slice_start > slice_stop:
            slice_start, slice_stop = slice_stop, slice_start
        slice_steps = int(slice_thickness_um / self.getZResolution())
        if slice_steps <= 0:
            raise ValueError("slice_thickness_um is smaller than one Z-stage step")
        z_start = slice_start * slice_steps
        z_stop = slice_stop * slice_steps
        if z_start == z_stop:
            raise ValueError("Projection needs non-zero Z distance")
        z = self.getZPos()

        is_fluo = self.isFluo()
        if is_fluo:
            self.setShutter(True)
        try:
            buffer, diagnostics = self.recordPreacceleratedStackToBuffer(
                z,
                z_start,
                z_stop,
                requested_spacing_um=slice_thickness_um,
                minimum_frames=minimum_frames,
                camera_margin_frames=camera_margin_frames,
            )
        finally:
            if is_fluo:
                self.setShutter(False)

        self.memmap_writer.store_image(buffer[len(buffer) // 2])
        index_dtype = np.uint8 if len(buffer) <= 256 else np.uint16
        metadata = {
            "PreacceleratedProjection": json.dumps(diagnostics, sort_keys=True)
        }
        self.saveImage(
            format_with_default(filename, z="MinProj"),
            np.min(buffer, axis=0),
            metadata,
        )
        self.saveImage(
            format_with_default(filename, z="MaxProj"),
            np.max(buffer, axis=0),
            metadata,
        )
        self.saveImage(
            format_with_default(
                filename, z="MinIndices{}".format(len(buffer))
            ),
            np.argmin(buffer, axis=0).astype(index_dtype),
            metadata,
        )
        self.saveImage(
            format_with_default(
                filename, z="MaxIndices{}".format(len(buffer))
            ),
            np.argmax(buffer, axis=0).astype(index_dtype),
            metadata,
        )
        print(f"[{formatByteNumber(self.used_disk_space)}] ", end="")
        return diagnostics

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
