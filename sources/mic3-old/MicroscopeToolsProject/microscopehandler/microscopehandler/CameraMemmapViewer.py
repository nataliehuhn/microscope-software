# -*- coding: utf-8 -*-
from __future__ import division, print_function

import sys

import qtawesome as qta
from qtpy import QtGui, QtCore, QtWidgets

from .CameraClient import Camera

states = {
0: "Empty",
1: "Written",
2: "Sent",
3: "Received",
}

def getStateName(state):
    return states[state]

class MemmapViewer(QtWidgets.QWidget):
    def __init__(self, parent=None):
        global mmc
        QtWidgets.QWidget.__init__(self)
        self.parent = parent

        # widget layout and elements
        self.setMinimumWidth(800)
        self.setMinimumHeight(400)
        self.setWindowTitle("Camera Memmap Viewer")
        self.setWindowIcon(qta.icon("fa.eye"))

        self.layout = QtWidgets.QHBoxLayout(self)

        mmc = Camera()

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

    def updateview(self):
        print("update")
        for index, command in enumerate(mmc.memmap.commands):
            row = self.setRow(index, "%d" % index,
                              getStateName(command.status),
                              command.function,
                              command.args,
                              command.response
                              )
            if command.locked:
                row[0].setIcon(qta.icon("fa.lock", color="#F00"))
            else:
                row[0].setIcon(qta.icon("fa.unlock"))
            self.setRowColor(row, QtGui.QColor(255, 255, 255))
            if index == mmc.memmap.current_command_index:
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
