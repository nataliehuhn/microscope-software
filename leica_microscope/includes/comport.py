from __future__ import print_function, division
import serial
import sys
import glob
import time
import logging


logger = logging.getLogger(__name__)



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


class _ReplyReader:
    """Assemble bounded CR-terminated replies across serial read timeouts."""

    def __init__(self, port):
        self.port = port
        self.pending = b""
        self.discarding = False

    def read(self, ser):
        self.pending += ser.read_until(b"\r")
        lines = []
        while b"\r" in self.pending:
            frame, self.pending = self.pending.split(b"\r", 1)
            if self.discarding or len(frame) > 4096:
                self.discarding = False
                logger.warning("Discarding oversized serial reply on %s", self.port)
                continue
            try:
                line = frame.decode("ascii").strip()
            except UnicodeDecodeError:
                logger.warning("Discarding non-ASCII serial reply on %s: %r", self.port, frame)
                continue
            if not line:
                continue
            if len(line) < 5 or not line[:5].isdigit():
                logger.warning("Discarding malformed serial reply on %s: %r", self.port, line)
                continue
            lines.append(line)
        if len(self.pending) > 4096:
            self.pending = b""
            self.discarding = True
        return lines


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
        reader = _ReplyReader(self.port)
        while time.perf_counter() < deadline:
            for line in reader.read(self.ser):
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
                try:
                    return apply_format(parameters.strip(), output_format)
                except ValueError:
                    logger.warning("Discarding invalid serial parameters on %s: %r", self.port, line)
        raise TimeoutError(
            "Timed out waiting for a complete valid reply to {} on {} (partial={!r})"
            .format(command.strip(), self.port, reader.pending[:80])
        )

    def send(self, command):
        """Send a command without waiting, reusing the open serial session."""
        if command[-1] != "\r":
            command += "\r"
        self.ser.write(command)

def send_command_and_wait(command_list, port, output_format=None, verbose=False, wait=True):
    single_command = not isinstance(command_list, (list, tuple))
    if single_command:
        command_list = [command_list]
        output_format = [output_format]
    if output_format is None:
        output_format = [None] * len(command_list)
    # Do not mutate callers' lists; tuples are supported as well.
    command_list = [command.rstrip("\r") + "\r" for command in command_list]
    if len(output_format) != len(command_list):
        raise ValueError("Each serial command needs one output format")
    if not command_list:
        return []
    command_codes = [split_code(command) for command in command_list]
    answers = [None] * len(command_list)
    answered = set()
    reader = _ReplyReader(port)
    with Connection(port) as ser:
        if verbose:
            print("Commands:", [c.strip() for c in command_list])
        for command in command_list:
            ser.write(command)
        if not wait:
            return
        deadline = time.perf_counter() + 5.0
        while time.perf_counter() < deadline:
            for line in reader.read(ser):
                if verbose:
                    print("Response:", line)
                device, error, cmd, parameters = split_code(line)
                if error == "9" and cmd in ("99", "98", "97"):
                    error_type = {"99": ComError, "98": IdError, "97": FuiError}[cmd]
                    raise error_type("Controller error: " + line, device, error, cmd, parameters)
                for i, (expected_device, _, expected_cmd, _) in enumerate(command_codes):
                    if i in answered or device != expected_device or cmd != expected_cmd:
                        continue
                    if device == "76" and cmd == "33":
                        # Objective property replies include objective and property IDs.
                        if len(line) < 9 or len(command_list[i]) < 9:
                            continue
                        if not (line[6:9] == command_list[i][6:9] or
                                (command_list[i][6] == "a" and line[8] == command_list[i][8])):
                            continue
                    if device == "78" and cmd == "27" and line[6:7] != command_list[i][6:7]:
                        continue
                    if error != "0":
                        error_type = {"1": ParError, "2": SequenceError,
                                      "3": FlowError, "9": UncError}.get(error, MicroscopeError)
                        raise error_type("Controller error for {}: {}".format(command_list[i].strip(), line),
                                         device, error, cmd, parameters)
                    if output_format[i] is not None and not parameters.strip():
                        continue
                    try:
                        value = apply_format(parameters.strip(), output_format[i])
                    except ValueError:
                        logger.warning("Discarding invalid serial parameters on %s: %r", port, line)
                        continue
                    answers[i] = value
                    answered.add(i)
                    if len(answered) == len(command_list):
                        return answers[0] if single_command else answers
                    break
    missing_indices = [i for i in range(len(command_list)) if i not in answered]
    missing = [command_list[i].strip() for i in missing_indices]
    if all(output_format[i] is None for i in missing_indices):
        # Original setters returned after the acknowledgement timeout. Keep
        # that behavior: callers still perform their normal movement/status
        # checks. Never replay a state-changing command because its ACK was lost.
        logger.warning("Missing command acknowledgement on %s: %s; continuing with normal status checks",
                       port, ", ".join(missing))
        return answers[0] if single_command else answers
    raise TimeoutError("Timed out waiting for complete valid replies on {}: {} (partial={!r})"
                       .format(port, ", ".join(missing), reader.pending[:80]))


def send_command(command, port):
    with Connection(port) as ser:
        ser.write(command)
