from __future__ import division, print_function
import qtawesome as qta
import sys
from pathlib import Path
import json

# Direct launches must use this checkout, even if another copy is installed.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
            self.slider.setRange(int(min * self.decimal_factor), int(max * self.decimal_factor))
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
        if self.decimals == 0:
            self.spin_box.setValue(int(value))
        else:
            self.spin_box.setValue(value)
        if self.slider is not None:
            self.slider.setValue(int(value * self.decimal_factor))

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
        self.parent.signal_objective_changed.emit()

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
        self.parent.setMode(method)

    def updateStatus(self):
        self.index = self.mic.properties["current_mode"]
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
        self.parent.setMode(self.mic.properties["current_mode"], i + 1)

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
        self.cam = parent.cam
        layout.addWidget(self)
        self.setTitle("Position")

        self.layout_main = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout_main)

        self.combo_box = QtWidgets.QComboBox()
        self.layout_main.addWidget(self.combo_box)

        self.layout_add_pos = QtWidgets.QHBoxLayout()
        self.layout_main.addLayout(self.layout_add_pos)

        self.button_addmore = QtWidgets.QPushButton("add well positions")
        self.button_addmore.clicked.connect(self.addMorePositions)
        self.layout_add_pos.addWidget(self.button_addmore)

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
                slider.setMaximum(int(self.max_values[i]*self.z_conversion))
            spinBox.setMaximum(int(self.max_values[i]*self.z_conversion))

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

        def onclick(event):
            self.mic.setXYPos(int(event.xdata), int(event.ydata))

        cid = self.plot.figure.canvas.mpl_connect('button_press_event', onclick)
        self.ax = ax

        self.positions = []
        self.position_names = []
        self.list = QtWidgets.QListWidget()

        self.plate_data = None
        self.list_plate_data = []
        for file in Path(__file__).parent.glob("plate_data*.json"):
            with file.open("r") as fp:
                plate_data = json.load(fp)
            self.list_plate_data.append(plate_data)
            self.combo_box.addItem(plate_data["name"])

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

        self.list.keyPressEvent_old = self.list.keyPressEvent
        self.list.keyPressEvent = self.listKeyPress
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

        self.button_clearall = QtWidgets.QPushButton("clear all")
        self.button_clearall.clicked.connect(self.deleteAllPosition)
        button_layout.addWidget(self.button_clearall)

        button_layout = QtWidgets.QHBoxLayout()
        self.layout_main.addLayout(button_layout)
        self.button_save = QtWidgets.QPushButton("Save Pos File")
        self.button_save.clicked.connect(self.ButtonSave)
        button_layout.addWidget(self.button_save)
        self.button_load = QtWidgets.QPushButton("Load Pos File")
        self.button_load.clicked.connect(self.ButtonLoad)
        button_layout.addWidget(self.button_load)

        self.loadFile(positions_file)
        self.combo_box.currentIndexChanged.connect(self.selectPlateData)
        self.selectPlateData()

        self.parent.signal.connect(self.updateStatus)

    def selectPlateData(self):
        index = self.combo_box.currentIndex()

        plate_data = self.list_plate_data[index]

        self.plate_data = plate_data

        self.plot.figure.axes[0].set_aspect('equal', 'box')

        self.ax.cla()
        for well, well_name in zip(plate_data["wells"], plate_data["well_names"]):
            x, y, r = well
            circle1 = plt.Circle((x, y), r, color='lightgray', ec="gray")
            self.ax.add_artist(circle1)
            self.ax.plot(x, y, "+", color="gray", zorder=10)
            self.ax.text(x-r, y+r, well_name, color="black", zorder=10, va="top")

        border = []
        w = plate_data["extent"][1] - plate_data["extent"][0]
        h = plate_data["extent"][3] - plate_data["extent"][2]
        corner_size = w * 0.08
        if 1:
            border.append([plate_data["extent"][0], plate_data["extent"][2]])
            border.append([plate_data["extent"][1] - corner_size, plate_data["extent"][2]])
            border.append([plate_data["extent"][1], plate_data["extent"][2] + corner_size])
            border.append([plate_data["extent"][1], plate_data["extent"][3] - corner_size])
            border.append([plate_data["extent"][1] - corner_size, plate_data["extent"][3]])
            border.append([plate_data["extent"][0], plate_data["extent"][3]])
            border.append([plate_data["extent"][0], plate_data["extent"][2]])
            self.ax.set_ylim(plate_data["extent"][2] - h * 0.01, plate_data["extent"][3] + h * 0.01)
        else:
            border.append([plate_data["extent"][0], plate_data["extent"][2]])
            border.append([plate_data["extent"][1] - corner_size, plate_data["extent"][2]])
            border.append([plate_data["extent"][1], plate_data["extent"][2] - corner_size])
            border.append([plate_data["extent"][1], plate_data["extent"][3] + corner_size])
            border.append([plate_data["extent"][1] - corner_size, plate_data["extent"][3]])
            border.append([plate_data["extent"][0], plate_data["extent"][3]])
            border.append([plate_data["extent"][0], plate_data["extent"][2]])
            self.ax.set_ylim(plate_data["extent"][3] + h * 0.01, plate_data["extent"][2] - h * 0.01)
        border = np.array(border)

        self.ax.plot(border[:, 0], border[:, 1], "-", color="gray")

        self.plot_line, = self.plot.figure.gca().plot(0, 0, 'r+', ms=10)
        self.plot_line2, = self.plot.figure.gca().plot([], [], 'bx', ms=5)
        self.plot_line3, = self.plot.figure.gca().plot([0, 0, 0, 0, 0], [0, 0, 0, 0, 0], 'k-', ms=5)

        self.ax.set_xlim(plate_data["extent"][0] - w * 0.01, plate_data["extent"][1] + w * 0.01)
        self.ax.set_xticks([])
        self.ax.set_yticks([])

        self.updateList()

    def listKeyPress(self, event):
        if event.key() == QtCore.Qt.Key_Return:
            self.addPosition()
        if event.key() == QtCore.Qt.Key_G:
            self.gotoPosition()
        if event.key() == QtCore.Qt.Key_Delete:
            self.deletePosition()
        return self.list.keyPressEvent_old(event)

    def addCenters(self):
        z = self.mic.getZPos()
        self.positions = []
        self.position_names = []
        for x, y, r in self.plate_data["wells"]:
            self.positions.append([int(x), int(y), z])
            self.position_names.append("")
        self.updateList()

    def addMorePositions(self):
        count = 1
        overlap = 0.1
        well_names = ""
        class SelectNumberOfPositions(QtWidgets.QDialog):
            def __init__(self):
                QtWidgets.QDialog.__init__(self)

                # Widget
                self.setWindowTitle("Select Number of Frames")
                self.setWindowIcon(qta.icon("fa.play"))
                self.setModal(True)
                main_layout = QtWidgets.QVBoxLayout(self)

                self.label = QtWidgets.QLabel("How many positions per well?")
                main_layout.addWidget(self.label)

                self.spinBox = QtWidgets.QSpinBox()
                self.spinBox.setRange(1, 10)
                main_layout.addWidget(self.spinBox)

                self.label2 = QtWidgets.QLabel("How should the overlap? (negative means gap)")
                main_layout.addWidget(self.label2)

                self.spinBox2 = QtWidgets.QDoubleSpinBox()
                self.spinBox2.setRange(-10, 10)
                self.spinBox2.setValue(-0.1)
                self.spinBox2.setSingleStep(0.1)
                main_layout.addWidget(self.spinBox2)

                self.label3 = QtWidgets.QLabel("Which wells? (comma separated list, leave empty for all)")
                main_layout.addWidget(self.label3)

                self.well_names = QtWidgets.QLineEdit()
                main_layout.addWidget(self.well_names)

                # set LineEdit text to selected
                self.spinBox.findChild(QtWidgets.QLineEdit).selectAll()

                button2 = QtWidgets.QPushButton("Ok")

                def done():
                    nonlocal count, overlap, well_names
                    count = self.spinBox.value()
                    overlap = self.spinBox2.value()
                    well_names = self.well_names.text()
                    self.done(1)

                button2.clicked.connect(done)
                main_layout.addWidget(button2)

        if not SelectNumberOfPositions().exec_():
            return

        well_names = [w.strip() for w in well_names.split(",") if w.strip() != ""]

        dx = int(self.cam.getWidth() * (
                    1 - overlap) * self.cam.getPixelSize() / self.mic.getEffectiveMagnification() / self.mic.getXResolution())
        dy = int(self.cam.getHeight() * (
                    1 - overlap) * self.cam.getPixelSize() / self.mic.getEffectiveMagnification() / self.mic.getYResolution())

        well_positions = [
            [], # 0 pos
            [[0,0]], # 1 pos
            [[0,-0.5],[0,0.5]], # 2 pos
            [[0,-1],[0,0],[0,1]], # 3 pos
            [[-0.5,-0.5],[-0.5,0.5],[0.5,-0.5],[0.5,0.5]], # 4 pos
            [[0, -1], [-1,0], [0, 0], [1, 0], [0, 1]],     # 5 pos
            [[-0.5,-1],[0.5,-1],[-0.5,0],[0.5,0], [-0.5,1],[0.5,1]], # 6 pos
            [[-0.5,-1],[0.5,-1],[-1,0],[0,0],[1,0], [-0.5,1],[0.5,1]], # 7 pos
            [[-0.5,-1],[0.5,-1],[-1.5,0],[-0.5,0],[0.5,0],[1.5,0], [-0.5,1],[0.5,1]], # 8 pos
            [[-1,-1],[0,-1],[1,-1],[-1,0],[0,0],[1,0], [-1,1],[0,1],[1,1]], # 9 pos
            [[-1,-1],[0,-1],[1,-1], [-1.5,0],[-0.5,0],[0.5,0],[1.5,0], [-1,1],[0,1],[1,1]], # 10 pos
        ]

        z = self.mic.getZPos()
        self.positions = []
        self.position_names = []
        for (x, y, r), name in zip(self.plate_data["wells"], self.plate_data["well_names"]):
            if len(well_names) != 0 and str(name) not in well_names:
                continue
            index = 1
            for offsetx, offsety in well_positions[count]:
                self.positions.append([int(x)+offsetx*dx, int(y)+offsety*dy, z])
                self.position_names.append(f"w{name}p{index}")
                index += 1
        self.updateList()

    def addPosition(self):
        position = self.mic.getPos()
        selections = self.list.selectedItems()
        if len(selections) == 0 or self.list.currentRow() == self.list.count() - 1:
            self.positions.append(position)
            self.position_names.append("")
            new_index = len(self.positions)
            added_index = new_index - 1
        else:
            self.positions[self.list.currentRow()] = position
            self.position_names[self.list.currentRow()] = ""
            new_index = self.list.currentRow()
            added_index = new_index

        pos_name = ""
        for (x, y, r), name in zip(self.plate_data["wells"], self.plate_data["well_names"]):
            if np.sqrt((position[0]-x)**2 + (position[1]-y)**2) < r:
                index = 0
                while True:
                    index += 1
                    pos_name = f"w{name}p{index}"
                    for position_name in self.position_names:
                        if position_name == pos_name:
                            break
                    else:
                        break
        self.position_names[added_index] = pos_name
        self.updateList()
        self.list.setCurrentRow(new_index)

    def deletePosition(self):
        selections = self.list.selectedItems()
        if len(selections) == 0 or self.list.currentRow() == self.list.count() - 1:
            pass
        else:
            index = self.list.currentRow()
            self.positions.pop(self.list.currentRow())
            self.position_names.pop(self.list.currentRow())
            self.updateList()
            if index == self.list.count() - 1 and index != 0:
                index -= 1
            self.list.setCurrentRow(index)

    def deleteAllPosition(self):
        self.positions = []
        self.position_names = []
        self.updateList()

    def gotoPosition(self):
        selections = self.list.selectedItems()
        if len(selections) == 0 or self.list.currentRow() == self.list.count() - 1:
            pass
        else:
            index = self.list.currentRow()
            with self.mic.nowait:
                self.mic.setPos(self.positions[index])

    def updateList(self):
        selections = self.list.selectedItems()
        if len(selections) == 0:# or self.list.currentRow() == self.list.count() - 1:
            row = 0
        else:
            row = self.list.currentRow()

        self.list.clear()
        for index, position in enumerate(self.positions):
            item = QtWidgets.QListWidgetItem(qta.icon("fa.crosshairs"), "%2d (x: %6d, y: %6d, z: %6d) %s" % (index, position[0], position[1], position[2], self.position_names[index]), self.list)
        item = QtWidgets.QListWidgetItem(qta.icon("fa.plus"), "free slot", self.list)
        self.plot_line2.set_data([p[0] for p in self.positions], [p[1] for p in self.positions])
        self.plot.draw()
        self.saveFile(positions_file)
        self.list.setCurrentRow(row)

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
        with open(filename, "w") as fp:
            for (x, y, z), name in zip(self.positions, self.position_names):
                if name != "":
                    fp.write(f"{x} {y} {z} # {name}\n")
                else:
                    fp.write(f"{x} {y} {z}\n")

    def ButtonLoad(self):
        fileName = QtWidgets.QFileDialog.getOpenFileName(self, "Open Positions", "", "Position Files (*.txt)")
        if isinstance(fileName, tuple):
            filename = str(fileName[0])
        else:
            filename = str(fileName)
        if os.path.exists(fileName[0]):
            self.loadFile(fileName[0])

    def loadFile(self, fileName):
        print("Loading:", fileName)
        self.positions = []
        self.position_names = []
        try:
            with open(fileName, "r") as fp:
                for line in fp:
                    data = [v.strip() for v in line.split() if v.strip() != "#"]
                    x = int(data[0])
                    y = int(data[1])
                    z = int(data[2])
                    name = data[3] if len(data) >= 4 else ""
                    self.positions.append([x, y, z])
                    self.position_names.append(name)
        except IOError:
            return
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
            self.mic.setX(int(value / self.conversion[i]))
        if i == 1:
            self.mic.setY(int(value / self.conversion[i]))
        if i == 2:
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
        self.input_exposure = QInputNumber(
            self.layout, "Exposure", self.cam.exposure(), min_exp, max_exp,
            use_slider=True, unit="ms",
            tooltip="Remembered separately for each method and fluorescence filter during this viewer session.",
        )
        self.input_gain = None
        gain = self.cam.gain()
        if gain is not None and np.isfinite(gain):
            min_gain, max_gain = self.cam.get_gain_range()
            self.input_gain = QInputNumber(self.layout, "Gain", gain, min_gain, max_gain, use_slider=True)
            self.input_gain.valueChanged.connect(lambda v: self.valueChanged(v, 1))
        self.input_exposure.valueChanged.connect(lambda v: self.valueChanged(v, 0))

        self.parent.signal.connect(self.updateStatus)
        self.parent.signal_new_image.connect(self.updateStatus)
        self.parent.signal_properties_changed.connect(self.updateStatus)
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
        if not self.input_exposure.slider_dragged:
            self.input_exposure.setValue(self.cam.exposure())
            # Readback is the baseline for the next edit, including after a mode switch.
            self.input_exposure.last_emited_value = self.input_exposure.value()
        if self.input_gain is not None and not self.input_gain.slider_dragged:
            gain = self.cam.gain()
            if gain is not None and np.isfinite(gain):
                self.input_gain.setValue(gain)
                self.input_gain.last_emited_value = self.input_gain.value()


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

        if self.cam.binning():
            self.input_binning = QInputNumber(self.layout, "Binning", self.cam.binning(), 1, 8, use_slider=True, float=False)
            self.input_binning.valueChanged.connect(lambda v: self.valueChanged(v, 1))

        self.input_crop.valueChanged.connect(lambda v: self.valueChanged(v, 0))

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
        else:
            print("Set ROI height to", value)
            crop = 2192 - value
            crop = crop - crop % (8*(self.cam.binning() if self.cam.binning() else 1))
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
        self.setMaximumHeight(130)

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

        self.checkbox_autocontrast = QtWidgets.QCheckBox("Auto-contrast (fluorescence)")
        self.checkbox_autocontrast.setChecked(self.parent.auto_contrast)
        self.checkbox_autocontrast.stateChanged.connect(self.toggleAutoContrast)
        self.layout.addWidget(self.checkbox_autocontrast)

        self.parent.signal_new_image.connect(self.updateStatus)

    def toggleAutoContrast(self, state):
        self.parent.auto_contrast = (state == QtCore.Qt.Checked)
        self.parent.showImage()

    def updateStatus(self):
        max = self.parent.im_max
        self.setTitle(f"Histogram {100 * max / self.max_value:3.1f}% ({max})")
        self.plot_line.set_data(self.parent.im_bins[:-1], self.parent.im_hist)
        self.label.setText(f"Overexposed: {int(self.parent.im_hist[-2]*1000)}%")
        self.plot.figure.gca().set_ylim(0, self.parent.im_hist[:-2].max()*1.05)
        self.plot.draw()


class ModuleSaveImage(QtWidgets.QGroupBox):
    last_folder = ""

    def __init__(self, parent, layout):
        QtWidgets.QWidget.__init__(self)
        self.parent = parent
        layout.addWidget(self)
        self.setTitle("Record")
        self.mic = parent.mic
        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)
        self.setMinimumWidth(200)

        self.layout1 = QtWidgets.QHBoxLayout()
        self.layout.addLayout(self.layout1)

        self.layout2 = QtWidgets.QHBoxLayout()
        self.layout.addLayout(self.layout2)

        self.button_save_image = QtWidgets.QPushButton("Save Image")
        self.layout2.addWidget(self.button_save_image)

        self.button_save_image.clicked.connect(self.ButtonSaveImage)

        #self.updateButtonContinuosText()

        #self.parent.signal_new_image.connect(self.updateStatus)

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
            self.mic.saveImage(filename, self.parent.im)
            print(filename, "saved")


class ModuleScaleBar(QtWidgets.QGroupBox):

    def __init__(self, parent):
        QtWidgets.QWidget.__init__(self)
        self.parent = parent
        self.mic = parent.mic
        self.cam = parent.cam

        self.font = QtGui.QFont()
        self.font.setPointSize(16)

        self.pixtomu = self.cam.getPixelSize()
        self.magnification = 1

        self.coupler = 1
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
        self.parent.signal_coupler_changed.connect(self.updateStatus)

        self.updateStatus()

    def updateStatus(self):
        try:
            self.magnification = self.mic.getMagnification()
        except IOError:
            self.magnification = 1

        try:
            self.coupler = self.mic.getCoupler()
        except IOError:
            self.coupler = 1

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


class Window(QtWidgets.QWidget):
    signal = QtCore.Signal()
    window_settings = None
    im = None

    signal_properties_changed = QtCore.Signal()

    signal_init = QtCore.Signal()
    signal_new_image = QtCore.Signal()
    signal_objective_changed = QtCore.Signal()
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

    signal_image_arrived = QtCore.Signal(object)

    def zoomEvent(self, scale, pos):
        self.signal_zoom.emit(scale, pos)

    def update(self):
        self.mic.getAllProperties()
        self.signal_properties_changed.emit()

    def _exposure_key(self):
        mode = self.mic.properties["current_mode"]
        channel = None
        if mode in (Microscope.MODE_FLUO, Microscope.MODE_FLUO_PH, Microscope.MODE_FLUO_DIC):
            channel = self.mic.properties["current_filter"]
        return mode, channel

    def setMode(self, mode, fluo_channel=None):
        """Restore live-view exposure without changing recording-mode behaviour."""
        previous_key = self._exposure_key()
        self._exposure_by_mode[previous_key] = self.cam.exposure()
        self.mic.setMode(mode, fluo_channel)
        self.mic.getAllProperties()
        key = self._exposure_key()
        try:
            if key != previous_key and key in self._exposure_by_mode:
                self.cam.setExposure(self._exposure_by_mode[key])
            # An unvisited method/filter keeps the current exposure until edited.
        finally:
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

        print("Connecting to microscope...")
        try:
            self.mic = Microscope(no_camera=True)
        except NoMicroscopeFound as err:
            print("leica_microscope.microscope.NoMicroscopeFound:", err, file=sys.stderr)
            self.mic = None

        self.cam = MemmapReader()
        self._exposure_by_mode = {}
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
        self.view.zoomEvent = self.zoomEvent
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
        ModuleSaveImage(self, right_layout)
        #ModuleSnap(self, right_layout)
        #ModuleProperties(self, right_layout)
        right_layout.addStretch()

        self.module_scalebar = ModuleScaleBar(self)

        self.pixmap = QtWidgets.QGraphicsPixmapItem(QtGui.QPixmap(1344,1024),self.origin)
        self.cam.setStreamCallback(lambda im: self.signal_image_arrived.emit(im))
        self.signal_image_arrived.connect(self.updateview)

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

    def showImage(self):
        if self.im.shape[0] != 0:
            max_brightness = np.amax(self.im)
            if max_brightness <= 0:
                im_display = np.zeros(self.im.shape, dtype=np.uint8)
            elif self.auto_contrast:
                im_f = self.im.astype(np.float64)
                im_f -= np.percentile(im_f, 0.01)
                hi = np.percentile(im_f, 99.99)
                if hi < 1:
                    hi = float(max_brightness)
                im_display = np.clip(im_f / hi * 255, 0, 255).astype(np.uint8)
            else:
                max_value = (100*max_brightness/self.cam.getMaxValue()-5.1)/(40-5.1)*255
                max_value = min(255, max(0, max_value))
                im_display = self.im * (max_value / max_brightness)
            # Display adjustment never changes the raw image used for recording.
            self.pixmap.setPixmap(QtGui.QPixmap(array2qimage(im_display)))

    last_update_time = 0
    auto_contrast = False
    def updateview(self, im):
        # update no more than 10 times per second
        if time.time() - self.last_update_time < 0.1:
            return

        self.im = im

        # calculate maximum and histogram
        self.im_max = np.amax(self.im)
        self.im_hist, self.im_bins = np.histogram(self.im[::4, ::4], bins=np.arange(0, self.cam.getMaxValue() + 20, 10),
                                              density=True)
        # display the image
        self.showImage()
        self.view.setExtend(self.im.shape[1], self.im.shape[0])

        self.last_update_time = time.time()
        self.signal_new_image.emit()
        
    def closeEvent(self, event):
        self.cam.stop()
        if self.window_settings is not None:
            self.window_settings.close()


class Timeit:
    def __init__(self, name):
        self.name = name

    def __enter__(self):
        self.time = time.time()

    def __exit__(self, exc_type, exc_val, exc_tb):
        print("TIMEIT", self.name, time.time()-self.time)


if __name__ == '__main__':
    if sys.platform[:3] == 'win':
        myappid = 'fabrybiophysics.liveviewer' # arbitrary string
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    try:
        window = Window()
    except Exception as err:
        import traceback
        traceback.print_exc()
        splash.close()
        QtWidgets.QMessageBox.critical(None, "LiveViewer could not start", str(err))
        sys.exit(1)
    window.show()
    splash.finish(window)
    sys.exit(app.exec_())
