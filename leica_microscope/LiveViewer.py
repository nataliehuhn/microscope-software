from __future__ import division, print_function
import qtawesome as qta
import sys

""" some magic to prevent PyQt5 from swallowing exceptions """
# Back up the reference to the exceptionhook
sys._excepthook = sys.excepthook
# Set the exception hook to our wrapping function
sys.excepthook = lambda *args: sys._excepthook(*args)

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

from qimage2ndarray import array2qimage

import time
import numpy as np
from leica_microscope.includes.matplotlibwidget import MatplotlibWidget
from leica_microscope.microscope import NoMicroscopeFound
import matplotlib.pyplot as plt


output_path = os.path.join(os.getenv('APPDATA'), "Microscope")
if not os.path.exists(output_path):
    os.mkdir(output_path)
positions_file = os.path.join(output_path, "Positions_tmp.txt")


#sys.path.insert(0, os.path.dirname(__file__))
#from HelperFunctions import format_partial

#sys.path.append(os.path.join(os.path.dirname(__file__), "..", "qextendedgraphicsview"))
#from QExtendedGraphicsView import QExtendedGraphicsView
#from Tools import HelpText, GraphicsItemEventFilter

#global mmc, mic, exposure_time, gain_values
#from microscopehandler.CameraClient import Camera
#from microscopehandler.MicroscopeClient import microscope

#from ui_dialog import Ui_Dialog

#icon_path = os.path.join(os.path.dirname(__file__), ".", "icons")

#sensor_size = 6.45

#output_path = os.path.join(os.getenv('APPDATA'), "Microscope")
#if not os.path.exists(output_path):
#    os.mkdir(output_path)
#exposure_times_file = os.path.join(output_path, "LiveViewer_ExposureTimes.txt")
#gain_values_file = os.path.join(output_path, "LiveViewer_GainValues.txt")
#positions_file = os.path.join(output_path, "Positions_tmp.txt")
from leica_microscope import Microscope
from leica_microscope import MemmapReader
from leica_microscope.includes.QExtendedGraphicsView import QExtendedGraphicsView


class QInput(QtWidgets.QWidget):
    """
    A base class for input widgets with a text label and a unified API.
    - The valueChanged signal is emitted when the user has changed the input.
    - The value of the input element get be set with setValue(value) and queried by value()
    """
    # the signal when the user has changed the value
    valueChanged = QtCore.Signal('PyQt_PyObject')

    no_signal = False

    last_emited_value = None

    def __init__(self, layout=None, name=None, tooltip=None, stretch=False):
        # initialize the super widget
        super(QInput, self).__init__()

        # initialize the layout of this widget
        QtWidgets.QHBoxLayout(self)
        self.layout().setContentsMargins(0, 0, 0, 0)

        # add me to a parent layout
        if layout is not None:
            if stretch is True:
                self.wrapper_layout = QtWidgets.QHBoxLayout()
                self.wrapper_layout.setContentsMargins(0, 0, 0, 0)
                self.wrapper_layout.addWidget(self)
                self.wrapper_layout.addStretch()
                layout.addLayout(self.wrapper_layout)
            else:
                layout.addWidget(self)

        # add a label to this layout
        self.label = QtWidgets.QLabel(name)
        self.layout().addWidget(self.label)

        if tooltip is not None:
            self.setToolTip(tooltip)

    def setLabel(self, text):
        # update the label
        self.label.setText(text)

    def _emitSignal(self):
        if self.value() != self.last_emited_value:
            self.valueChanged.emit(self.value())
            self.last_emited_value = self.value()

    def _valueChangedEvent(self, value):
        if self.no_signal:
            return
        self.setValue(value)
        self._emitSignal()

    def setValue(self, value):
        self.no_signal = True
        try:
            self._doSetValue(value)
        finally:
            self.no_signal = False

    def _doSetValue(self, value):
        # dummy method to be overloaded by child classes
        pass

    def value(self):
        # dummy method to be overloaded by child classes
        pass


class QInputNumber(QInput):
    slider_dragged = False

    def __init__(self, layout=None, name=None, value=0, min=None, max=None, use_slider=False, float=True, decimals=2,
                 unit=None, **kwargs):
        # initialize the super widget
        QInput.__init__(self, layout, name, **kwargs)

        if float is False:
            self.decimals = 0
        else:
            if decimals is None:
                decimals = 2
            self.decimals = decimals
        self.decimal_factor = 10**self.decimals

        if use_slider and min is not None and max is not None:
            # slider
            self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            self.layout().addWidget(self.slider)
            self.slider.setRange(min * self.decimal_factor, max * self.decimal_factor)
            self.slider.valueChanged.connect(lambda x: self._valueChangedEvent(x / self.decimal_factor))
            self.slider.sliderPressed.connect(lambda: self._setSliderDragged(True))
            self.slider.sliderReleased.connect(lambda: self._setSliderDragged(False))
        else:
            self.slider = None

        # add spin box
        if float:
            self.spin_box = QtWidgets.QDoubleSpinBox()
            self.spin_box.setDecimals(decimals)
        else:
            self.spin_box = QtWidgets.QSpinBox()
        if unit is not None:
            self.spin_box.setSuffix(" " + unit)

        if self.slider is not None:
            self.spin_box.setMaximumWidth(100)

        self.layout().addWidget(self.spin_box)
        self.spin_box.valueChanged.connect(self._valueChangedEvent)

        if min is not None:
            self.spin_box.setMinimum(min)
        else:
            self.spin_box.setMinimum(-99999)
        if max is not None:
            self.spin_box.setMaximum(max)
        else:
            self.spin_box.setMaximum(+99999)

        if value is not None:
            self.setValue(value)

    def _setSliderDragged(self, value):
        self.slider_dragged = value
        if value is False:
            self._emitSignal()

    def _valueChangedEvent(self, value):
        if self.no_signal:
            return
        self.setValue(value)
        if not self.slider_dragged:
            self._emitSignal()

    def _doSetValue(self, value):
        self.spin_box.setValue(value)
        if self.slider is not None:
            self.slider.setValue(value * self.decimal_factor)

    def value(self):
        return self.spin_box.value()


class ModuleObjective(QtWidgets.QGroupBox):

    def __init__(self, parent, layout):
        QtWidgets.QWidget.__init__(self)
        self.parent = parent
        self.mic = parent.mic
        layout.addWidget(self)
        self.setTitle("Objectives")

        self.layout = QtWidgets.QGridLayout()
        self.setLayout(self.layout)
        self.magnifications = self.mic.properties["objectives"]
        self.buttons = []

        self.index = self.mic.properties["current_objective"]

        for i in range(6):
            button = QtWidgets.QPushButton("")
            button.setCheckable(True)
            if self.magnifications[i] == "-":
                button.setDisabled(True)
            else:
                self.magnifications[i] = int(self.magnifications[i])
                button.setText(f"{self.magnifications[i]} x")
            button.clicked.connect(lambda x, i=i: self.buttonClicked(i))
            self.layout.addWidget(button, i // 3, i % 3)
            self.buttons.append(button)

        self.parent.signal_properties_changed.connect(self.updateStatus)
        self.updateStatus()

    def buttonClicked(self, i):
        print("Setting objective to %d (%d x)" % (i + 1, self.magnifications[i]))
        self.setTitle(f"Objectives {self.magnifications[self.index-1]} x -> {self.magnifications[i]} x")
        self.index = None
        app.processEvents()
        self.updateButtons()
        self.mic.setObjective(i + 1)
        self.parent.update()

    def updateStatus(self):
        self.index = self.mic.properties["current_objective"]
        self.setTitle(f"Objectives {self.magnifications[self.index-1]} x")
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
        self.mic = parent.mic
        layout.addWidget(self)
        self.setTitle("Methods")

        self.layout = QtWidgets.QGridLayout()
        self.setLayout(self.layout)
        self.buttons = []
        self.buttons_by_mode = {}
        self.index = self.mic.properties["current_mode"]
        self.methods_names = ["TL BF", "TL PH", "TL DF", "TL DIC", "TL POL", "IL BF", "IL OBL", "IL DF", "IL DIC",
                              "IL POL", "FLUO", "FLUO/PH", "FLUO/DIC", "BF/BF"]#, "nn", "nn"]

        #self.parent.signal_mode_changed.connect(self.updateStatus)
        #self.parent.signal_init.connect(self.init)

        for index, method in enumerate(self.mic.properties["modes"]):
            button = QtWidgets.QPushButton(method)
            button.setCheckable(True)
            button.clicked.connect(lambda x, i=method: self.buttonClicked(i))
            self.layout.addWidget(button, len(self.buttons) // 3, len(self.buttons) % 3)
            self.buttons.append(button)
            self.buttons_by_mode[method] = button

        self.updateStatus()
        self.parent.signal_properties_changed.connect(self.updateStatus)

    def buttonClicked(self, method):
        print("Setting methods to %s" % method)
        self.setTitle(f"Methods {self.mic.mode_id_to_name(self.index)} -> {method}")
        app.processEvents()
        self.updateButtons()
        self.mic.setMode(method)
        self.parent.update()

    def updateStatus(self):
        self.index = self.mic.properties["current_mode"]
        print("self.index", self.index, self.mic.mode_id_to_name(self.index))
        self.setTitle("Methods %s" % self.mic.mode_id_to_name(self.index))
        self.updateButtons()

    def updateButtons(self):
        for button in self.buttons:
            button.setChecked(False)
        if self.mic.mode_id_to_name(self.index):
            self.buttons_by_mode[self.mic.mode_id_to_name(self.index)].setChecked(True)



class ModuleIntensity(QtWidgets.QGroupBox):

    def __init__(self, parent, layout):
        QtWidgets.QWidget.__init__(self)
        self.parent = parent
        self.mic = parent.mic
        layout.addWidget(self)
        self.setTitle("Intensity")

        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)
        self.input_aperture = QInputNumber(self.layout, "Aperture", self.mic.properties["aperture"], 1, 24, float=False, use_slider=True)
        self.input_field = QInputNumber(self.layout, "Field", self.mic.properties["field"], 1, 12, float=False, use_slider=True)
        self.input_intensity = QInputNumber(self.layout, "Intensity", self.mic.properties["intensity"], 0, 255, float=False, use_slider=True)

        self.input_aperture.valueChanged.connect(lambda v, i=0: self.valueChanged(v, i))
        self.input_field.valueChanged.connect(lambda v, i=1: self.valueChanged(v, i))
        self.input_intensity.valueChanged.connect(lambda v, i=2: self.valueChanged(v, i))

        self.parent.signal_properties_changed.connect(self.update)

    def valueChanged(self, value, i):
        if i == 0:
            print("Set Aperture to", value)
            self.mic.setApertureTL(value)
        if i == 1:
            print("Set Field to", value)
            self.mic.setFieldTL(value)
        if i == 2:
            print("Set Lamp to", value)
            self.mic.setLampIntensity(value)
        self.parent.update()

    def update(self):
        self.input_aperture.setValue(self.mic.properties["aperture"])
        self.input_field.setValue(self.mic.properties["field"])
        self.input_intensity.setValue(self.mic.properties["intensity"])

class ModuleFilters(QtWidgets.QGroupBox):

    def __init__(self, parent, layout):
        QtWidgets.QWidget.__init__(self)
        self.parent = parent
        self.mic = parent.mic
        layout.addWidget(self)

        self.layout = QtWidgets.QGridLayout()
        self.setLayout(self.layout)
        self.filters = self.mic.properties["filters"]
        self.buttons = []

        for i in range(6):
            button = QtWidgets.QPushButton()
            if self.filters[i] == "-0" or self.filters[i] == "-1" or self.filters[i] == "EMP1":
                button.setDisabled(True)
                button.setText("-")
            else:
                button.setText(self.filters[i])
            button.setCheckable(True)
            button.clicked.connect(lambda x, i=i: self.buttonClicked(i))
            self.layout.addWidget(button, i // 3, i % 3)
            self.buttons.append(button)

        self.parent.signal_properties_changed.connect(self.updateStatus)
        self.updateStatus()

    def initButtons(self, index, filter):
        if filter == "-0" or filter == "-1" or filter == "EMP1":
            return
        self.filters[index-1] = filter
        self.buttons[index-1].setText(filter)
        self.buttons[index-1].setDisabled(False)

    def buttonClicked(self, i):
        print("Setting filter to %d (%s)" % (i + 1, self.filters[i]))
        self.setTitle(f'Filters {self.mic.properties["filters"][self.mic.properties["current_filter"]-1]} -> {self.mic.properties["filters"][i]}')
        app.processEvents()
        self.updateButtons()
        self.mic.setMode(self.mic.properties["current_mode"], i + 1)
        self.parent.update()

    def updateStatus(self):
        self.setTitle("Filters %s" % self.mic.properties["filters"][self.mic.properties["current_filter"]-1])
        self.updateButtons()

    def updateButtons(self):
        for button in self.buttons:
            button.setChecked(False)
        if self.mic.properties["current_filter"]:
            self.buttons[self.mic.properties["current_filter"]-1].setChecked(True)

class ModulePosition(QtWidgets.QGroupBox):
    z_conversion = 0.003800
    x_conversion = 0.13818360
    y_conversion = 0.13818360

    def __init__(self, parent, layout):
        QtWidgets.QWidget.__init__(self)
        self.setMaximumWidth(300)
        self.parent = parent
        self.mic = parent.mic
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
        self.conversion = self.mic.properties["resolution"]

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

        #self.parent.signal_x_changed.connect(lambda value: self.initSlider(value, 0))
        #self.parent.signal_y_changed.connect(lambda value: self.initSlider(value, 1))
        #self.parent.signal_z_changed.connect(lambda value: self.initSlider(value, 2))

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

        #self.parent.signal_init.connect(self.init)
        #self.init()

        #mic.getMaxX(callback=lambda value: self.setMax(value, 0))
        #mic.getMaxY(callback=lambda value: self.setMax(value, 1))
        #mic.getMaxZ(callback=lambda value: self.setMax(value, 2))

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

    def addPosition(self):
        position = self.mic.getPos()
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
            with self.mic.nowait:
                self.mic.setPos(self.positions[index])

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
            self.positions = []
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
        #if i == 2:
        #    SetValueNoSignal(self.sliders[0], value * self.conversion[i])
        #SetValueNoSignal(self.spinBoxes[i], int(value * self.conversion[i]))
        if i == 2:
            self.sliders[0].setDisabled(False)
        self.spinBoxes[i].setDisabled(False)

    def valueChanged(self, value, i):
        if not self.spinBoxes[i].isEnabled():
            return
        #SetValueNoSignal(self.spinBoxes[i], value)
        if i == 0:
            print("Set X to", value)
            self.mic.setX(int(value / self.conversion[i]))
        if i == 1:
            print("Set Y to", value)
            self.mic.setY(int(value / self.conversion[i]))
        if i == 2:
            print("Set Z to", value, int(value/self.conversion[i]))
            self.mic.setZ(int(value/self.conversion[i]))
            #SetValueNoSignal(self.sliders[0], value)

    def updateStatus(self):
        self.setTitle("Position")


class CameraSettings(QtWidgets.QWidget):
    def __init__(self):
        QtWidgets.QWidget.__init__(self)

        # widget layout and elements
        self.setWindowTitle("Camera Settings")
        layout_vert = QtWidgets.QVBoxLayout(self)

        layout_hor = QtWidgets.QHBoxLayout()
        layout_vert.addLayout(layout_hor)

        layout_hor.addWidget(QtWidgets.QLabel("ROI"))
        self.spinbox_roi = QtWidgets.QSpinBox()
        self.spinbox_roi.setRange(8, 1024)
        self.spinbox_roi.setValue(mmc.memmap.roi[3])
        self.spinbox_roi.valueChanged.connect(self.changeROI)
        layout_hor.addWidget(self.spinbox_roi)
        #self.spinbox_roi.setValue()
        self.button_reset_roi = QtWidgets.QPushButton("Reset")
        self.button_reset_roi.clicked.connect(lambda x: self.spinbox_roi.setValue(1024))
        layout_hor.addWidget(self.button_reset_roi)

    def changeROI(self):
        crop = 1024-self.spinbox_roi.value()
        mmc.setROI(0, crop/2, 1344, 1024-crop)


class ModuleCoupler(QtWidgets.QGroupBox):

    def __init__(self, parent, layout):
        QtWidgets.QWidget.__init__(self)
        self.parent = parent
        self.mic = parent.mic
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

        self.button_055 = QtWidgets.QPushButton("0.55")
        self.button_055.setCheckable(True)
        self.layout1.addWidget(self.button_055)

        self.button_10 = QtWidgets.QPushButton("1.0")
        self.button_10.setCheckable(True)
        self.layout1.addWidget(self.button_10)

        self.button_05.clicked.connect(lambda x: self.setCoupler(0.5))
        self.button_055.clicked.connect(lambda x: self.setCoupler(0.55))
        self.button_10.clicked.connect(lambda x: self.setCoupler(1.0))

        self.updateStatus()

    def setCoupler(self, value):
        if self.mic != None:
            self.mic.setCoupler(value)
        self.updateStatus()
        self.parent.signal_coupler_changed.emit(value)

    def updateStatus(self):
        if self.mic != None:
            self.setTitle("Coupler: %.2f" % self.mic.getCoupler())
            if self.mic.getCoupler() == 0.5:
                self.button_05.setChecked(True)
                self.button_055.setChecked(False)
                self.button_10.setChecked(False)
            elif self.mic.getCoupler() == 0.55:
                self.button_05.setChecked(False)
                self.button_055.setChecked(True)
                self.button_10.setChecked(False)
            else:
                self.button_05.setChecked(False)
                self.button_055.setChecked(False)
                self.button_10.setChecked(True)


class ModuleExposure(QtWidgets.QGroupBox):
    nochange = False

    def __init__(self, parent, layout):
        QtWidgets.QWidget.__init__(self)
        self.parent = parent
        self.mic = parent.mic
        self.cam = parent.cam
        layout.addWidget(self)
        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)
        min_exp, max_exp = self.cam.get_exposure_range()
        self.input_exposure = QInputNumber(self.layout, "Exposure", self.cam.exposure(), min_exp, max_exp, use_slider=True)
        min_gain, max_gain = self.cam.get_gain_range()
        self.input_gain = QInputNumber(self.layout, "Gain", self.cam.gain(), min_gain, max_gain, use_slider=True)

        self.input_exposure.valueChanged.connect(lambda v: self.valueChanged(v, 0))
        self.input_gain.valueChanged.connect(lambda v: self.valueChanged(v, 1))

        self.parent.signal.connect(self.updateStatus)
        self.updateStatus()

    def valueChanged(self, value, i):
        if i == 0:
            print("Set Exposure to", value)
            self.cam.setExposure(value)
        if i == 1:
            print("Set Gain to", value)
            self.cam.setGain(value)
        self.updateStatus()

    def updateStatus(self):
        self.setTitle("Exposure")


class ModuleROI(QtWidgets.QGroupBox):
    nochange = False
    last_binning = 1

    def __init__(self, parent, layout):
        QtWidgets.QWidget.__init__(self)
        self.parent = parent
        self.cam = parent.cam
        layout.addWidget(self)
        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)

        self.input_crop = QInputNumber(self.layout, "ROI Height", self.cam.getHeight(), 8, 2192, use_slider=True, float=False)
        self.input_binning = QInputNumber(self.layout, "Binning", self.cam.gain(), 1, 8, use_slider=True, float=False)

        self.input_crop.valueChanged.connect(lambda v: self.valueChanged(v, 0))
        self.input_binning.valueChanged.connect(lambda v: self.valueChanged(v, 1))

        self.parent.signal.connect(self.updateStatus)
        self.updateStatus()

    def valueChanged(self, value, i):
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
            self.input_binning.setValue(value)
            self.cam.setBinning(value)
            self.last_binning = value
        print("Set ROI height to", value)
        crop = 2192 - value
        crop = crop - crop % (8*self.cam.binning())
        self.input_crop.setValue(2192 - crop)
        self.cam.setROI(0, crop // 2, 2752, 2192 - crop)
        self.updateStatus()

    def updateStatus(self):
        self.setTitle("ROI")


class ModuleHistogram(QtWidgets.QGroupBox):

    def __init__(self, parent, layout, max_value):
        QtWidgets.QWidget.__init__(self)
        self.parent = parent
        layout.addWidget(self)
        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)
        self.setMaximumHeight(100)

        self.max_value = max_value

        self.plot = MatplotlibWidget()
        self.plot.figure.patch.set_facecolor([0, 1, 0, 0])
        ax = self.plot.figure.add_axes([0, 0, 1, 1])
        self.plot.setMinimumHeight(50)
        self.plot.setMaximumHeight(50)
        self.plot_line, = self.plot.figure.gca().plot(np.arange(0, max_value + 20, 20), np.arange(0, max_value + 20, 20))
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.set_yticks([])
        ax.set_xticks([])
        ax.set_xlim(0, max_value + 20)
        self.layout.addWidget(self.plot)

        self.label = QtWidgets.QLabel()
        self.layout.addWidget(self.label)

        self.parent.signal_new_image.connect(self.updateStatus)

    def updateStatus(self):
        max = self.parent.im_max
        self.setTitle(f"Histogram {100 * max / self.max_value:3.1f}% ({max})")
        self.plot_line.set_data(self.parent.im_bins[:-1], self.parent.im_hist)
        self.label.setText(f"Overexposed: {int(self.parent.im_hist[-2]*1000)}%")
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


class Window(QtWidgets.QWidget):
    signal = QtCore.Signal()
    window_settings = None
    im = None

    signal_properties_changed = QtCore.Signal()

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

    def update(self):
        self.mic.getAllProperties()
        self.signal_properties_changed.emit()

    def sceneEventFilter(self, event):
        if event.type() == QtCore.QEvent.GraphicsSceneMousePress and event.button() == QtCore.Qt.LeftButton:
            self.pan = True
            pos = event.pos()  # self.view.mapFromView(event.pos())
            self.last_x = pos.x()
            self.last_y = pos.y()
            return True
        if event.type() == QtCore.QEvent.GraphicsSceneMouseMove:
            if self.pan:
                pos = event.pos()  # self.view.mapFromView(event.pos())
                print(pos.x(), pos.y())
                dx = (self.last_x - pos.x())
                dy = (self.last_y - pos.y())
                # print(dx,-dy)
                self.pan_offsetX += dx
                self.pan_offsetY -= dy
                # self.view.translateBy((dx, -dy))
                self.view.origin.mapFromScene(event.pos())  # without the view shakes for strange reasons
                self.last_x = pos.x()
                self.last_y = pos.y()
                return True
        if event.type() == QtCore.QEvent.GraphicsSceneMouseRelease and event.button() == QtCore.Qt.LeftButton:
            self.pan = False
            return True
        return False
   
    def __init__(self, parent=None):
        super().__init__(parent)

        print("Conneting to microscope...")
        try:
            self.mic = Microscope(no_camera=True)
        except NoMicroscopeFound as err:
            print("leica_microscope.microscope.NoMicroscopeFound:", err, file=sys.stderr)
            self.mic = None

        self.cam = MemmapReader()
        print("... connected")

        self.setWindowTitle('LiveViewer')
        self.setWindowIcon(QtGui.QIcon(os.path.join(os.path.dirname(__file__), "icons", "LiveViewer.ico")))
        main_layout = QtWidgets.QHBoxLayout(self)
        left_layout = QtWidgets.QVBoxLayout()
        main_layout.addLayout(left_layout)
        center_layout = QtWidgets.QVBoxLayout()
        main_layout.addLayout(center_layout)
        right_layout = QtWidgets.QVBoxLayout()
        main_layout.addLayout(right_layout)

        self.last_folder = ""

        self.view = QExtendedGraphicsView()
        self.local_scene = self.view.scene
        self.origin = self.view.origin
        center_layout.addWidget(self.view)

        if self.mic != None:
            ModuleObjective(self, left_layout)
            ModuleMethods(self, left_layout)
            ModuleIntensity(self, left_layout)
            ModuleFilters(self, left_layout)
            ModulePosition(self, left_layout)
        left_layout.addStretch()

        ModuleCoupler(self, right_layout)
        ModuleExposure(self, right_layout)
        ModuleROI(self, right_layout)
        ModuleHistogram(self, right_layout, self.cam.getMaxValue())
        #ModuleSnap(self, right_layout)
        #ModuleProperties(self, right_layout)
        right_layout.addStretch()

        self.pixmap = QtWidgets.QGraphicsPixmapItem(QtGui.QPixmap(1344,1024),self.origin)

        if 0:
            self.button_save.clicked.connect(self.ButtonSave)
            self.button_load.clicked.connect(self.ButtonLoad)
            self.button_addPos.clicked.connect(lambda: self.save_position(-1))
            self.button_delPos.clicked.connect(lambda: self.del_position(self.current_position))
            self.button_changePos.clicked.connect(lambda: self.save_position(self.current_position))
            self.button_leftPos.clicked.connect(lambda: self.UpdateLabel(1, -1))
            self.button_rightPos.clicked.connect(lambda: self.UpdateLabel(1, +1))

            self.button_snap.clicked.connect(self.ButtonSnap)
            self.button_continuous.clicked.connect(self.ButtonContinuous)
            self.button_save_image.clicked.connect(self.ButtonSaveImage)
            self.button_save_grid.clicked.connect(self.ButtonGrid)
            self.button_save_stack.clicked.connect(self.ButtonStack)
            self.button_save_video.clicked.connect(self.ButtonVideo)
            self.button_save_stop.clicked.connect(self.ButtonStop)

            self.spinBox_exposureTime.valueChanged.connect(self.ValueChanged)
            self.spinBox_gain.valueChanged.connect(self.ValueChanged2)
            self.button_camera_options.clicked.connect(self.OpenCameraMenu)

            self.positions = []
            self.current_position = -1
            self.Label_Path.setText("No Positions")

            self.pan = False
            self.pan_offsetX = 0
            self.pan_offsetY = 0
            #self.event_filter = GraphicsItemEventFilter(self.origin, self)
            #self.pixmap.installSceneEventFilter(self.event_filter)

            self.blocked = False

            #self.HelpText = HelpText(self.view.hud, __file__)

            #self.help_text = QtWidgets.QGraphicsSimpleTextItem(self.view.hud)
            #self.help_text.setFont(QtGui.QFont("", 11))
            #self.help_text.setPos(0, 10)
            #self.help_text.setBrush(QtGui.QBrush(QtGui.QColor(255, 255, 255)))

            if 0:#os.path.exists(exposure_times_file):
                exposure_time = np.loadtxt(exposure_times_file)
            else:
                exposure_time = [5]*180

            if 0:#os.path.exists(gain_values_file):
                gain_values = np.loadtxt(gain_values_file)
            else:
                gain_values = [0]*180

            #self.spinBox_exposureTime.setValue(mmc.memmap.exposure)
            #self.spinBox_gain.setValue(mmc.memmap.gain)

            #self.ConnectToCamera()

            #self.UpdateExposureTime()

        if 1:
            #self.cam.fast_recording.__enter__()
            self.timer = QtCore.QTimer(self)
            self.timer.timeout.connect(self.updateview)
            self.timer.start(100)
        
        #self.last_mode = self.GetMode()
        #mic.connectEvent(self.Event)
        #mmc.event_connect = self.Event
        #self.signal.connect(self.MicroscopeUpdate)
        #self.Event(0, 0, "")

    def OpenCameraMenu(self):
        if self.window_settings is None:
            self.window_settings = CameraSettings()
        else:
            self.window_settings.close()
        self.window_settings.show()

    def keyPressEvent(self, event):
        # @key ---- General ----
        if event.key() == QtCore.Qt.Key_F1:
            # @key F1: toggle help window
            self.HelpText.ShowHelpText()
            
        if event.key() == QtCore.Qt.Key_F:
            # @key F: fit image to view
            self.view.fitInView()

        if event.key() == QtCore.Qt.Key_F11:
            # @key F11: save current image (filedialog)
            self.ButtonSaveImage()
            
        # @key ---- Point List ----
        if event.key() == QtCore.Qt.Key_S:
            # @key S: save current mic position to list
            print("Save")
            self.save_position(-1)
        if event.key() == QtCore.Qt.Key_C:
            # @key C: overwrite position to list with current mic position
            print("Change")
            if self.current_position < len(self.positions):
                self.save_position(self.current_position)
        if event.key() == QtCore.Qt.Key_Left and not self.blocked:
            # @key Left: next point in list
            print("Left")
            self.UpdateLabel(1, -1)
        if event.key() == QtCore.Qt.Key_Right and not self.blocked:
            # @key Right: previous point in list
            print("Right")
            self.UpdateLabel(1, +1)
        if event.key() == QtCore.Qt.Key_E:
            # @key E: delete current point from list
            self.del_position(self.current_position)
            
        # @key ---- Microscope ----
        """
        if not self.blocked:
            if event.key() == QtCore.Qt.Key_0:
                # @key 0: change to brightfield
                mic.setBFMode()
                self.UpdateExposureTime()
            if event.key() == QtCore.Qt.Key_9:
                # @key 9: change to phase contrast
                mic.setPHMode()
                self.UpdateExposureTime()
            if event.key() == QtCore.Qt.Key_8:
                # @key 8: change to DIC
                mic.setMode(3)
                mic.sendCommand(82, 22, 2, wait=1)  # set the condenser disc to 2 "K10"
                mic.sendCommand(85, 24, 1, wait=1)  # set the DIC turret to the next position
                print("DIC turret in position ", mic.sendRequest(85, 23))
                self.UpdateExposureTime()
            if event.key() == QtCore.Qt.Key_Q:
                mic.setMode(101)
            if event.key() == QtCore.Qt.Key_W:
                mic.setMode(102)
            if QtCore.Qt.Key_1 <= event.key() <= QtCore.Qt.Key_6:
                # @key 1-6: change to Fluorescence channel
                mic.setFluoMode()
                mic.setFluoChannel(event.key()-QtCore.Qt.Key_0)
                self.UpdateExposureTime()
            if event.key() == 223:
                # @key ss: change to phase contrast
                mic.setShutter(not mic.memmap.shutter)
        """


    def showImage(self):
        if self.im.shape[0] != 0:
            # show the histogram
            #hist, bins = np.histogram(self.im, bins=np.arange(0, 2 ** mmc.config["BitDepth"] + 20, 10), normed=True)
            #self.plot_line.set_data(bins[:-1], hist)
            #self.plot.figure.gca().set_ylim(0, hist.max()*1.05)
            #self.plot.draw()

            max_brightness = np.amax(self.im)

            max_value = (100*max_brightness/self.cam.getMaxValue()-5.1)/(40-5.1)*255
            if max_value > 255:
                max_value = 255
            if max_value < 0:
                max_value = 0
            factor = max_value/max_brightness
            self.pixmap.setPixmap(QtGui.QPixmap(array2qimage(self.im*factor)))

            #self.label_mode.setText("%.2f fps Illumination: %3.1f%% (%d, %dms, %d)" % (mmc.memmap.fps, 100*np.amax(self.im)/(2**mmc.config["BitDepth"]), np.amax(self.im), mmc.memmap.exposure, mmc.memmap.gain))

    def updateview(self):

        if 1:
            #if mmc.getRemainingImageCount():

            im = self.cam.getImage()

            if im is None:
                return
            self.im = im# >> 2

            # calculate maximum and histogram

            self.im_max = np.amax(self.im)
            #print("range", np.amin(self.im), np.amax(self.im))
            self.im_hist, self.im_bins = np.histogram(self.im[::4, ::4], bins=np.arange(0, self.cam.getMaxValue() + 20, 10),
                                                  density=True)
            # display the iamge


            self.showImage()
            self.view.setExtend(self.im.shape[1], self.im.shape[0])



            self.signal_new_image.emit()
            #self.CheckBlocked()
        return
        if self.pan_offsetX or self.pan_offsetY:
            PixToMu = sensor_size/mic.getEffectiveMagnification()
            StepToMu = mic.getResolutionX()
            PixToStep = PixToMu/StepToMu
            print(self.pan_offsetX*PixToStep, self.pan_offsetY*PixToStep)
            mic.setXOffset(self.pan_offsetX*PixToStep)
            mic.setYOffset(self.pan_offsetY*PixToStep)
            self.pan_offsetX = 0
            self.pan_offsetY = 0
        
    def closeEvent(self, event):
        self.cam.stop()
        if self.window_settings is not None:
            self.window_settings.close()
        exit

class Timeit:
    def __init__(self, name):
        self.name = name

    def __enter__(self):
        self.time = time.time()

    def __exit__(self, exc_type, exc_val, exc_tb):
        print("TIMEIT", self.name, time.time()-self.time)

if __name__ == '__main__':
    if sys.platform[:3] == 'win':
        myappid = 'fabrybiophysics.clickpoints' # arbitrary string
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    window = Window()
    window.show()
    splash.finish(window)
    sys.exit(app.exec_())
