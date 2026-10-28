# -*- coding: utf-8 -*-
from __future__ import division, print_function

import qtawesome as qta
from qtpy import QtGui, QtCore, QtWidgets
import time

devices = {
52: "PortMagnification",
54: "FastFilterwheel",
56: "MA4Mirror",
60: "Docuport",
70: "Master",
71: "ZDrive",
72: "XAxis",
73: "YAxis",
74: "MicroscopeButtons",
75: "MicroscopeDisplay",
76: "ObjectiveTurret",
77: "Lamp",
78: "ILTurret",
79: "MagnificationChanger",
80: "SwitchablePrisms",
81: "FlappingCondenser",
82: "CondenserDisk",
84: "ApertureDiaphragmTL",
85: "DICTurret",
86: "ZHandwheel",
94: "FieldDiaphragmIL",
95: "ApertureDiaphragmIL",
96: "ZoomLensTL",
97: "CCWheel",
98: "Polarizer",
}

def getDeviceName(device):
    if device in devices:
        return "%02d  %s" % (device, devices[device])
    return "%02d" % device

states = {
0: "Empty",
1: "Written",
2: "Sent",
3: "Received",
}

STATE_Empty = 0
STATE_Written = 1
STATE_Sent = 2
STATE_Received = 3

def getStateName(state):
    return states[state]

import os, sys

from .MicroscopeClient import microscope

class MemmapViewer(QtWidgets.QWidget):
    def __init__(self, parent=None):
        global mic
        QtWidgets.QWidget.__init__(self)
        self.parent = parent

        # widget layout and elements
        self.setMinimumWidth(800)
        self.setMinimumHeight(400)
        self.setWindowTitle("Microscope Memmap Viewer")
        self.setWindowIcon(qta.icon("fa.eye"))

        self.layout = QtWidgets.QHBoxLayout(self)

        mic = microscope()

        self.tree = QtWidgets.QTreeView()
        self.layout.addWidget(self.tree)
        self.model = QtGui.QStandardItemModel(0, 0)

        self.items = {}

        # some settings for the tree
        self.tree.setUniformRowHeights(True)
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setModel(self.model)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.updateview)
        self.timer.start(100)
        self.updateview()
        self.updateview()

        for stack in mic.memmap.command_stacks:
            stack.locked = 0

    def updateview(self):
        print("update")

        # test
        if 0:
            for stack in mic.memmap.command_stacks:
                # lock the stack
                with stack.editLock:
                    # get the current command
                    command = stack.commands[stack.pointer_server]
                    # if the command is written by the client, send it
                    if command.state == STATE_Written:
                        # write the command to the serial interface
                        if command.parameter:
                            self.write("%02d%03d %s\r" % (command.device, command.command, command.parameter))
                        else:
                            self.write("%02d%03d\r" % (command.device, command.command))
                        print("written", "#%d" % command.index,
                              "%02d%03d %s\r" % (command.device, command.command, command.parameter))
                        # set the state to "sent"
                        command.state = STATE_Sent
                    # if the command takes too long, cancel the command due to timeout
                    elif command.state == STATE_Sent and time.time() - command.time > 60:
                        command.error = 3
                        command.state = STATE_Received
                        print("timeout", command.time, round(time.time() - command.time, 3), "s")

        index = -1
        for stack in mic.memmap.command_stacks:
            for command in stack.commands:
                index += 1
                row = self.setRow(index, "%d" % command.index,
                                  stack.locked,
                                  getStateName(command.state),
                                  getDeviceName(command.device),
                                  "%d" % command.command,
                                  command.parameter,
                                  command.answer,
                                  command.error,
                                  "%.3fs" % (time.time()-command.time)
                                  )
                if stack.locked:
                    row[0].setIcon(qta.icon("fa.lock", color="#F00"))
                else:
                    row[0].setIcon(qta.icon("fa.unlock"))
                self.setRowColor(row, QtGui.QColor(255, 255, 255))
                if command.index == stack.pointer_server:
                    self.setRowColor(row, QtGui.QColor(255, 128, 255))
                if command.index == stack.pointer_client:
                    self.setRowColor(row, QtGui.QColor(255, 255, 128))

    def setRowColor(self, row, color):
        for r in row:
            r.setBackground(color)

    def setRow(self, row, *args):
        if row in self.items:
            for item, arg in zip(self.items[row], args):
                item.setText(str(arg))
            return self.items[row]
        else:
            items = []
            for index, arg in enumerate(args):
                item = QtGui.QStandardItem(arg)
                item.setEditable(False)
                self.model.setItem(row, index, item)
                items.append(item)
            self.items[row] = items
        return items


def main():
    app = QtWidgets.QApplication(sys.argv)

    window = MemmapViewer()
    window.show()
    app.exec_()

if __name__ == '__main__':
    main()
