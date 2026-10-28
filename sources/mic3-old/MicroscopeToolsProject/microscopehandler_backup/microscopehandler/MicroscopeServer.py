# -*- coding: utf-8 -*-
from __future__ import print_function, division

import logging
import os
import re
import subprocess
import sys
import threading
import time

import psutil
import serial
from qtpy import QtCore, QtGui, QtWidgets

from .MicroscopeClient import microscope
from .includes.MemMap import MemMap

from .includes import killOldInstance, find_mic_port, getMicLogFile, MicMemMap

logging.basicConfig(filename=getMicLogFile(), level=logging.DEBUG,
                    format='%(asctime)s: ' + os.path.basename(__file__) + ' %(message)s')

config_file = os.path.join(os.path.dirname(__file__), "Microscope_Config.txt")

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


class MicroscopeServer(QtWidgets.QWidget):
    stream = ""
    ser = None

    def __init__(self, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.setWindowTitle('Microscope Server')

        self.trayIconMenu = QtWidgets.QMenu(self)

        showLogAction = QtWidgets.QAction("Show Log", self)
        showLogAction.triggered.connect(self.trayActionShowLog)
        self.trayIconMenu.addAction(showLogAction)
        self.log_process = None

        quitAction = QtWidgets.QAction("Quit", self)
        quitAction.triggered.connect(self.trayActionClose)
        self.trayIconMenu.addAction(quitAction)

        self.trayIcon = QtWidgets.QSystemTrayIcon(self)
        self.trayIcon.setToolTip("Microscope Server")
        self.trayIcon.setIcon(QtGui.QIcon("icons/CameraServer.ico"))
        self.trayIcon.setContextMenu(self.trayIconMenu)
        self.trayIcon.show()

        if killOldInstance(__file__, "microscope_server", "microscope_server_noconsole"):
            self.trayIcon.showMessage("Restart Microscope Server", "Shut down old server and start new one.")
            logging.info("Killed old server")
            time.sleep(1)

        # Load config
        self.config = dict(MicroscopePort=9998, mic_buffer_count=100)
        if os.path.exists(config_file):
            execfile(config_file, globals(), self.config)

        try:
            self.ConnectMicroscope()
        except:
            if self.ser is not None:
                self.DisconnectMicroscope()
            self.trayIcon.showMessage("No Microscope Connection",
                                      "Can't connect to microscope. Is it turned off or does it use the wrong port?")
            logging.error("ERROR: can't connect to microscope")

        self.CreateMemMap()

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.commandLoop)
        self.timer.start(5)

        logging.info("serving ...")

    """ gui actions """

    def trayActionShowLog(self):
        # kill the old log view
        if self.log_process is not None and self.log_process.pid in psutil.pids():
            self.log_process.kill()
        # start a new log view
        self.log_process = subprocess.Popen([sys.executable, "LogView.py", getMicLogFile(), "Microscope Log"])

    def trayActionClose(self):
        # kill the old log view
        if self.log_process is not None and self.log_process.pid in psutil.pids():
            self.log_process.kill()
        # hide the icon and terminate the script
        self.trayIcon.hide()
        sys.exit()

    def closeEvent(self, event):
        self.trayIcon.hide()

    """ connect/disconnect microscope """

    def ConnectMicroscope(self):
        port = find_mic_port()
        if port is not None:
            self.ser = serial.Serial(port, 19200, timeout=0.1)
            self.trayIcon.showMessage("Microscope Connection", "Connected to microscope.")
            logging.info('Serial connected')

            new_event_index = (self.memmap.index_written_event + 1) % len(self.memmap.events)
            evt = self.memmap.events[new_event_index]
            evt.device = 1
            evt.command = 0
            evt.answer = 0
            print("Send init")
            self.memmap.index_written_event = new_event_index
        else:
            logging.info('No microscope port found')

    def DisconnectMicroscope(self):
        self.ser.close()
        self.ser = None
        self.trayIcon.showMessage("Lost Microscope Connection",
                                  "Lost the connection to the microscope.\nIs it turned off?")
        logging.info('Serial disconnected')

    """ serial write and read """

    def write(self, x):
        """ write a command to the serial port """
        try:
            # write the command to the serial port
            self.ser.write(x)
        except Exception as err:
            print("exception", err)
            # if the connection is there but an error occurred, disconnect
            if self.ser is not None:
                self.DisconnectMicroscope()
            return False
        return True

        while True:
            try:
                # if the microscope is not connected try to connect
                if self.ser is None:
                    self.ConnectMicroscope()
                # write the command to the serial port
                self.ser.write(x)
            except Exception as err:
                print("exception", err)
                # if the connection is there but an error occurred, disconnect
                if self.ser is not None:
                    self.DisconnectMicroscope()
                # wait and than retry
                logging.info("no connection")
                time.sleep(2)
            else:
                # if writing was successful, exit the loop
                logging.info('SerialOut %s', x.strip())
                break

    def read(self):
        # Do we have received a full command yet?
        if self.stream.find("\r") == -1:
            # then listen
            try:
                # if the microscope is not connected try to connect
                if self.ser is None:
                    self.ConnectMicroscope()
                # read text from the serial port
                self.stream += self.ser.readline()
            except:
                # if the connection is there but an error occurred, disconnect
                if self.ser is not None:
                    self.DisconnectMicroscope()
                # wait
                logging.info("no connection")
                time.sleep(2)
        # Do we now have received a full command?
        if self.stream.find("\r") != -1:
            # Then split it from the stream
            answer, self.stream = self.stream.split("\r", 1)
            logging.info('SerialIn %s', answer)
            # return answer
            return answer

        return None

    """ command loop """

    def commandLoop(self):
        # read
        self.reading()
        # write
        self.writing()
        # read
        self.reading()

    def writing(self):
        """ test all the stacks if they have commands that have been written to the stack by the client,
            but have not been sent to the microscope by the server yet
        """

        # test all stacks
        for stack in self.memmap.command_stacks:
            # lock the stack
            with stack.editLock:
                # get the current command
                command = stack.commands[stack.pointer_server % len(stack.commands)]
                # if the command is written by the client, send it
                if command.state == STATE_Written:
                    # write the command to the serial interface
                    if command.parameter:
                        sent_string = "%02d%03d %s\r" % (command.device, command.command, command.parameter)
                    else:
                        sent_string = "%02d%03d\r" % (command.device, command.command)
                    # if the command was successfully sent to the serial port
                    if self.write(sent_string):
                        # print status
                        print("written", "#%d" % command.index, sent_string)
                        # set the state to "sent"
                        command.state = STATE_Sent
                # if the command takes too long, cancel the command due to timeout
                elif command.state == STATE_Sent:
                    if time.time() - command.time > 60:
                        command.error = 3
                        command.state = STATE_Received
                        stack.pointer_server = (stack.pointer_server + 1) % len(stack.commands)
                        print("timeout", command.time, round(time.time() - command.time, 3), "s")
                # if it is in a different state and there are more commands to be sent, increase counter
                # ideally we should never come here...
                else:
                    if stack.pointer_server != stack.pointer_client:
                        stack.pointer_server = (stack.pointer_server + 1) % len(stack.commands)

    def reading(self):
        """ read input from the microscope and try to match it with the commands that have been sent, or put them
            in the stack of events, if they are not associated with a command
        """
        raw_answer = self.read()
        if raw_answer is None or len(raw_answer) == 0:
            return
        # Split answer in components
        event, device, error, command, answer = re.match(r"(\$)?(\d\d)(\d)(\d\d)\s*(.*)\s*", raw_answer).groups()
        event = event is not None
        device = int(device)
        error = int(error)
        command = int(command)
        # if it is not an event
        if not event:
            # go thought the stacks
            for stack in self.memmap.command_stacks:
                # lock the stack
                with stack.editLock:
                    # get the current command
                    cmd = stack.commands[stack.pointer_server % len(stack.commands)]
                    if cmd.state == STATE_Sent and cmd.device == device and cmd.command == command:
                        # set the response in the command
                        cmd.error = error
                        cmd.answer = answer
                        cmd.state = STATE_Received
                        stack.pointer_server = (stack.pointer_server + 1) % len(stack.commands)
                        print("processed", "#%d" % cmd.index, round(time.time()-cmd.time, 3), "s")
                        break
            else:
                print("Unknown response", answer)
                return
            # print errors
            if error:
                print("########### an error has occurred", raw_answer)
        else:
            # events are added in the event list
            print("Event!")
            new_event_index = (self.memmap.index_written_event + 1) % len(self.memmap.events)
            evt = self.memmap.events[new_event_index]
            evt.device = device
            evt.command = command
            evt.answer = answer
            self.memmap.index_written_event = new_event_index

        answers = answer.split()
        if event:
            """ Update status """
            if command == 4:
                if device == XAxis:  # X moving status
                    self.memmap.moving_x = bool(int(answers[0]))
                if device == YAxis:  # Y moving status
                    self.memmap.moving_y = bool(int(answers[0]))
                if device == ZDrive:  # Z moving status
                    self.memmap.moving_z = bool(int(answers[0]))
            if device == Lamp and command == 33:  # shutter status
                self.memmap.shutter = bool(int(answers[1]))
                self.memmap.shutter_planned = -1
            if device == Master and command == 28:  # mode
                self.memmap.mode = int(answers[0])
                self.memmap.mode_planned = -1
            if device == ILTurret and command == 23:  # fluo channel
                self.memmap.fluo_channel = int(answers[0])
                self.memmap.fluo_channel_name = answers[1]
            if device == ObjectiveTurret and command == 33:
                if answers[1] == "1":
                    self.memmap.magnification = int(answers[2])
                if answers[1] == "3":
                    self.memmap.objective = int(answers[2])

    def CreateMemMap(self):
        logging.info("Create Mem Map ...")
        print("Create Mem Map Server ...")

        self.memmap = MicMemMap()

        logging.info("... done")

        # Call the microscope to initialize the memmap
        # this is done in the microscope because the microscope has all the commands
        mic = microscope()
        self.init_thread = threading.Thread(target=mic.initialize)
        self.init_thread.setDaemon(1)
        self.init_thread.start()


def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MicroscopeServer()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
    app = QtWidgets.QApplication(sys.argv)
    window = MicroscopeServer()
    sys.exit(app.exec_())
