from __future__ import division, print_function
import sys
import os
import numpy as np
import logging
import psutil
from MemMap import MemMap
import json
import glob
import serial

def NoArray(args):
    # convert arrays to lists, because json can't handle numpy arrays
    for i in range(len(args)):
        if isinstance(args[i], type(np.array([]))):
            args[i] = args[i].tolist()
    return args


def serialize(value):
    if isinstance(value, tuple):
        value = NoArray(list(value))
    return json.dumps(value)

def NoUnicode(args):
    for i in range(len(args)):
        if type(args[i]) == type(u'abc'):
            args[i] = str(args[i])
    return args

def deserialize(string):
    result = json.loads(string)
    try:
        result = NoUnicode(result)
    except:
        pass
    return result


def serial_ports():
    """ Lists serial port names

        :raises EnvironmentError:
            On unsupported or unknown platforms
        :returns:
            A list of the serial ports available on the system
    """
    if sys.platform.startswith('win'):
        ports = ['COM%s' % (i + 1) for i in range(256)]
    elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
        # this excludes your current terminal "/dev/tty"
        ports = glob.glob('/dev/tty[A-Za-z]*')
    elif sys.platform.startswith('darwin'):
        ports = glob.glob('/dev/tty.*')
    else:
        raise EnvironmentError('Unsupported platform')

    result = []
    for port in ports:
        try:
            s = serial.Serial(port)
            s.close()
            result.append(port)
        except (OSError, serial.SerialException):
            pass
    return result


def find_mic_port():
    ports = serial_ports()
    for port in ports:
        print("Trying port", port)
        s = serial.Serial(port, timeout=0.1)
        line = s.readline()
        s.write("70080\r")
        line = s.readline()
        s.close()
        if line.startswith("70080") and int(line[5:]) == 1:
            print("Found microscope")
            return port
        else:
            print("response:", line)
    return None


def restart():
    args = sys.argv[:]
    logging.info('Re-spawning %s' % ' '.join(args))

    args.insert(0, sys.executable)
    if sys.platform == 'win32':
        args = ['"%s"' % arg for arg in args]

    # os.chdir(_startup_cwd)
    os.execv(sys.executable, args)


def killOldInstance(filename, *args):
    """ kill instances of filename which are not the current process id (pid) """
    pid = os.getpid()
    count = 0
    for process in psutil.process_iter():
        try:
            if process.name().find("python") != -1:
                script_name = os.path.split(process.cmdline()[-1])[1]
                if (script_name == os.path.basename(filename) or script_name.startswith(args[0])) and process.pid != pid:
                    for child in process.children(recursive=True):
                        child.kill()
                    process.kill()
                    count += 1
                    logging.info("Killed pid %d (%s)", process.pid, script_name)
        except psutil.AccessDenied:
            pass
    return count


def ensureScriptIsRunning(python_name, start_name):
    # iterate though all processes and find all running python processes
    python_process = []
    found = False
    for process in psutil.process_iter():
        try:
            if process.name().find("python") != -1:
                python_process.append(os.path.split(process.cmdline()[-1])[1])
                script_name = os.path.split(process.cmdline()[-1])[1]
                if (script_name == os.path.basename(python_name[0]) or script_name.startswith(python_name[1])):
                    found = True
        except:
            pass

    # check if one of the python processes is the camera server
    if not found:
        # if it is not running, restart it
        print("%s not running" % python_name)
        print("Starting %s" % python_name)
        os.startfile(os.path.join(os.path.dirname(__file__), "..", start_name))
        print("%s started" % python_name)
        # time.sleep(10)  # Wait for server to setup
    else:
        print("%s already running" % python_name)


def print_revert(msg):
    print(msg, "\r" * len(msg), end="")


def getCamLogFile():
    output_path = os.path.join(os.getenv('APPDATA'), "Microscope")
    if not os.path.exists(output_path):
        os.mkdir(output_path)
    log_file = os.path.join(output_path, 'camera.log')
    if os.path.exists(log_file):
        with open(log_file, 'w') as fp:
            fp.write("")
    return log_file


def getMicLogFile():
    output_path = os.path.join(os.getenv('APPDATA'), "Microscope")
    if not os.path.exists(output_path):
        os.mkdir(output_path)

    log_file = os.path.join(output_path, 'microscope.log')
    if os.path.exists(log_file):
        with open(log_file, 'w') as fp:
            fp.write("")
    return log_file


class MicMemMap(MemMap):
    def __init__(self):
        output_path = os.path.join(os.getenv('APPDATA'), "Microscope")
        if not os.path.exists(output_path):
            os.mkdir(output_path)
        filename = os.path.join(output_path, "microscope.dat")

        _new_memmap = not os.path.exists(filename)

        buffer_count = 30
        buffer_count_event = 100

        layout = (
            dict(name="initialized", type="uint8"),

            dict(name="command_stacks", type="memmap", shape=(5,), layout=(
                dict(name="locked", type="int8"),
                dict(name="locked_time", type="float"),
                dict(name="pointer_server", type="uint8"),
                dict(name="pointer_client", type="uint8"),
                dict(name="index_sent_command", type="uint8"),
                dict(name="index_written_command", type="uint8"),
                dict(name="commands", type="memmap", shape=(buffer_count,), layout=(
                    dict(name="index", type="int8"),
                    dict(name="state", type="int8"),

                    dict(name="device", type="int8"),
                    dict(name="command", type="int8"),
                    dict(name="parameter", type="|S30"),

                    dict(name="error", type="int8"),
                    dict(name="answer", type="|S30"),

                    dict(name="time", type="float"),
                )))),
            dict(name="index_written_event", type="uint8"),
            dict(name="events", type="memmap", shape=(buffer_count_event,), layout=(
                dict(name="device", type="int8"),
                dict(name="command", type="int8"),
                dict(name="answer", type="|S30"),
            )),
            dict(name="mode", type="int8"),
            dict(name="fluo_channel", type="int8"),
            dict(name="fluo_channel_name", type="|S30"),
            dict(name="conv_x", type="float"),
            dict(name="conv_y", type="float"),
            dict(name="conv_z", type="float"),

            dict(name="stage_pos", type="uint16", shape=(3,)),
            dict(name="magnification", type="int8"),
            dict(name="numerical_aperture", type="float"),
            dict(name="objective", type="|S30"),
            dict(name="shutter", type="int8"),
            dict(name="shutter_planned", type="int8"),
            dict(name="mode_planned", type="int8"),

            dict(name="moving_x", type="int8"),
            dict(name="moving_y", type="int8"),
            dict(name="moving_z", type="int8"),

            dict(name="pos_planned", type="int8", shape=(3,)),
            dict(name="x_max", type="int32"),
            dict(name="y_max", type="int32"),
        )
        MemMap.__init__(self, filename, layout)
        self._new_memmap = _new_memmap

        # if the memmap is new, initialize it
        if _new_memmap:
            # iterate over all stacks
            for stack in self.command_stacks:
                with stack.editLock:
                    # set the indices to 0
                    stack.pointer_server = 0
                    stack.pointer_client = 0
                    # set the command to 0
                    for i, command in enumerate(stack.commands):
                        command.index = i
                        command.device = 0
                        command.state = 0

    def isNewMemmap(self):
        return self._new_memmap


class CamMemMap(MemMap):
    def __init__(self, height, width):
        output_path = os.path.join(os.getenv('APPDATA'), "Microscope")
        if not os.path.exists(output_path):
            os.mkdir(output_path)
        filename = os.path.join(output_path, "camera.dat")

        _new_memmap = not os.path.exists(filename)

        ring_buffer_count = 10
        property_count = 100

        layout = (
            dict(name="locked", type="uint8"),
            dict(name="locked_time", type="float"),
            dict(name="current_index", type="uint32"),
            dict(name="current_command_index", type="uint32"),
            dict(name="width", type="uint16"),
            dict(name="height", type="uint16"),
            dict(name="sequence", type="double"),
            dict(name="exposure", type="double"),
            dict(name="gain", type="float"),
            dict(name="blocking_process", type="int"),
            dict(name="binning", type="uint16"),
            dict(name="roi", type="uint16", shape=(4,)),
            dict(name="fps", type="float"),

            dict(name="images", type="memmap", shape=(ring_buffer_count,), layout=(
                dict(name="width", type="uint16"),
                dict(name="height", type="uint16"),
                dict(name="data", align=64, type="uint16", shape=(height, width)),
            )),
            dict(name="commands", type="memmap", shape=(ring_buffer_count,), layout=(
                dict(name="locked", type="uint8"),
                dict(name="function", type="|S1024"),
                dict(name="args", type="|S1024"),
                dict(name="status", type="int16"),
                dict(name="error", type="int16"),
                dict(name="response", type="|S1024"),
            )),
            dict(name="property_count", type="uint16"),
            dict(name="properties", type="memmap", shape=(property_count,), layout=(
                dict(name="name", type="|S1024"),
                dict(name="value", type="|S1024"),
                dict(name="allowed_values", type="|S1024"),
                dict(name="min", type="float"),
                dict(name="max", type="float"),
            )),
        )
        MemMap.__init__(self, filename, layout)
        self.width = width
        self.height = height
        self._new_memmap = _new_memmap

        # if the memmap is new, initialize it
        if _new_memmap:
            # set property count to 0
            self.property_count = 0

    def isNewMemmap(self):
        return self._new_memmap

    def saveToRingbuffer(self, img):
        # increase the buffer index
        new_index = self.current_index+1
        buffer_count = len(self.images)
        write_index = new_index % buffer_count
        # store the image in the memmap
        h, w = img.shape
        self.images[write_index].data[:h, :w] = img
        self.images[write_index].width = w
        self.images[write_index].height = h
        self.current_index = new_index

    def getImageAtPosition(self, index):
        # retrieve an image from the memory map
        image = self.images[index % len(self.images)]
        x, y, w, h = self.roi
        if self.binning == 0:
            self.binning = 1
        if self.binning != 1:
            w, h = int(w / self.binning), int(h / self.binning)
        return image.data[:h, :w]  # [:image.height,:image.width]