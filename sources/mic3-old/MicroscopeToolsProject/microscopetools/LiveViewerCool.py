# -*- coding: utf-8 -*-
from __future__ import division, print_function
import qtawesome as qta

if __name__ == "__main__":
    import sys, os
    from qtpy import QtGui, QtCore, QtWidgets
    # start the Qt application
    app = QtWidgets.QApplication(sys.argv)

    # Create and display the splash screen
    splash_pix = QtGui.QPixmap(os.path.join(os.path.dirname(__file__), 'icons', 'Splash.png'))
    splash = QtWidgets.QSplashScreen(splash_pix, QtCore.Qt.WindowStaysOnTopHint)
    splash.setMask(splash_pix.mask())
    splash.show()
    app.processEvents()

import sys, os, ctypes
from qtpy import QtCore, QtGui, QtWidgets
from matplotlibwidget import MatplotlibWidget
import matplotlib.pyplot as plt

from qimage2ndarray import array2qimage

import time
import numpy as np
import subprocess
import psutil

sys.path.insert(0, os.path.dirname(__file__))
from HelperFunctions import format_partial

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "qextendedgraphicsview"))
from QExtendedGraphicsView import QExtendedGraphicsView
from Tools import HelpText, GraphicsItemEventFilter

from microscopehandler.CameraClient import Camera, deserialize
from microscopehandler.MicroscopeClient import microscope

from ui_dialog import Ui_Dialog

icon_path = os.path.join(os.path.dirname(__file__), ".", "icons")

sensor_size = 6.45

mic = None
mmc = None

output_path = os.path.join(os.getenv('APPDATA'), "Microscope")
if not os.path.exists(output_path):
    os.mkdir(output_path)
positions_file = os.path.join(output_path, "Positions_tmp.txt")


def SetValueNoSignal(widget, value):
    widget.blockSignals(True)
    if value > widget.maximum():
        widget.setMaximum(value)
    widget.setValue(value)
    widget.blockSignals(False)


class ModuleObjective(QtWidgets.QGroupBox):

    def __init__(self, parent, layout):
        QtWidgets.QWidget.__init__(self)
        self.parent = parent
        layout.addWidget(self)
        self.setTitle("Objectives")

        self.layout = QtWidgets.QGridLayout()
        self.setLayout(self.layout)
        self.magnifications = ["-"]*6
        self.buttons = []

        self.index = 0

        for i in range(6):
            button = QtWidgets.QPushButton("%s" % self.magnifications[i])
            button.setCheckable(True)
            button.setDisabled(True)
            button.clicked.connect(lambda x, i=i: self.buttonClicked(i))
            self.layout.addWidget(button, i // 3, i % 3)
            self.buttons.append(button)

        self.parent.signal_objective_changed.connect(self.updateStatus)
        self.parent.signal_init.connect(self.init)
        self.init()

    def init(self):
        print("self.init")
        mic.getObjectives(callback=self.initButtons)
        mic.sendRequest(76, 33, parameter=["a", "1"], formats=[int, int, int], callback=self.updateStatus)

    def initButtons(self, index, value, magnifications):
        try:
            magnifications = int(magnifications)
        except ValueError:
            return
        self.magnifications[index-1] = magnifications
        self.buttons[index-1].setText("%d x" % magnifications)
        self.buttons[index-1].setDisabled(False)

    def buttonClicked(self, i):
        print("Setting objective to %d (%d x)" % (i + 1, self.magnifications[i]))
        self.updateButtons()
        mic.setObjective(i + 1, wait=False)

    def updateStatus(self, index, value, magnification):
        self.setTitle("Objectives %d x" % magnification)
        self.index = index
        self.updateButtons()

    def updateButtons(self):
        for button in self.buttons:
            button.setChecked(False)
        if self.index:
            self.buttons[self.index-1].setChecked(True)


class ModuleMethods(QtWidgets.QGroupBox):

    def __init__(self, parent, layout):
        QtWidgets.QWidget.__init__(self)
        self.parent = parent
        layout.addWidget(self)
        self.setTitle("Methods")

        self.layout = QtWidgets.QGridLayout()
        self.setLayout(self.layout)
        self.buttons = []
        self.buttons_by_mode = {}
        self.index = -1
        self.methods_names = ["TL BF", "TL PH", "TL DF", "TL DIC", "TL POL", "IL BF", "IL OBL", "IL DF", "IL DIC",
                              "IL POL", "FLUO", "FLUO/PH", "FLUO/DIC", "BF/BF"]#, "nn", "nn"]

        self.parent.signal_mode_changed.connect(self.updateStatus)
        self.parent.signal_init.connect(self.init)
        self.init()

    def init(self):
        mic.getAllMethods(callback=self.initButtons)
        mic.sendRequest(70, 28, formats=[int], callback=self.updateStatus)

    def initButtons(self, methods):
        self.methods = [i == "1" for i in methods[::-1]]

        for button in self.buttons:
            button.setParent(None)
        self.buttons = []
        self.buttons_by_mode = {}
        for i in range(len(self.methods_names)):
            if self.methods[i]:
                button = QtWidgets.QPushButton(self.methods_names[i])
                button.setCheckable(True)
                button.clicked.connect(lambda x, i=i: self.buttonClicked(i))
                self.layout.addWidget(button, len(self.buttons)//3, len(self.buttons)%3)
                self.buttons.append(button)
                self.buttons_by_mode[i] = button
        self.updateButtons()

    def buttonClicked(self, i):
        print("Setting methods to %s (%d)" % (self.methods_names[i], i))
        self.updateButtons()
        mic.setMode(i, wait=False)

    def updateStatus(self, mode):
        self.setTitle("Methods %s" % self.methods_names[mic.memmap.mode])
        self.index = mode
        self.updateButtons()

    def updateButtons(self):
        for button in self.buttons:
            button.setChecked(False)
        if self.index in self.buttons_by_mode:
            self.buttons_by_mode[self.index].setChecked(True)


class ModuleIntensity(QtWidgets.QGroupBox):

    def __init__(self, parent, layout):
        QtWidgets.QWidget.__init__(self)
        self.parent = parent
        layout.addWidget(self)
        self.setTitle("Intensity")

        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)
        labels = ["Aperture", "Field", "Intensity"]
        #max_values = [24, 12, mic.getLampMax()] SHIZZLE
        max_values = [24, 12, 255]
        min_values = [1, 1, 0]

        self.sliders = []
        self.spinBoxes = []
        for i in range(3):
            self.layout.addWidget(QtWidgets.QLabel(labels[i]))
            layout = QtWidgets.QHBoxLayout()
            self.layout.addLayout(layout)

            slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            layout.addWidget(slider)

            spinBox = QtWidgets.QSpinBox()
            layout.addWidget(spinBox)

            self.sliders.append(slider)
            self.spinBoxes.append(spinBox)

            slider.setDisabled(True)
            spinBox.setDisabled(True)

            slider.sliderReleased.connect(lambda i=i, slider=slider: self.valueChanged(slider.value(), i))
            spinBox.valueChanged.connect(lambda v, i=i: self.valueChanged(v, i))

            slider.setRange(min_values[i], max_values[i])
            spinBox.setRange(min_values[i], max_values[i])

        spinBox.setSingleStep(10)

        self.parent.signal_aperture_changed.connect(lambda value: self.initSlider(value, 0))
        self.parent.signal_field_changed.connect(lambda value: self.initSlider(value, 1))
        self.parent.signal_lamp_changed.connect(lambda value: self.initSlider(value, 2))

        self.parent.signal_init.connect(self.init)
        self.init()

    def init(self):
        mic.getApertureTL(callback=lambda value: self.initSlider(value, 0))
        mic.getFieldTL(callback=lambda value: self.initSlider(value, 1))
        mic.getLamp(callback=lambda value: self.initSlider(value, 2))

    def initSlider(self, value, i):
        SetValueNoSignal(self.sliders[i], value)
        SetValueNoSignal(self.spinBoxes[i], value)
        self.sliders[i].setDisabled(False)
        self.spinBoxes[i].setDisabled(False)

    def valueChanged(self, value, i):
        if not self.sliders[i].isEnabled() or not self.spinBoxes[i].isEnabled():
            return
        SetValueNoSignal(self.sliders[i], value)
        SetValueNoSignal(self.spinBoxes[i], value)
        if i == 0:
            print("Set Aperture to", value)
            mic.setApertureTL(value)
        if i == 1:
            print("Set Field to", value)
            mic.setFieldTL(value)
        if i == 2:
            print("Set Lamp to", value)
            mic.setLamp(value)


class ModuleFilters(QtWidgets.QGroupBox):

    def __init__(self, parent, layout):
        QtWidgets.QWidget.__init__(self)
        self.parent = parent
        layout.addWidget(self)
        self.setTitle("Filters")

        self.layout = QtWidgets.QGridLayout()
        self.setLayout(self.layout)
        self.filters = ["-"]*6
        self.buttons = []

        self.index = 0

        for i in range(6):
            button = QtWidgets.QPushButton("%s" % self.filters[i])
            button.setCheckable(True)
            button.setDisabled(True)
            button.clicked.connect(lambda x, i=i: self.buttonClicked(i))
            self.layout.addWidget(button, i // 3, i % 3)
            self.buttons.append(button)

        self.parent.signal_filter_changed.connect(self.updateStatus)
        self.parent.signal_init.connect(self.init)
        self.init()

    def init(self):
        mic.getFilters(callback=self.initButtons)
        mic.sendRequest(78, 23, formats=[int, str], callback=self.updateStatus)

    def initButtons(self, index, filter):
        if filter == "-0" or filter == "-1" or filter == "EMP1":
            return
        self.filters[index-1] = filter
        self.buttons[index-1].setText(filter)
        self.buttons[index-1].setDisabled(False)

    def buttonClicked(self, i):
        print("Setting filter to %d (%s)" % (i + 1, self.filters[i]))
        self.updateButtons()
        mic.setFluoChannel(i + 1, wait=False)

    def updateStatus(self, index, filter):
        self.setTitle("Filters %s" % filter)
        self.index = index
        self.updateButtons()

    def updateButtons(self):
        for button in self.buttons:
            button.setChecked(False)
        if self.index:
            self.buttons[self.index-1].setChecked(True)

class ModulePosition(QtWidgets.QGroupBox):
    z_conversion = 0.003800
    x_conversion = 0.13818360
    y_conversion = 0.13818360

    def __init__(self, parent, layout):
        QtWidgets.QWidget.__init__(self)
        self.parent = parent
        layout.addWidget(self)
        self.setTitle("Position")

        self.layout_main = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout_main)
        self.layout = QtWidgets.QHBoxLayout()
        self.layout_main.addLayout(self.layout)
        self.layout2 = QtWidgets.QHBoxLayout()
        self.layout_main.addLayout(self.layout2)
        self.max_values = [919500, 600750, 9999999]
        labels = ["x", "y", "z"]
        self.conversion = [self.x_conversion, self.y_conversion, self.z_conversion]

        mic.getResolutionX(callback=lambda value: self.setConversion(value, 0))
        mic.getResolutionY(callback=lambda value: self.setConversion(value, 1))
        mic.getResolutionZ(callback=lambda value: self.setConversion(value, 2))

        self.plot = MatplotlibWidget()
        self.layout.addWidget(self.plot)

        self.sliders = []
        self.spinBoxes = []
        for i in range(3):
            if i == 2:
                slider = QtWidgets.QSlider(QtCore.Qt.Vertical)
                self.layout.addWidget(slider)
            spinBox = QtWidgets.QSpinBox()
            self.layout2.addWidget(spinBox)
            spinBox.setSuffix(" um")
            spinBox.setPrefix(labels[i]+" ")

            if i == 2:
                slider.setMaximum(self.max_values[i]*self.z_conversion)
            spinBox.setMaximum(self.max_values[i]*self.z_conversion)

            if i == 2:
                self.sliders.append(slider)
            self.spinBoxes.append(spinBox)
            if i == 2:
                slider.setDisabled(True)
                slider.sliderReleased.connect(lambda i=i, slider=slider: self.valueChanged(slider.value(), i))
            spinBox.setDisabled(True)
            spinBox.valueChanged.connect(lambda v, i=i: self.valueChanged(v, i))

        spinBox.setSingleStep(10)

        self.parent.signal_x_changed.connect(lambda value: self.initSlider(value, 0))
        self.parent.signal_y_changed.connect(lambda value: self.initSlider(value, 1))
        self.parent.signal_z_changed.connect(lambda value: self.initSlider(value, 2))

        self.plot.figure.patch.set_facecolor([0, 1, 0, 0])
        self.plot.figure.clear()
        ax = self.plot.figure.add_axes([0, 0, 1, 1])
        #self.plot.setMinimumHeight(50)
        #self.plot.setMaximumHeight(50)
        self.plot_line, = self.plot.figure.gca().plot(0, 0, 'r+', ms=10)
        self.plot_line2, = self.plot.figure.gca().plot([], [], 'bx', ms=5)
        self.plot_line3, = self.plot.figure.gca().plot([0, 0, 0, 0, 0], [0, 0, 0, 0, 0], 'k-', ms=5)
        # ax = self.plot.figure.gca()
        ax.spines['top'].set_visible(False)
        ax.spines['bottom'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.set_yticks([])
        ax.set_xticks([])
        ax.set_xlim(919500, 0)
        ax.set_ylim(600750, 0)
        circle1 = plt.Circle((np.mean([276665, 188642]), np.mean([194082, 106795])), (276665-188642)/2, color='lightgray', ec="gray")
        ax.add_artist(circle1)
        self.plot.figure.axes[0].set_aspect('equal', 'box')
        self.ax = ax

        self.parent.signal_init.connect(self.init)
        self.init()

        mic.getMaxX(callback=lambda value: self.setMax(value, 0))
        mic.getMaxY(callback=lambda value: self.setMax(value, 1))
        mic.getMaxZ(callback=lambda value: self.setMax(value, 2))

        #ax.set_aspect('equal', 'datalim')

        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)
        self.layout_main.addWidget(line)

        self.positions = []
        self.list = QtWidgets.QListWidget()
        #self.list.itemSelectionChanged.connect(self.changePosition)
        self.layout_main.addWidget(self.list)
        button_layout = QtWidgets.QHBoxLayout()
        self.layout_main.addLayout(button_layout)
        self.button_add = QtWidgets.QPushButton("store")
        self.button_add.clicked.connect(self.addPosition)
        button_layout.addWidget(self.button_add)
        self.button_clear = QtWidgets.QPushButton("clear")
        self.button_clear.clicked.connect(self.deletePosition)
        button_layout.addWidget(self.button_clear)
        self.button_goto = QtWidgets.QPushButton("goto")
        self.button_goto.clicked.connect(self.gotoPosition)
        button_layout.addWidget(self.button_goto)

        button_layout = QtWidgets.QHBoxLayout()
        self.layout_main.addLayout(button_layout)
        self.button_save = QtWidgets.QPushButton("Save Pos File")
        self.button_save.clicked.connect(self.ButtonSave)
        button_layout.addWidget(self.button_save)
        self.button_load = QtWidgets.QPushButton("Load Pos File")
        self.button_load.clicked.connect(self.ButtonLoad)
        button_layout.addWidget(self.button_load)

        self.loadFile(positions_file)

        self.parent.signal.connect(self.updateStatus)
        self.updateList()

    def init(self):
        mic.getX(callback=lambda value: self.initSlider(value, 0))
        mic.getY(callback=lambda value: self.initSlider(value, 1))
        mic.getZ(callback=lambda value: self.initSlider(value, 2))

    def setConversion(self, value, index):
        self.conversion[index] = value

    def setMax(self, value, index):
        self.max_values[index] = value
        if index == 2:
            self.sliders[0].setMaximum(value * self.conversion[index])
        if index == 0:
            self.ax.set_xlim(value, 0)
            #self.ax.set_xlim(276665, 188642)
        if index == 1:
            self.ax.set_ylim(value, 0)
            #self.ax.set_ylim(194082, 106795)
        self.spinBoxes[index].setMaximum(value * self.conversion[index])

    def addPosition(self):
        mic.getPos(callback=self.storePosition)

    def storePosition(self, x, y, z):
        position = [x, y, z]
        selections = self.list.selectedItems()
        if len(selections) == 0 or self.list.currentRow() == self.list.count() - 1:
            self.positions.append(position)
        else:
            self.positions[self.list.currentRow()] = position
        self.updateList()

    def deletePosition(self):
        selections = self.list.selectedItems()
        if len(selections) == 0 or self.list.currentRow() == self.list.count() - 1:
            pass
        else:
            index = self.list.currentRow()
            self.positions.pop(self.list.currentRow())
            self.updateList()
            if index == self.list.count() - 1 and index != 0:
                index -= 1
            self.list.setCurrentRow(index)

    def gotoPosition(self):
        selections = self.list.selectedItems()
        if len(selections) == 0 or self.list.currentRow() == self.list.count() - 1:
            pass
        else:
            index = self.list.currentRow()
            mic.setPos(self.positions[index])

    def updateList(self):
        self.list.clear()
        for index, position in enumerate(self.positions):
            item = QtWidgets.QListWidgetItem(qta.icon("fa.crosshairs"), "%2d (x: %6d, y: %6d, z: %6d)" % (index, position[0], position[1], position[2]), self.list)
        item = QtWidgets.QListWidgetItem(qta.icon("fa.plus"), "free slot", self.list)
        self.plot_line2.set_data([p[0] for p in self.positions], [p[1] for p in self.positions])
        self.plot.draw()
        self.saveFile(positions_file)

    def ButtonSave(self):
        if len(self.positions) == 0:
            detour = QtWidgets.QMessageBox.question(self,
                                                    "Save empty file?",
                                                    "No positions have been saved yet. Do you want to save an empty file?",
                                                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if detour == QtWidgets.QMessageBox.No:
                return False
            elif detour == QtWidgets.QMessageBox.Yes:
                pass
        filename = QtWidgets.QFileDialog.getSaveFileName(self, "Save Positions", "", "Position Files (*.txt)")
        if isinstance(filename, tuple):
            filename = str(filename[0])
        else:
            filename = str(filename)
        if filename:
            self.saveFile(filename)

    def saveFile(self, filename):
        print("Saving:", filename)
        np.savetxt(filename, self.positions, fmt="%d")

    def ButtonLoad(self):
        fileName = QtWidgets.QFileDialog.getOpenFileName(self, "Open Positions", "", "Position Files (*.txt)")
        if isinstance(fileName, tuple):
            filename = str(fileName[0])
        else:
            filename = str(fileName)
        if os.path.exists(fileName):
            self.loadFile(fileName)

    def loadFile(self, fileName):
        print("Loading:", fileName)
        try:
            positions = np.loadtxt(fileName)
        except IOError:
            self.positions = ()
            return
        if len(positions.shape) == 1 and positions.shape[0] == 3:
            positions = positions.reshape(1, 3)
        self.positions = positions.tolist()
        self.updateList()

    def initSlider(self, value, i):
        if i == 0:
            w = 1344*6.45/5 / self.conversion[i]
            self.plot_line.set_xdata([value])
            self.plot_line3.set_xdata([value-w/2, value-w/2, value+w/2, value+w/2, value-w/2])
            self.plot.draw()
        if i == 1:
            self.plot_line.set_ydata([value])
            h = 1024 * 6.45 / 5 / self.conversion[i]
            self.plot_line3.set_ydata([value - h / 2, value + h / 2, value + h / 2, value - h / 2, value - h / 2])
            self.plot.draw()
        if i == 2:
            SetValueNoSignal(self.sliders[0], value * self.conversion[i])
        SetValueNoSignal(self.spinBoxes[i], int(value * self.conversion[i]))
        if i == 2:
            self.sliders[0].setDisabled(False)
        self.spinBoxes[i].setDisabled(False)

    def valueChanged(self, value, i):
        if not self.spinBoxes[i].isEnabled():
            return
        SetValueNoSignal(self.spinBoxes[i], value)
        if i == 0:
            print("Set X to", value)
            mic.setX(int(value / self.conversion[i]))
        if i == 1:
            print("Set Y to", value)
            mic.setY(int(value / self.conversion[i]))
        if i == 2:
            print("Set Z to", value, int(value/self.conversion[i]))
            mic.setZ(int(value/self.conversion[i]))
            SetValueNoSignal(self.sliders[0], value)

    def updateStatus(self):
        self.setTitle("Position")


class ModuleCoupler(QtWidgets.QGroupBox):

    def __init__(self, parent, layout):
        QtWidgets.QWidget.__init__(self)
        self.parent = parent
        layout.addWidget(self)
        self.setTitle("Coupler")
        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)
        self.setMinimumWidth(200)

        self.layout1 = QtWidgets.QHBoxLayout()
        self.layout.addLayout(self.layout1)

        self.button_05 = QtWidgets.QPushButton("0.5")
        self.button_05.setCheckable(True)
        self.layout1.addWidget(self.button_05)

        self.button_10 = QtWidgets.QPushButton("1.0")
        self.button_10.setCheckable(True)
        self.layout1.addWidget(self.button_10)

        self.button_05.clicked.connect(lambda x: self.setCoupler(0.5))
        self.button_10.clicked.connect(lambda x: self.setCoupler(1.0))

        self.updateStatus()

    def setCoupler(self, value):
        mic.setCoupler(value)
        self.updateStatus()
        self.parent.signal_coupler_changed.emit(value)

    def updateStatus(self):
        self.setTitle("Coupler: %.1f" % mic.getCoupler())
        if mic.getCoupler() == 0.5:
            self.button_05.setChecked(True)
            self.button_10.setChecked(False)
        else:
            self.button_05.setChecked(False)
            self.button_10.setChecked(True)


class ModuleExposure(QtWidgets.QGroupBox):
    nochange = False

    def __init__(self, parent, layout):
        QtWidgets.QWidget.__init__(self)
        self.parent = parent
        layout.addWidget(self)
        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)
        labels = ["Exposure", "Gain"]
        max_values = [1000, 255]
        max_values2 = [10000, 255]
        min_values = [1, 0]

        self.sliders = []
        self.spinBoxes = []
        for i in range(2):
            self.layout.addWidget(QtWidgets.QLabel(labels[i]))
            layout = QtWidgets.QHBoxLayout()
            self.layout.addLayout(layout)
            slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            layout.addWidget(slider)
            if i == 0:
                spinBox = QtWidgets.QDoubleSpinBox()
            else:
                spinBox = QtWidgets.QSpinBox()
            layout.addWidget(spinBox)

            slider.setRange(min_values[i], max_values[i])
            spinBox.setRange(min_values[i], max_values2[i])

            self.sliders.append(slider)
            self.spinBoxes.append(spinBox)
            if i == 0:
                slider.setValue(mmc.memmap.exposure)
                spinBox.setSingleStep(0.1)
                spinBox.setValue(mmc.memmap.exposure)
            if i == 1:
                slider.setValue(mmc.memmap.gain)
                spinBox.setValue(mmc.memmap.gain)
                spinBox.setSingleStep(10)
            slider.sliderReleased.connect(lambda i=i, slider=slider: self.valueChanged(slider.value(), i))
            spinBox.valueChanged.connect(lambda v, i=i: self.valueChanged(v, i))

        self.parent.signal.connect(self.updateStatus)
        self.updateStatus()

    def valueChanged(self, value, i):
        if self.nochange:
            return
        self.nochange = True
        self.sliders[i].setValue(value)
        self.spinBoxes[i].setValue(value)
        if i == 0:
            print("Set Exposure to", value)
            mmc.setExposure(value)
        if i == 1:
            print("Set Gain to", value)
            mmc.setGainValue(value)
        self.nochange = False
        self.updateStatus()

    def updateStatus(self):
        self.setTitle("Exposure")


class ModuleROI(QtWidgets.QGroupBox):
    nochange = False
    last_binning = 1

    def __init__(self, parent, layout):
        QtWidgets.QWidget.__init__(self)
        self.parent = parent
        layout.addWidget(self)
        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)
        labels = ["ROI Height", "Binning"]
        max_values = [1024, 8]
        min_values = [8, 1]

        self.sliders = []
        self.spinBoxes = []
        for i in range(2):
            self.layout.addWidget(QtWidgets.QLabel(labels[i]))
            layout = QtWidgets.QHBoxLayout()
            self.layout.addLayout(layout)
            slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            layout.addWidget(slider)
            spinBox = QtWidgets.QSpinBox()
            layout.addWidget(spinBox)

            slider.setRange(min_values[i], max_values[i])
            spinBox.setRange(min_values[i], max_values[i])

            if i == 0:
                print(mmc.memmap.roi, mmc.memmap.binning)
                slider.setValue(mmc.memmap.roi[3])
                spinBox.setValue(mmc.memmap.roi[3])
            if i == 1:
                slider.setValue(mmc.memmap.binning)
                spinBox.setValue(mmc.memmap.binning)

            self.sliders.append(slider)
            self.spinBoxes.append(spinBox)
            slider.sliderReleased.connect(lambda i=i, slider=slider: self.valueChanged(slider.value(), i))
            spinBox.valueChanged.connect(lambda v, i=i: self.valueChanged(v, i))

        self.parent.signal.connect(self.updateStatus)
        self.updateStatus()

    def valueChanged(self, value, i):
        if self.nochange:
            return
        self.nochange = True
        if i == 0:
            print("Set ROI height to", value)
            crop = 1024 - value
            mmc.setROI(0, crop / 2, 1344, 1024 - crop)
        if i == 1:
            if value == 3:
                if self.last_binning > value:
                    value = 2
                else:
                    value = 4
            if value == 5 or value == 6 or value == 7:
                if self.last_binning > value:
                    value = 4
                else:
                    value = 8
            print("Set Binning to", value)
            mmc.setBinning(value)
            self.last_binning = value
        self.sliders[i].setValue(value)
        self.spinBoxes[i].setValue(value)
        self.nochange = False
        self.updateStatus()

    def updateStatus(self):
        self.setTitle("ROI")


class ModuleHistogram(QtWidgets.QGroupBox):

    def __init__(self, parent, layout, bitDepth):
        QtWidgets.QWidget.__init__(self)
        self.parent = parent
        layout.addWidget(self)
        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)
        self.setMaximumHeight(100)

        self.bitDepth = bitDepth

        self.plot = MatplotlibWidget()
        self.plot.figure.patch.set_facecolor([0, 1, 0, 0])
        ax = self.plot.figure.add_axes([0, 0, 1, 1])
        self.plot.setMinimumHeight(50)
        self.plot.setMaximumHeight(50)
        self.plot_line, = self.plot.figure.gca().plot(np.arange(0, 2 ** self.bitDepth + 20, 20), np.arange(0, 2 ** self.bitDepth + 20, 20))
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.set_yticks([])
        ax.set_xticks([])
        ax.set_xlim(0, 2 ** mmc.config["BitDepth"] + 20)
        self.layout.addWidget(self.plot)

        self.label = QtWidgets.QLabel()
        self.layout.addWidget(self.label)

        self.parent.signal_new_image.connect(self.updateStatus)
        #self.updateStatus()

    def updateStatus(self):
        max = self.parent.im_max
        self.setTitle("Histogram %3.1f%% (%d)" % (100 * max / (2 ** self.bitDepth), max))
        self.plot_line.set_data(self.parent.im_bins[:-1], self.parent.im_hist)
        self.label.setText("Overexposed: %d%%" % int(self.parent.im_hist[-2]*1000))
        self.plot.figure.gca().set_ylim(0, self.parent.im_hist[:-2].max()*1.05)
        self.plot.draw()


class ModuleSnap(QtWidgets.QGroupBox):
    last_folder = ""

    def __init__(self, parent, layout):
        QtWidgets.QWidget.__init__(self)
        self.parent = parent
        layout.addWidget(self)
        self.setTitle("Record")
        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)
        self.setMinimumWidth(200)

        self.layout1 = QtWidgets.QHBoxLayout()
        self.layout.addLayout(self.layout1)

        self.layout2 = QtWidgets.QHBoxLayout()
        self.layout.addLayout(self.layout2)

        self.button_snap = QtWidgets.QPushButton("Snap Image")
        self.layout1.addWidget(self.button_snap)

        self.button_continuous = QtWidgets.QPushButton("Sequence")
        self.layout1.addWidget(self.button_continuous)

        self.button_save_image = QtWidgets.QPushButton("Save Image")
        self.layout2.addWidget(self.button_save_image)

        self.button_snap.clicked.connect(self.ButtonSnap)
        self.button_continuous.clicked.connect(self.ButtonContinuous)
        self.button_save_image.clicked.connect(self.ButtonSaveImage)

        self.updateButtonContinuosText()

        self.parent.signal_new_image.connect(self.updateStatus)

    def updateStatus(self):
        if mmc.isSequenceRunning():
            self.setTitle("Record %.2f fps" % mmc.memmap.fps)
        else:
            self.setTitle("Record %.2f fps" % 0.0)

    def ButtonSnap(self):
        self.parent.im = None
        shutter_opened = False
        if mic:
            print(mic.memmap.mode, mic.memmap.shutter)
            if (mic.memmap.mode == 10 or mic.memmap.mode > 100) and not mic.memmap.shutter:
                shutter_opened = True
                mic.setShutter(True)
                mic.waitTillEvent(shutter=True)
        mmc.snapImage()
        if shutter_opened:
            mic.setShutter(False)
        self.parent.im = mmc.getImage().copy()
        self.parent.showImage()
        self.updateButtonContinuosText()

    def updateButtonContinuosText(self):
        if mmc.isSequenceRunning():
            self.button_continuous.setText("Stop Sequence")
        else:
            self.button_continuous.setText("Start Sequence")

    def ButtonContinuous(self):
        if mmc.isSequenceRunning():
            mmc.stopSequenceAcquisition()
        else:
            mmc.startContinuousSequenceAcquisition(1)
        self.updateButtonContinuosText()

    def ButtonSaveImage(self):
        save_filename = r"{datetime}.tif".format(datetime=time.strftime("%Y%m%d-%H%M%S", time.localtime()))

        filename = os.path.join(self.last_folder, save_filename)
        filename = QtWidgets.QFileDialog.getSaveFileName(self, "Save Image", filename, "TIF images (*.tif)")
        if isinstance(filename, tuple):
            filename = str(filename[0])
        else:
            filename = str(filename)
        if filename:
            self.last_folder = os.path.dirname(filename)
            mmc.saveImage(filename, self.parent.im, microscope=mic)
            print(filename, "saved")


class ModuleProperties(QtWidgets.QGroupBox):
    last_folder = ""

    def __init__(self, parent, layout):
        QtWidgets.QWidget.__init__(self)
        #for prop in mmc.getPropertyList():
        #    print(prop.name, prop.value, prop.allowed_values, prop.min, prop.max)
        allowed_names = ["LIGHT MODE", "Sensor Cooler Fan"]
        self.properties = [p for p in mmc.getPropertyList() if p.name in allowed_names]
        if len(self.properties) == 0:
            return

        self.parent = parent
        layout.addWidget(self)
        self.setTitle("Properties")
        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)
        self.setMinimumWidth(200)

        self.buttons = []
        for index, prop in enumerate(self.properties):
            button = QtWidgets.QPushButton(prop.name+": "+prop.value)
            self.layout.addWidget(button)
            self.buttons.append(button)
            button.clicked.connect(lambda c, index=index: self.buttonClicked(index))

    def buttonClicked(self, index):
        prop = self.properties[index]
        allowed_values = deserialize(prop.allowed_values)
        current_index = allowed_values.index(prop.value)
        new_index = (current_index+1) % len(allowed_values)
        new_value = allowed_values[new_index]
        mmc.setProperty("Camera", self.properties[index].name, new_value, callback=lambda x: self.updateButtons())

    def updateButtons(self):
        for index, prop in enumerate(self.properties):
            self.buttons[index].setText(prop.name+": "+prop.value)


class ModuleScaleBar(QtWidgets.QGroupBox):

    def __init__(self, parent):
        QtWidgets.QWidget.__init__(self)
        self.parent = parent

        self.font = QtGui.QFont()
        self.font.setPointSize(16)

        self.pixtomu = 6.45
        self.magnification = 1
        self.coupler = mic.getCoupler()
        self.scale = 1

        self.scalebar = QtWidgets.QGraphicsRectItem(0, 0, 1, 1, self.parent.view.hud_lowerRight)
        self.scalebar.setBrush(QtGui.QBrush(QtGui.QColor("white")))
        self.scalebar.setPen(QtGui.QPen(QtGui.QColor("white")))
        self.scalebar.setPos(-20, -20)
        self.scalebar_text = QtWidgets.QGraphicsTextItem("", self.parent.view.hud_lowerRight)
        self.scalebar_text.setFont(self.font)
        self.scalebar_text.setDefaultTextColor(QtGui.QColor("white"))

        self.parent.signal_zoom.connect(self.zoomEvent)

        self.parent.signal_objective_changed.connect(self.updateStatus)
        self.parent.signal_coupler_changed.connect(self.updateCouplerStatus)
        self.parent.signal_init.connect(self.init)
        self.init()

    def init(self):
        # query current magnification
        mic.sendRequest(76, 33, parameter=["a", "1"], formats=[int, int, int], callback=self.updateStatus)

    def updateStatus(self, index, value, magnification):
        self.magnification = magnification
        self.updateBar()

    def updateCouplerStatus(self, coupler):
        self.coupler = coupler
        self.updateBar()

    def zoomEvent(self, scale, pos):
        if self.pixtomu:
            self.scale = scale
            self.updateBar()

    def updateBar(self):
        mu = 100*self.pixtomu/(self.magnification*self.coupler)/self.scale
        values = [1, 5, 10, 25, 50, 75, 100, 150, 200, 250, 500, 1000, 1500, 2000, 2500, 5000, 10000]
        old_v = mu
        for v in values:
            if mu < v:
                mu = old_v
                break
            old_v = v
        pixel = mu/(self.pixtomu/(self.magnification*self.coupler))*self.scale
        self.scalebar.setRect(0, 0, -pixel, 5)
        self.scalebar_text.setPos(-pixel-20-25, -20-30)
        self.scalebar_text.setTextWidth(pixel+50)
        self.scalebar_text.setHtml(u"<center>%d&thinsp;µm</center>" % mu)


class Window(QtWidgets.QWidget, Ui_Dialog):
    signal = QtCore.Signal()
    signal_init = QtCore.Signal()
    signal_new_image = QtCore.Signal()
    signal_objective_changed = QtCore.Signal(int, int, int)
    signal_mode_changed = QtCore.Signal(int)
    signal_aperture_changed = QtCore.Signal(int)
    signal_field_changed = QtCore.Signal(int)
    signal_lamp_changed = QtCore.Signal(int)
    signal_filter_changed = QtCore.Signal(int, str)
    signal_x_changed = QtCore.Signal(int)
    signal_y_changed = QtCore.Signal(int)
    signal_z_changed = QtCore.Signal(int)
    signal_zoom = QtCore.Signal(float, QtCore.QPointF)
    signal_coupler_changed = QtCore.Signal(float)
    signal_callback = QtCore.Signal(tuple)
    window_settings = None

    im = None
    im_max = None
    im_hist = None
    im_bins = None

    def callback(self, args):
        # execute the callback which has been wrapped in a signal to be thread save
        args[0](*args[1])

    def zoomEvent(self, scale, pos):
        self.signal_zoom.emit(scale, pos)

    def __init__(self, parent=None):
        global mmc, mic
        # initialize window
        QtWidgets.QWidget.__init__(self, parent)
        self.setWindowTitle('LiveViewerCool')
        self.setWindowIcon(QtGui.QIcon(QtGui.QIcon(os.path.join(icon_path, "LiveViewer.ico"))))
        self.setGeometry(100, 100, 1300, 800)

        # set main layout
        self.layout = QtWidgets.QHBoxLayout(self)

        # set tools layout left (microscope)
        self.tools_layout = QtWidgets.QVBoxLayout()
        self.layout.addLayout(self.tools_layout)

        # set live view layout
        self.view_layout = QtWidgets.QVBoxLayout()
        self.layout.addLayout(self.view_layout)

        # set tools layout right (camera)
        self.tools2_layout = QtWidgets.QVBoxLayout()
        self.layout.addLayout(self.tools2_layout)

        # initialize live view
        self.view = QExtendedGraphicsView()
        self.view.zoomEvent = self.zoomEvent
        self.local_scene = self.view.scene
        self.origin = self.view.origin
        self.view_layout.addWidget(self.view)

        self.pixmap = QtWidgets.QGraphicsPixmapItem(QtGui.QPixmap(1344,1024),self.origin)

        # connect to camera
        print("Conneting to camera server...")
        mmc = Camera()
        mmc.nowait = True
        mmc.no_exceptions = True
        mmc.startContinuousSequenceAcquisition(1)

        # connect to microscope
        mic = microscope()
        mic.callback_signal = self.signal_callback
        self.signal_callback.connect(self.callback)
        mic.connectEvent(self.Event)
        mmc.event_connect = self.Event
        self.Event(0, 0, "")
        print("... connected")

        # view update timer
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.updateview)
        self.timer.start(100)

        # initialize microscope modules
        self.mod_obj = ModuleObjective(self, self.tools_layout)
        self.mod_obj = ModuleMethods(self, self.tools_layout)
        self.mod_obj = ModuleIntensity(self, self.tools_layout)
        self.mod_obj = ModuleFilters(self, self.tools_layout)
        self.mod_obj = ModulePosition(self, self.tools_layout)
        self.tools_layout.addStretch()

        # initialize camera modules
        self.mod_obj = ModuleCoupler(self, self.tools2_layout)
        self.mod_obj = ModuleExposure(self, self.tools2_layout)
        self.mod_obj = ModuleROI(self, self.tools2_layout)
        self.mod_obj = ModuleHistogram(self, self.tools2_layout, mmc.config["BitDepth"])
        self.mod_obj = ModuleSnap(self, self.tools2_layout)
        self.mod_obj = ModuleProperties(self, self.tools2_layout)
        self.tools2_layout.addStretch()

        # module to create the scalebar
        self.mod_obj = ModuleScaleBar(self)

        # center window in desktop
        DRect = QtWidgets.QDesktopWidget().screenGeometry()
        WRect = self.geometry()
        self.move((DRect.width() - WRect.width()) / 2, (DRect.height() - WRect.height()) / 4)

    def Event(self, device, command, answer):
        """ automatically called by the microscope client when the microscope as sent an event """
        answer = answer.split()
        print(device, "-", command, "-", answer)
        # new magnification
        if device == 76 and command == 33 and int(answer[1]) == 1:
            self.signal_objective_changed.emit(*[int(i) for i in answer])
        # mode changed
        elif device == 70 and command == 28:
            self.signal_mode_changed.emit(int(answer[0]))
        # aperture changed
        elif device == 84 and command == 23:
            self.signal_aperture_changed.emit(int(answer[0]))
        # field diaphragm changed
        elif device == 94 and command == 23:
            self.signal_field_changed.emit(int(answer[0]))
        # lamp intensity changed
        elif device == 77 and command == 21:
            self.signal_lamp_changed.emit(int(answer[0]))
        # filter changed
        elif device == 78 and command == 23:
            self.signal_filter_changed.emit(int(answer[0]), answer[1])
        # z changed
        elif device == 71 and command == 23:
            self.signal_z_changed.emit(int(answer[0]))
        # x changed
        elif device == 72 and command == 23:
            self.signal_x_changed.emit(int(answer[0]))
        # y changed
        elif device == 73 and command == 23:
            self.signal_y_changed.emit(int(answer[0]))
        # reconnected to the microscope
        elif device == 1 and command == 0:
            print("init emit")
            self.signal_init.emit()
        # generic event
        else:
            self.signal.emit()

    def keyPressEvent(self, event):
        # @key ---- General ----
        #if event.key() == QtCore.Qt.Key_F1:
        #    # @key F1: toggle help window
        #    self.HelpText.ShowHelpText()
            
        if event.key() == QtCore.Qt.Key_F:
            # @key F: fit image to view
            self.view.fitInView()
        pass

    def showImage(self):
        # if we have a non zero image
        if self.im.shape[0] != 0:
            # notifiy modules
            self.signal_new_image.emit()

            # calculate stretching factor
            max_brightness = np.amax(self.im)
            # don't stretch too much to keep dark images dark
            max_value = (100*max_brightness/2**mmc.config["BitDepth"]-5.1)/(40-5.1)*255
            if max_value > 255:
                max_value = 255
            if max_value < 0:
                max_value = 0
            factor = max_value/max_brightness
            # draw image
            self.pixmap.setPixmap(QtGui.QPixmap(array2qimage(self.im*factor)))

    def updateview(self):
        # do we have a new image?
        if mmc.getRemainingImageCount():
            # copy the image
            self.im = mmc.getLastImage().copy()
            # calculate maximum and histogram
            self.im_max = np.amax(self.im)
            self.im_hist, self.im_bins = np.histogram(self.im, bins=np.arange(0, 2 ** mmc.config["BitDepth"] + 20, 10), normed=True)
            # display the iamge
            self.showImage()
            self.view.setExtend(self.im.shape[1], self.im.shape[0])


if __name__ == '__main__':
    if sys.platform[:3] == 'win':
        myappid = 'fabrybiophysics.clickpoints'  # arbitrary string
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    window = Window()
    window.show()
    splash.finish(window)
    sys.exit(app.exec_())
