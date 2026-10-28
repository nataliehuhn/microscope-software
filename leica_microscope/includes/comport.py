from __future__ import print_function, division
import serial
import sys
import glob
import time



class Connection:
    def __init__(self, port):
        self.port = port

    def __enter__(self):
        # open the serial connection
        try:
            # if it opened successfully, its fine
            self.ser = serial.Serial(self.port, 19200, timeout=0.1)
        except serial.serialutil.SerialException:
            print("ERROR: could not connect to port", self.port, "keep trying.")
            # if not, we will try for some time
            for i in range(50):
                try:
                    # if it opened successfully, its fine
                    self.ser = serial.Serial(self.port, 19200, timeout=0.1)
                except serial.serialutil.SerialException:
                    # if not, sleep a bit and try again
                    time.sleep(0.1)
                    continue
                break
            # if we were not able to start the serial connection after multiple tries, give up
            else:
                raise serial.serialutil.SerialException

        # patch the write method to directly take a string and not bytes
        write = self.ser.write
        def write_new(data):
            write(data.encode('utf-8'))
        self.ser.write = write_new

        # patch the readline method to directly return a string and not bytes
        readline = self.ser.readline
        def readline_new():
            return readline().decode("utf-8")
        self.ser.readline = readline_new

        # return the connection
        return self.ser

    def __exit__(self, err, err2, err3):
        # close the connection
        self.ser.close()
        self.ser = None


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

def find_mic_port(port):
    if port is not None:
        try:
            with Connection(port) as s:
                line = s.readline()
                s.write("70080\r")
                line = s.readline()
            if line.startswith("70080") and int(line[5:]) == 1: #TODO
                #print("Found leica_microscope")
                return port
        except serial.serialutil.SerialException:
            pass

    ports = serial_ports()
    print("Serial ports", serial_ports())
    for port in ports:
        print("Trying port", port)
        with Connection(port) as s:
            line = s.readline()
            s.write("70080\r")
            line = s.readline()
        if line.startswith("70080") and int(line[5:]) == 1: #TODO
            return port
        else:
            pass
    return None


def apply_format(string, format):
    if format is None:
        return string
    if not isinstance(format, (list, tuple)):
        format = [format]
    result = [fmt(param) for fmt, param in zip(format, string.split()) if fmt is not None]
    if len(result) == 0:
        return None
    elif len(result) == 1:
        return result[0]
    return result

def split_code(code):
    return code[:2], code[2], code[3:5], code[5:]

class MicroscopeError(ValueError):
    def __init__(self, msg, device, error, command, parameters):
        self.device = device
        self.error = error
        self.command = command
        self.parameters = parameters
        super().__init__(msg)

class FlowError(MicroscopeError):
    pass

class ParError(MicroscopeError):
    pass

class SequenceError(MicroscopeError):
    pass

class UncError(MicroscopeError):
    pass

class FuiError(MicroscopeError):
    pass

class IdError(MicroscopeError):
    pass

class ComError(MicroscopeError):
    pass


class PersistentCommandSession:
    """Reuse one serial connection for low-latency repeated read commands."""

    def __init__(self, port):
        self.port = port
        self.connection = None
        self.ser = None

    def __enter__(self):
        self.connection = Connection(self.port)
        self.ser = self.connection.__enter__()
        self.ser.reset_input_buffer()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.connection is not None:
            self.connection.__exit__(exc_type, exc_val, exc_tb)
        self.ser = None
        self.connection = None

    def query(self, command, output_format=None, timeout=1.0):
        if command[-1] != "\r":
            command += "\r"
        expected_device, _, expected_command, _ = split_code(command)
        self.ser.write(command)
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            raw = self.ser.read_until(b"\r")
            if not raw:
                continue
            for line in raw.decode("utf-8").split("\r"):
                if not line.strip():
                    continue
                device, error, response_command, parameters = split_code(line)
                if device != expected_device or response_command != expected_command:
                    continue
                if error != "0":
                    if error == "1":
                        raise ParError(
                            "PAR_ERR for command {}".format(command.strip()),
                            device, error, response_command, parameters,
                        )
                    if error == "2":
                        raise SequenceError(
                            "SEQUENCE_ERR for command {}".format(command.strip()),
                            device, error, response_command, parameters,
                        )
                    if error == "3":
                        raise FlowError(
                            "FLOW_ERR for command {}".format(command.strip()),
                            device, error, response_command, parameters,
                        )
                    raise MicroscopeError(
                        "Microscope error for command {}".format(command.strip()),
                        device, error, response_command, parameters,
                    )
                if not parameters.strip() and output_format is not None:
                    continue
                return apply_format(parameters.strip(), output_format)
        raise TimeoutError("Timed out waiting for {}".format(command.strip()))

    def send(self, command):
        """Send a command without waiting, reusing the open serial session."""
        if command[-1] != "\r":
            command += "\r"
        self.ser.write(command)

def send_command_and_wait(command_list, port, output_format=None, verbose=False, wait=True):
    single_command = False

    if not isinstance(command_list, (list, tuple)):
        command_list = [command_list]
        if output_format is None:
            output_format = [None]
        else:
            output_format = [output_format]
        single_command = True

    if output_format is None:
        output_format = [None] * len(command_list)

    # ensure that all commands end with \r
    for i in range(len(command_list)):
        if command_list[i][-1] != "\r":
            command_list[i] += "\r"

    # the part before the first space is the command code, the rest are the paremeters
    command_codes = [split_code(command) for command in command_list]

    commands_answered = 0
    answers = [None] * len(command_list)

    while True:
        # open the connection
        with Connection(port) as ser:
            # log
            if verbose: print("Commands:", [c.strip() for c in command_list])
            # write the command to the port
            for command in command_list:
                ser.write(command)
            if wait is False:
                return
            # remember start time
            start_time = time.time()
            while time.time() - start_time < 5:
                # read the line
                line = ser.readline()
                # if the answer is empty, ignore it
                if line.strip() == "":
                    continue
                #
                lines = line.split("\r")
                for line in lines:
                    if line.strip() == "":
                        continue
                    if verbose: print("Response:", line)
                    device, error, cmd, parameters = split_code(line)
                    if error == "9":
                        if cmd == "99":
                            raise ComError(
                                f"COM_ERR occurred for command {line}", device, error, cmd, parameters)
                        if cmd == "98":
                            raise IdError(
                                f"ID_ERR occurred for command {line}", device, error, cmd, parameters)
                        if cmd == "97":
                            raise FuiError(
                                f"FUI_ERR occurred for command {line}", device, error, cmd, parameters)
                    for i in range(len(command_list)):
                        if device == command_codes[i][0] and cmd == command_codes[i][2] \
                                and ((device != "76" or cmd != "33") or (device == "76" and cmd == "33" and (line[6:9] == command_list[i][6:9] or (command_list[i][6] == "a" and line[8] == command_list[i][8]))))\
                                and ((device != "78" or cmd != "27") or (device == "78" and cmd == "27" and line[6:7] == command_list[i][6:7]))\
                                :
                            if error != "0":
                                if error == "1":
                                    raise ParError(f"PAR_ERR: wrong parameters supplied for command {command_list[i]}", device, error, cmd, parameters)
                                if error == "2":
                                    raise SequenceError(f"SEQUENCE_ERR occurred for command {command_list[i]}", device, error, cmd, parameters)
                                if error == "3":
                                    raise FlowError(f"FLOW_ERR occurred for command {command_list[i]}", device, error, cmd, parameters)
                                if error == "9":
                                    raise UncError(f"UNC_ERR occurred for command {command_list[i]}", device, error, cmd, parameters)
                            try:
                                answers[i] = apply_format(parameters.strip(), output_format[i])
                            except ValueError:
                                raise ValueError(f"Tried to format answer '{line}' to format {output_format[i]}")
                            commands_answered += 1
                            if verbose: print(commands_answered, len(answers))
                            if commands_answered == len(answers):
                                if single_command:
                                    return answers[0]
                                return answers
                            break

            #print("Timout try to reset the microscope")
            #ser.write("70007")
            #time.sleep(2)
            #continue
            break
        if verbose: print("timeout")

        if single_command:
            return answers[0]
        return answers


def send_command(command, port):
    with Connection(port) as ser:
        ser.write(command)
