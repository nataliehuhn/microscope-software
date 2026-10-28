from __future__ import division, print_function

import collections
import logging
import os
import serial
import socket
import sys
try:
    import thread
except ImportError:
    import _thread as thread
import threading
import time
import traceback
import re

from .includes import MicMemMap, getMicLogFile

PY3 = sys.version_info[0] == 3

logging.basicConfig(filename=getMicLogFile(), level=logging.DEBUG, format='%(asctime)s: '+os.path.basename(__file__)+' %(message)s')
logging.info("Start client")

PortMagnification = 52
FastFilterwheel = 54
MA4Mirror = 56
Docuport = 60
Master = 70
ZDrive = 71
XAxis = 72
YAxis = 73
MicroscopeButtons = 74
MicroscopeDisplay = 75
ObjectiveTurret = 76
Lamp = 77
ILTurret = 78
MagnificationChanger = 79
SwitchablePrisms = 80
FlappingCondenser = 81
CondenserDisk = 82
ApertureDiaphragmTL = 84
DICTurret = 85
ZHandwheel = 86
FieldDiaphragmIL = 94
ApertureDiaphragmIL = 95
ZoomLensTL = 96
CCWheel = 97
Polarizer = 98

STATE_Empty = 0
STATE_Written = 1
STATE_Sent = 2
STATE_Received = 3


config_file = os.path.join(os.path.dirname(__file__), "Microscope_Config.txt")


class microscope:
    class MicroscopeError(Exception):
        pass

    def __init__(self):
        self.events = collections.deque(maxlen=100)
        self.queries = collections.deque(maxlen=100)

        self.lock = threading.Lock()
        self.moving = [False, False, False]
        self.moving_event = [False, False, False]

        self.event_connect = None
        self.callback_signal = None

        self.open_commands = []

        # Load config
        self.config = dict(MicroscopePort=9998,
                           MicroscopeName="Mic",
                           Coupler=1,
                           speed_percentage=1.0,
                           InvertAxisY=False,
                           InvertAxisX=False,
                           ZSpeedFactor=0.1)
        if os.path.exists(config_file):
            if PY3:
                with open(config_file, "r") as fp:
                    code = compile(fp.read(), config_file, 'exec')
                    exec(code, globals(), self.config)
            else:
                execfile(config_file, globals(), self.config)

        self.tirf = None
        if "Tirf" in self.config:
            try:
                self.tirf = serial.Serial(self.config["Tirf"], 9600, timeout=0.5)
            except:
                self.trif = None
        else:
            self.tirf = None

        print("open")
        self.open()
        print("opened")

        #thread.start_new_thread(self.checkEvents, ())

    def connectEvent(self, function):
        if self.event_connect is None:
            thread.start_new_thread(self.checkEvents, ())
        self.event_connect = function

    def checkEvents(self):
        while True:
            time.sleep(0.01)
            if self.memmap.index_written_event != self.index_event:
                new_event_index = (self.index_event + 1) % len(self.memmap.events)
                evt = self.memmap.events[new_event_index]
                if self.event_connect:
                    self.event_connect(evt.device, evt.command, evt.answer)
                self.index_event = new_event_index

    def initialize(self):
        self.memmap.initialized = 1

        # Start receiving commands
        self.sendCommand(XAxis, 3, parameter=[1, 0, 0, 0, 0, 1, 0, 0, 0])  # Event x axis start/stop
        self.sendCommand(YAxis, 3, parameter=[1, 0, 0, 0, 0, 1, 0, 0, 0])  # Event y axis start/stop
        self.sendCommand(ZDrive, 3, parameter=[1, 0, 0, 0, 0, 1, 0, 0, 0])  # Event z axis start/stop
        self.setSpeedsToMax()

        self.sendCommand(ApertureDiaphragmTL, 3, parameter=[0, 1])  # Event aperture changed
        self.sendCommand(FieldDiaphragmIL, 3, parameter=[0, 1])  # Event field diaphragm changed

        self.sendCommand(Lamp, 3, parameter=[0, 1, 0, 0, 0, 1])  # Event lamp intentity, shutter
        self.sendCommand(Master, 3, parameter=[1, 0, 0, 0, 0])  # Event mode

        self.sendCommand(ILTurret, 3, parameter=1)  # fluo filter

        self.sendCommand(ObjectiveTurret, 3, parameter=[0, 1, 1, 0, 0, 0, 0, 0, 0, 0])  # objective

        # Get the current status
        self.memmap.mode = self.getMode()
        self.memmap.fluo_channel, self.memmap.fluo_channel_name = self.getFluoChannel()
        self.memmap.conv_x = self.getResolutionX(force=True)
        self.memmap.conv_y = self.getResolutionY(force=True)
        self.memmap.conv_z = self.getResolutionZ(force=True)
        self.memmap.stage_pos[:] = self.getPos()
        self.memmap.magnification = self.getMagnification()
        self.memmap.numerical_aperture = self.getNumericalAperture()
        self.memmap.objective = self.getObjective()

        self.memmap.x_max = self.sendRequest(XAxis, 29, int)
        self.memmap.y_max = self.sendRequest(YAxis, 29, int)

        self.memmap.shutter = False
        self.memmap.shutter_planned = -1
        self.memmap.mode_planned = -1

    def open(self, port=None):
        self.CreateMemMap()

    def CreateMemMap(self):
        print("Create Mem Map ...")
        logging.info("Create Mem Map ...")

        self.memmap = MicMemMap()
        self.index_event = self.memmap.index_written_event

        print("... done")
        logging.info("... done")

    def get_error_msg(self, command):
        if command.error == 0:  # No error
            return None
        elif command.error == 1:
            return "ParErr: Parameter out of range"
        elif command.error == 2:
            return "SequenceErr:"
        elif command.error == 3:
            return "FlowErr: Command %d aborted." % command.command
        elif command.error == 9:
            if command.command == 99:
                return "ComErr: Command can't be executed."
            elif command.command == 98:
                return "IDErr: Unknown id %d." % command.device
            elif command.command == 97:
                return "FuiErr:"
            else:
                return "UncErr:"
        else:
            raise Exception("Unknown Error Code", command.device, command.error, command.command)

    """ External functions """

    def waitTillEvent(self, moving=None, shutter=None, mode=None):
        start_time = time.time()
        while True:
            # if we have waited for one second check again
            if time.time()-start_time > 2:
                print("Waited for more than 2 seconds, talking to microscope again")
                if shutter is not None and self.memmap.shutter != shutter:
                    print("Set Shutter again")
                    self.setShutter(shutter)
                if mode is not None and self.memmap.mode != mode:
                    print("set mode again")
                    self.setMode(mode)
                if moving is not None and not ([self.memmap.moving_x, self.memmap.moving_y, self.memmap.moving_z] == [moving, moving, moving]):
                    print("inquire moving state again")
                    self.memmap.moving_x = self.getMovingX()
                    self.memmap.moving_y = self.getMovingY()
                    self.memmap.moving_z = self.getMovingZ()
                start_time = time.time()
            #print("Waiting for", moving, shutter, mode, " is ", [self.memmap.moving_x, self.memmap.moving_y, self.memmap.moving_z], self.memmap.shutter, self.memmap.shutter_planned, self.memmap.mode)
            wait = 0
            if shutter is not None and self.memmap.shutter != shutter:
                if self.memmap.shutter_planned != shutter:
                    self.setShutter(shutter)
                wait = 1
            if mode is not None and self.memmap.mode != mode:
                if self.memmap.mode_planned != mode:
                    self.setMode(mode)
                wait = 1
            if moving is not None and not ([self.memmap.moving_x, self.memmap.moving_y, self.memmap.moving_z] == [moving, moving, moving]):
                wait = 1
            if wait == 0:
                return 0
            time.sleep(0.010)

    def getEvent(self):
        if len(self.events):
            return self.events.pop()
        return None

    def isMoving(self):
        return [self.memmap.moving_x, self.memmap.moving_y, self.memmap.moving_z]

    def getStackForDevice(self, device):
        if device == ZDrive:
            return 0
        if device == XAxis:
            return 1
        if device == YAxis:
            return 2
        return 3

    """ Sending Commands """

    def sendCommand(self, device, command, parameter=None, formats=None, wait=0, callback=None):
        # Compose parameter string
        parameter_string = ""
        # Add parameter if specified
        if parameter is not None:
            if type(parameter) != list:
                parameter = [parameter]
            parameter_string += ' '+' '.join([str(par) for par in parameter])
        # wait until the next slot is not locked
        stack = self.memmap.command_stacks[self.getStackForDevice(device)]
        with stack.editLock:
            # get slot
            cmd = stack.commands[stack.pointer_client]
            # fill slot
            cmd.device = int(device)
            cmd.command = int(command)
            cmd.parameter = parameter_string.strip()
            cmd.error = 0
            cmd.answer = 0
            cmd.state = STATE_Written
            cmd.time = time.time()
            # increase pointer
            stack.pointer_client = (stack.pointer_client + 1) % len(stack.commands)
        # Return or wait
        if not wait or callback is not None:
            with self.lock:
                self.open_commands.append(cmd)
            stack = traceback.extract_stack()[:-2]
            t = threading.Thread(target=lambda: self.threadedWait(cmd, stack, formats, callback))
            t.start()
            return cmd
        # Wait until the response is received
        while not cmd.state == STATE_Received:
            time.sleep(0.001)
        # Raise error if one occurred
        if cmd.error:
            raise self.MicroscopeError(cmd.error)
        with stack.editLock:
            cmd.state = STATE_Empty
        # Format output if desired
        if formats:
            answers = cmd.answer.split()
            if type(formats) != list:
                formats = [formats]*len(answers)
            if len(answers) != len(formats):
                raise IndexError("Not enough formats specified for the number of answers")
            answers = [fmt(ans) for ans, fmt in zip(answers, formats)]
            if len(answers) == 1:
                return answers[0]
            return answers
        return cmd.answer

    def isCommandFinished(self, cmd):
        return cmd.state == STATE_Empty

    def isCommandStarted(self, cmd):
        return cmd.state != STATE_Written

    def waitForCommand(self, cmd):
        if type(cmd) != list:
            cmd = [cmd]
        for c in cmd:
            while not self.isCommandFinished(c):
                time.sleep(0.001)
                #print("Waiting for", c)
            c.state = STATE_Empty

    def waitForMyCommands(self):
        while True:
            with self.lock:
                # basically check on len(self.open_commands) == 0
                # should be enough but for some reason commands sometimes don't get removed
                # therefore we count the open commands
                count = sum([cmd.state for cmd in self.open_commands])
                # if there are none, break the loop
                if count == 0:
                    # and to be on the save side ensure that the list now is empty
                    if len(self.open_commands):
                        self.open_commands = []
                    return
            # if some commands are still pending, sleep a bit
            time.sleep(0.01)

    def executeCallback(self, function, args):
        if self.callback_signal:
            self.callback_signal.emit((function, args))
        else:
            function(*args)

    def threadedWait(self, cmd, stack, formats, callback=None):
        while not cmd.state == STATE_Received:
            time.sleep(0.1)
        # Raise error if one occurred
        if cmd.error:
            msg = "Traceback (most recent call last):\n"
            msg += "".join(traceback.format_list(stack))
            msg += self.get_error_msg(cmd)
            print("----------------------------")
            print(msg)
            print("----------------------------")
        try:
            if callback is not None:
                if formats:
                    answers = cmd.answer.split()
                    if type(formats) != list:
                        formats = [formats] * len(answers)
                    if len(answers) != len(formats):
                        raise IndexError("Not enough formats specified for the number of answers")
                    answers = [fmt(ans) for ans, fmt in zip(answers, formats)]
                    if len(answers) == 1:
                        parameter = [answers[0]]
                    else:
                        parameter = answers
                else:
                    parameter = [cmd.answer]
                self.executeCallback(callback, parameter)
        except Exception as err:
            msg = "Traceback (most recent call last):\n"
            msg += "".join(traceback.format_list(stack))
            msg += str(err)
            print("----------------------------")
            print(msg)
            print("----------------------------")
        cmd.state = STATE_Empty
        with self.lock:
            if cmd in self.open_commands:
                self.open_commands.remove(cmd)

    def sendRequest(self, device, command, formats=float, parameter=None, callback=None):
        return self.sendCommand(device, command, parameter=parameter, formats=formats, wait=1, callback=callback)

    def getSpeedForDistance(self, distance, duration):
        return int(self.config["ZSpeedFactor"] * distance) / duration

    """ Set Functions """

    def setPos(self, a, wait=0):
        assert len(a) == 3
        for i in range(3):
            if a[i] is not None:
                self.setAxis(a[i], i, wait=wait)

    def setX(self, a, wait=0):
        return self.setAxis(a, 0, wait=wait)

    def setY(self, a, wait=0):
        return self.setAxis(a, 1, wait=wait)

    def setZ(self, a, wait=0, callback=None):
        return self.setAxis(a, 2, wait=wait, callback=callback)

    def setAxis(self, a, axis, wait=0, callback=None):
        #while self.moving[axis]:
        #    time.sleep(0.01)
        if self.config["InvertAxisX"] and axis == 0:
            a = self.memmap.x_max - a
        if self.config["InvertAxisY"] and axis == 1:
            a = self.memmap.y_max - a
        self.moving[axis] = True
        self.memmap.stage_pos[axis] = -1
        self.memmap.pos_planned[axis] = int(a)
        devices = [XAxis, YAxis, ZDrive]
        return self.sendCommand(devices[axis], 22, int(a), wait=wait, callback=callback)

    def setXOffset(self, offset, wait=0):
        return self.setAxisOffset(offset, 0, wait=wait)

    def setYOffset(self, offset, wait=0):
        return self.setAxisOffset(offset, 1, wait=wait)

    def setZOffset(self, offset, wait=0):
        return self.setAxisOffset(offset, 2, wait=wait)

    def setAxisOffset(self, offset, axis, wait=0):
        #while self.moving[axis]:
        #    time.sleep(0.01)
        if self.config["InvertAxisX"] and axis == 0:
            offset = -offset
        if self.config["InvertAxisY"] and axis == 1:
            offset = -offset
        self.moving[axis] = True
        self.memmap.pos_planned[axis] = self.memmap.stage_pos[axis]+int(offset)
        self.memmap.stage_pos[axis] = -1
        devices = [XAxis, YAxis, ZDrive]
        return self.sendCommand(devices[axis], 24, int(offset), wait=wait)

    def setRampSpeedX(self, ramp, wait=0):
        return self.sendCommand(XAxis, 30, ramp, wait=wait)

    def setRampSpeedY(self, ramp, wait=0):
        return self.sendCommand(YAxis, 30, ramp, wait=wait)

    def setRampSpeedZ(self, ramp, wait=0):
        return self.sendCommand(ZDrive, 30, ramp, wait=wait)

    def setXSpeed(self, speed, wait=0):
        return self.sendCommand(XAxis, 32, speed, wait=wait)

    def setYSpeed(self, speed, wait=0):
        return self.sendCommand(YAxis, 32, speed, wait=wait)

    def setZSpeed(self, speed, wait=0):
        return self.sendCommand(ZDrive, 32, speed, wait=wait)

    def setShutter(self, shutter_open, wait=0):
        if self.memmap.shutter == shutter_open:
            return True
        if self.memmap.mode > 100 and self.tirf:
            self.memmap.shutter = shutter_open
            self.tirf.write("%s%d\n" % ("A" if self.memmap.mode == 101 else "B", self.memmap.shutter))
            self.tirf.readline()
            if self.event_connect:
                self.event_connect(Lamp, 32, "1 %d" % int(shutter_open) )
            return
        self.memmap.shutter = -1
        self.memmap.shutter_planned = shutter_open
        return self.sendCommand(Lamp, 32, [1, int(shutter_open)], wait=wait)

    def setFluoMode(self, wait=0):
        return self.setMode(10, wait=wait)

    def setFluoChannel(self, channel, wait=0):
        if self.memmap.fluo_channel == channel:
            return True
        self.memmap.fluo_channel = -1
        return self.sendCommand(ILTurret, 22, channel, wait=wait)

    def setBFMode(self, wait=0):
        return self.setMode(0, wait=wait)

    def setPHMode(self, wait=0):
        return self.setMode(1, wait=wait)

    def setMode(self, mode, wait=0):
        if self.memmap.mode == mode:
            return True
        if self.memmap.mode > 100 and self.tirf is not None:  # turn old tirf mode off
            self.tirf.write("%s%d\n" % ("A" if self.memmap.mode == 101 else "B", 0))
            self.tirf.readline()
        if mode > 100 and self.tirf is not None:
            if self.memmap.mode < 10:
                self.sendCommand(Master, 29, 10)
                self.sendCommand(Lamp, 32, [1, 0])
            self.memmap.mode = mode
            self.tirf_channel = "A" if mode == 101 else "B"
            self.tirf.write("%s%d\n" % (self.tirf_channel, self.memmap.shutter))
            self.tirf.readline()
            if self.event_connect:
                self.event_connect(Master, 29, mode)
            return
        self.memmap.mode = -1
        self.memmap.mode_planned = mode
        return self.sendCommand(Master, 29, mode, wait=wait)

    def setObjective(self, index, wait=False):
        return self.sendCommand(ObjectiveTurret, 22, index, wait=wait)

    def setSpeedsToMax(self):
        try:
            max_xspeed = self.getMaxXSpeed()
        except self.MicroscopeError:
            max_xspeed = 1200000
            print('Could not determine max. speed in x-direction, using default value.')
        try:
            max_yspeed = self.getMaxYSpeed()
        except self.MicroscopeError:
            max_yspeed = 1200000
            print('Could not determine max. speed in y-direction, using default value.')

        self.setXSpeed(int(max_xspeed*self.config["speed_percentage"]))
        self.setYSpeed(int(max_yspeed*self.config["speed_percentage"]))
        self.setZSpeed(8820000)
        self.setRampSpeedX(self.config["ramp_speed"])
        self.setRampSpeedY(self.config["ramp_speed"])
        self.setRampSpeedZ(3612)

    def setApertureTL(self, value, wait=False):
        return self.sendCommand(ApertureDiaphragmTL, 22, value, wait=wait)

    def setFieldTL(self, value, wait=False):
        return self.sendCommand(FieldDiaphragmIL, 22, value, wait=wait)

    def setLamp(self, value, wait=False):
        return self.sendCommand(Lamp, 20, value, wait=wait)

    def setCoupler(self, value):
        self.config["Coupler"] = value
        with open(config_file, "r") as fp:
            text = fp.read()
        text = re.sub(r"Coupler\s*=[^\n]*", "Coupler = %.1f" % value, text)
        with open(config_file, "w") as fp:
            fp.write(text)

    """ Get Functions """

    def getMode(self):
        return self.sendRequest(Master, 28, formats=int)

    def getAllMethods(self, callback=None):
        return self.sendRequest(Master, 26, formats=str, callback=callback)

    def getFluoChannel(self):
        if self.memmap.fluo_channel != -1:
            return [self.memmap.fluo_channel, self.memmap.fluo_channel_name]
        return self.sendRequest(ILTurret, 23, formats=[int, str])

    def getFilters(self, callback=None):
        return [self.sendRequest(ILTurret, 27, parameter=["%d" % (i + 1)], formats=[int, str], callback=callback) for i in range(6)]

    def getMagnification(self):
        return self.sendRequest(ObjectiveTurret, 33, parameter=["a","1"], formats=int)[2]

    def getObjectiveIndex(self):
        return self.sendRequest(ObjectiveTurret, 23, formats=int)

    def getNumericalAperture(self):
        return self.sendRequest(ObjectiveTurret, 33, parameter=["a","2"], formats=float)[2]

    def getObjective(self):
        return self.sendRequest(ObjectiveTurret, 33, parameter=["a","3"], formats=int)[2]

    def getObjectives(self, callback=None):
        return [self.sendRequest(ObjectiveTurret, 33, parameter=["%d" % (i+1), "1"], formats=[int, int, str], callback=callback) for i in range(6)]

    def getPos(self, callback=None):
        self.temp_pos = [None, None, None]
        self.pos_query_finished = False
        if 1:#callback:
            def testFinished():
                for p in self.temp_pos:
                    if p is None:
                        return
                self.pos_query_finished = True
                if callback is not None:
                    self.executeCallback(callback, self.temp_pos)
            def setX(x):
                if self.config["InvertAxisX"]:
                    x = self.memmap.x_max - x
                self.temp_pos[0] = x
                testFinished()

            def setY(y):
                if self.config["InvertAxisY"]:
                    y = self.memmap.y_max - y
                self.temp_pos[1] = y
                testFinished()

            def setZ(z):
                self.temp_pos[2] = z
                testFinished()
            x = self.sendRequest(XAxis, 23, formats=int, callback=setX)
            y = self.sendRequest(YAxis, 23, formats=int, callback=setY)
            z = self.sendRequest(ZDrive, 23, formats=int, callback=setZ)
            if callback is not None:
                return
            while not self.pos_query_finished:
                pass
            return self.temp_pos
        x = self.sendRequest(XAxis, 23, formats=int)
        if self.config["InvertAxisX"]:
            x = self.memmap.x_max - x
        y = self.sendRequest(YAxis, 23, formats=int)
        if self.config["InvertAxisY"]:
            y = self.memmap.y_max - y
        z = self.sendRequest(ZDrive, 23, formats=int)
        return [x, y, z]

    def getZ(self, callback=None):
        return self.sendRequest(ZDrive, 23, formats=int, callback=callback)

    def getX(self, callback=None):
        return self.sendRequest(XAxis, 23, formats=int, callback=callback)

    def getY(self, callback=None):
        return self.sendRequest(YAxis, 23, formats=int, callback=callback)

    def getResolutionX(self, force=False, callback=None):
        if not force and not callback:
            return self.memmap.conv_x
        return self.sendRequest(XAxis, 34, callback=callback)

    def getResolutionY(self, force=False, callback=None):
        if not force and not callback:
            return self.memmap.conv_y
        return self.sendRequest(YAxis, 34, callback=callback)

    def getResolutionZ(self, force=False, callback=None):
        if not force and not callback:
            return self.memmap.conv_z
        return self.sendRequest(ZDrive, 42, callback=callback)

    def getMaxX(self, force=False, callback=None):
        if not force and not callback:
            return self.memmap.conv_x
        return self.sendRequest(XAxis, 29, callback=callback)

    def getMaxY(self, force=False, callback=None):
        if not force and not callback:
            return self.memmap.conv_y
        return self.sendRequest(YAxis, 29, callback=callback)

    def getMaxZ(self, force=False, callback=None):
        if not force and not callback:
            return self.memmap.conv_z
        return self.sendRequest(ZDrive, 56, callback=callback)

    def getXSpeed(self):
        return self.sendRequest(XAxis, 33)

    def getYSpeed(self):
        return self.sendRequest(YAxis, 33)

    def getMaxXSpeed(self):
        return self.sendRequest(XAxis, 36)

    def getMaxYSpeed(self):
        return self.sendRequest(YAxis, 36)

    def getZSpeed(self, wait=0):
        return self.sendRequest(ZDrive, 33)

    #is z-drive of stage moving?
    def getMovingZ(self):
        return self.sendRequest(ZDrive, 4, formats=int)[0]

    def getMovingX(self):
        return self.sendRequest(XAxis, 4, formats=int)[0]

    def getMovingY(self):
        return self.sendRequest(YAxis, 4, formats=int)[0]

    def getEffectiveMagnification(self):  # TODO implemented in server maybe move here
        return self.getMagnification()*self.config["Coupler"]

    def getCoupler(self):
        return self.config["Coupler"]

    def getApertureTL(self, callback=None):
        return self.sendRequest(ApertureDiaphragmTL, 23, formats=int, callback=callback)

    def getFieldTL(self, callback=None):
        return self.sendRequest(FieldDiaphragmIL, 23, formats=int, callback=callback)

    def getLamp(self, callback=None):
        return self.sendRequest(Lamp, 21, formats=int, callback=callback)

    def getMicroscopeName(self):
        return self.config["MicroscopeName"]

    def getMetadata(self):
        self.metadata = {}
        self.metadata["Coupler"] = float(self.config["Coupler"])

        self.metadata["Mode"] = int(self.memmap.mode)
        self.metadata["Channel"] = int(self.memmap.fluo_channel)

        self.metadata["StagePosition"] = self.memmap.stage_pos.tolist()

        # Objective
        self.metadata["Magnification"] = int(self.memmap.magnification)
        self.metadata["NumericalAperture"] = float(self.memmap.numerical_aperture)
        self.metadata["Objective"] = str(self.memmap.objective)

        # System
        self.metadata["ComputerName"] = socket.gethostname()
        self.metadata["MicroscopeName"] = self.config["MicroscopeName"]
        self.metadata["Time"] = time.strftime("%Y%m%d-%H%M%S", time.gmtime())+"-%06d" % ((time.time()-int(time.time()))*1e6)
        return self.metadata


if __name__ == '__main__':
    mic = microscope()
    #mic.sendCommand(XAxis, 22, 100)
