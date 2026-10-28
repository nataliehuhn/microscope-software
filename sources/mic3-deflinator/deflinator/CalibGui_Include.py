# -*- coding: utf-8 -*-
from __future__ import division, print_function
import qtawesome as qta
import os, sys
import re
import glob
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt4 import NavigationToolbar2QT as NavigationToolbar
sys.path.insert(0, os.path.dirname(__file__))
from matplotlibwidget import MatplotlibWidget
from matplotlib import mlab
from scipy.optimize import fmin
import time
import xlrd
import xlwt
from xlutils.copy import copy

from qtpy import QtGui, QtCore, QtWidgets


class PlotGui(QtWidgets.QWidget):
    def __init__(self, parent=None):
        QtWidgets.QWidget.__init__(self)
        self.parent = parent

        # widget layout and elements
        self.setMinimumWidth(800)
        self.setMinimumHeight(400)
        self.setWindowTitle("Calibration")

        self.measurements = []
        self.measurement_number = 0

        layout_vert = QtWidgets.QVBoxLayout(self)

        layout_hor = QtWidgets.QHBoxLayout()
        layout_vert.addLayout(layout_hor)

        self.pbConfirm = QtWidgets.QPushButton('<-', self)
        self.pbConfirm.pressed.connect(self.back)
        QtWidgets.QShortcut(QtGui.QKeySequence("Left"), self, self.back)
        QtWidgets.QShortcut(QtGui.QKeySequence("Home"), self, self.first)
        layout_hor.addWidget(self.pbConfirm)

        self.pbDiscard = QtWidgets.QPushButton('->', self)
        self.pbDiscard.pressed.connect(self.next)
        QtWidgets.QShortcut(QtGui.QKeySequence("Right"), self, self.next)
        QtWidgets.QShortcut(QtGui.QKeySequence("End"), self, self.end)
        layout_hor.addWidget(self.pbDiscard)

        self.label_info = QtWidgets.QLabel('', self)
        layout_hor.addWidget(self.label_info)

        layout_hor.addStretch()

        self.pbDelete = QtWidgets.QPushButton('', self)
        self.pbDelete.setIcon(qta.icon("fa.trash"))
        self.pbDelete.setCheckable(True)
        QtWidgets.QShortcut(QtGui.QKeySequence("Del"), self, self.delete)
        self.pbDelete.pressed.connect(self.delete)
        layout_hor.addWidget(self.pbDelete)


        layout_hor = QtWidgets.QHBoxLayout()
        layout_vert.addLayout(layout_hor)
        self.plot = MatplotlibWidget(self)
        self.plot.figure.patch.set_facecolor([0, 1, 0, 0])
        layout_hor.addWidget(self.plot)
        self.plot.figure.clear()

        self.navi_toolbar = NavigationToolbar(self.plot, self)
        layout_vert.addWidget(self.navi_toolbar)

        # Create Axes object
        self.axes1 = self.plot.figure.add_subplot(111)

        self.plot_line, = self.axes1.plot([], [], "-")

        self.axes1.set_ylabel(u"deflection (µm)", fontsize=12)
        self.axes1.set_xlabel("time (s)", fontsize=12)

    def setFolder(self, folder, filename):
        self.folder = folder
        self.filename = filename
        os.chdir(folder)

        book = xlrd.open_workbook(filename, formatting_info=True)
        sh = book.sheet_by_index(0)
        row_headers = []
        for j in range(1, 3 * 6 + 1):
            try:
                row = sh.row(j)
            except IndexError:
                break
            row_headers.append(row[0].value[2:-2])
            print(row[0].value[2:-2])
        self.measurements = row_headers
        self.measurement_number = 0
        self.load_folder()

    def back(self):
        if self.measurement_number > 0:
            self.measurement_number -= 1
            self.load_folder()

    def next(self):
        if self.measurement_number < len(self.measurements) - 1:
            self.measurement_number += 1
            self.load_folder()

    def first(self):
        if self.measurement_number > 0:
            self.measurement_number = 0
            self.load_folder()

    def end(self):
        if self.measurement_number < len(self.measurements) - 1:
            self.measurement_number = len(self.measurements) - 1
            self.load_folder()

    def delete(self):
        path = self.measurements.pop(self.measurement_number)
        print(path, self.measurement_number)

        if 1:

            # Hier darf Delf spielen
            # lösche Zeilte mit dem Index self.measurement_number

            book = xlrd.open_workbook(filename, formatting_info=True)
            sheet = book.sheet_by_index(0)  # read only copy to introspect the file
            wb = copy(book)  # a writable copy (I can't read values out of this, only write to it)
            w_sheet = wb.get_sheet(0)

            w_sheet.write(self.measurement_number + 1 , 6, "No proper contraction")
            w_sheet.write(self.measurement_number + 1, 7, "")
            wb.save(filename)

            # Hier nicht mehr

        if self.measurement_number >= len(self.measurements):
            self.measurement_number = len(self.measurements)-1
        self.load_folder()

    def load_folder(self):
        path = self.measurements[self.measurement_number]
        path2 = path + ".npy"
        print("Loading folder", path)
        if not os.path.exists(path2):
            self.plot_line.set_xdata([])
            self.plot_line.set_ydata([])

        else:

            data = np.load(path2)  # Load the data from the file in green
            # data = np.load(r'w12.npy') #Load the data from the file in green
            time = data[0]
            distances = data[1]

            self.plot_line.set_xdata(time)
            self.plot_line.set_ydata(distances)

            self.axes1.set_xlim(0, time[-1])
            self.axes1.set_ylim(np.min(distances), np.max(distances))
        self.axes1.set_title(path)

        self.plot.draw()
        self.plot.figure.tight_layout()
        self.plot.draw()

    def keyPressEvent(self, event):
        print(event.key())

        if event.key() == QtCore.Qt.Key_Left:
            # @key Left: previous measurement
            self.back()
            return True
        if event.key() == QtCore.Qt.Key_Right:
            # @key Right: next measurement
            self.next()
            return True

        return False


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)

    #tw = TweezerFile(r"D:\Richard\test\tesdt4.tw")

    window = PlotGui()
    if 1:
        filename = QtWidgets.QFileDialog.getOpenFileName(None, "Save Path", "C:\\", "*.xls")
        if isinstance(filename, tuple):
            filename = str(filename[0])
        else:
            filename = str(filename)

        if filename is "":
            print("Schade dann halt nicht.")
            sys.exit()
        folder, name = os.path.split(filename)
        window.setFolder(folder, name)
    else:
        window.setFolder("D:\Delf\Software\Abenteuerland\ctrl_small", "0ctrl.xls")
    #window.LoadedFile(tw)
    window.show()
    app.exec_()
