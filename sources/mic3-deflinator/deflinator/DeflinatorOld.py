# -*- coding: utf-8 -*-
from __future__ import division, print_function
import qtawesome as qta
import sys
import os
import ctypes
from qtpy import QtCore, QtGui, QtWidgets
import xlwt
import xlrd
import glob
import shutil
from threading import Thread

from qimage2ndarray import array2qimage

import time
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
sys.path.append(r"C:\Software\MicroscopeToolsProject\qextendedgraphicsview")
from QExtendedGraphicsView import QExtendedGraphicsView

sys.path.append(r"C:\Software\MicroscopeToolsProject\microscopetools")
from Tools import HelpText, GraphicsItemEventFilter

from microscopehandler.CameraClient import Camera
from microscopehandler.MicroscopeClient import microscope, STATE_Empty

icon_path = os.path.join(os.path.dirname(__file__), "..", "icons")

sensor_size = 6.45

mic = None
mmc = None

output_path = os.path.join(os.getenv('APPDATA'), "Microscope")
if not os.path.exists(output_path):
    os.mkdir(output_path)

record_file = r"C:\Software\MicroscopeToolsProject\microscopetools\Record.py"
record_progress_file = r"C:\Software\MicroscopeToolsProject\microscopehandler\microscopehandler\Flask\percent.txt"
clickpoints_file = r"C:\Software\clickpoints\ClickPoints.bat"
last_folder = ""

path_folder_save = os.path.join(output_path, "Delfinator_path.txt")
if os.path.exists(path_folder_save):
    with open(path_folder_save, "r") as fp:
        last_folder = fp.read().strip()

def my_excepthook(type, value, tback):
    # log the exception here

    # then call the default handler
    sys.__excepthook__(type, value, tback)

sys.excepthook = my_excepthook


def AddQLineEdit(layout, text, value=None, strech=False):
    horizontal_layout = QtWidgets.QHBoxLayout()
    layout.addLayout(horizontal_layout)
    text = QtWidgets.QLabel(text)
    lineEdit = QtWidgets.QLineEdit()
    if value:
        lineEdit.setText(value)
    lineEdit.label = text
    horizontal_layout.addWidget(text)
    horizontal_layout.addWidget(lineEdit)
    lineEdit.managingLayout = horizontal_layout
    if strech:
        horizontal_layout.addStretch()
    return lineEdit


def autofocus(x, y, z=None, dx=32, dy=32, slice_thickness=10, slice_count=21):
    from scipy.ndimage.filters import sobel
    global mmc, mic

    SingleImages = False

    halft_slice_count = int(slice_count // 2)

    slice_start = -halft_slice_count
    slice_stop = halft_slice_count

    StepToMu = mic.getResolutionZ()

    if slice_start > slice_stop:
        slice_start, slice_stop = (slice_stop, slice_start)

    slice_thickness /= StepToMu
    slice_thickness = int(slice_thickness)

    z_positions = np.arange(slice_start, slice_stop + 2) * slice_thickness

    if z is None:
        z = mic.getZ()
    mic.setZ(z + z_positions[0])

    was_running = mmc.isSequenceRunning()
    if was_running:
        mmc.stopSequenceAcquisition()
    # old_roi = mmc.getROI()
    # print(old_roi)
    mmc.clearROI()
    h = mmc.getImageHeight()
    w = mmc.getImageWidth()
    mmc.setROI(x - int(dx / 2), y - int(dy / 2), dx, dy)
    mmc.startContinuousSequenceAcquisition(1)

    sharp = np.zeros(len(z_positions))

    mmc.clearImages()

    last_image = len(z_positions[1:]) - 1
    print(z, z_positions)
    for index, z_offset in enumerate(z_positions[1:]):
        t = time.time()
        print(index)
        if SingleImages:
            mmc.snapImage()
            if index != last_image:
                mic.setZ(z + z_offset)
            im = mmc.getImage()

            im = im / max([np.amax(im), 0.01])  # don't divide by zero
            sobelX = sobel(im / np.amax(im), 0) / 2
            sobelY = sobel(im / np.amax(im), 1) / 2
            sobelAll = np.sqrt(sobelX ** 2 + sobelY ** 2)
            sharp[index] = np.std(sobelAll)

            if index != last_image:
                mic.waitForMyCommands()
        else:
            while not mmc.getRemainingImageCount():
                pass
            im = mmc.getLastImage()

            im = im / max([np.amax(im), 0.01])  # don't divide by zero
            sobelX = sobel(im / np.amax(im), 0) / 2
            sobelY = sobel(im / np.amax(im), 1) / 2
            sobelAll = np.sqrt(sobelX ** 2 + sobelY ** 2)
            sharp[index] = np.std(sobelAll)

            cmd = mic.setZ(z + z_offset)
            if index != last_image:
                mic.waitForCommand(cmd)
            mmc.clearImages()

    mmc.stopSequenceAcquisition()
    # mmc.setROI(*old_roi)
    mmc.startContinuousSequenceAcquisition(1)

    index = np.argmax(sharp)
    from matplotlib import pyplot as plt
    plt.plot(z_positions * StepToMu, sharp)
    plt.show()

    if index == 0 or index == len(sharp) - 1:
        print("ERROR too much out of focus")
        delta_z = 0
    else:
        corrected_index = sum(sharp[index - 1:index + 2] * np.array([-1, 0, 1])) / np.sum(
            sharp[index - 1:index + 2]) + index
        delta_z = (corrected_index - halft_slice_count) * slice_thickness
    print("Autofocus", delta_z * StepToMu)
    mic.setZ(z + delta_z)
    return delta_z


class AskWindow(QtWidgets.QWidget):
    def __init__(self, parent=None):
        global mmc, mic, exposure_time, gain_values
        QtWidgets.QWidget.__init__(self)
        self.deflinator = parent
        self.setWindowTitle('Deflinator K')
        self.setWindowIcon(QtGui.QIcon(QtGui.QIcon(os.path.join(icon_path, "LiveViewer.ico"))))
        # self.setGeometry(100, 100, 1300, 800)

        self.layout = QtWidgets.QVBoxLayout(self)

        self.label = QtWidgets.QLabel("Do you want to open an exiting measurement or a new mesaurement?")
        self.layout.addWidget(self.label)

        self.tools_layout = QtWidgets.QHBoxLayout()
        self.layout.addLayout(self.tools_layout)

        button = QtWidgets.QPushButton("Exiting Folder")
        self.tools_layout.addWidget(button)
        button.clicked.connect(self.askFolder)

        button = QtWidgets.QPushButton("New Folder")
        self.tools_layout.addWidget(button)
        button.clicked.connect(self.askFolder)

        button = QtWidgets.QPushButton("Abort")
        self.tools_layout.addWidget(button)
        button.clicked.connect(self.close)

    def askFolder(self):
        self.setEnabled(False)
        filename = QtWidgets.QFileDialog.getExistingDirectory(self, "Save Path", last_folder)
        if isinstance(filename, tuple):
            filename = str(filename[0])
        else:
            filename = str(filename)
        if filename:
            with open(path_folder_save, "w") as fp:
                fp.write(filename)
            self.filename = filename
            print("Select the bottom of the device using the arrow keys")
            self.deflinator.show()
            self.deflinator.setFilename(filename)
            self.hide()
        else:
            self.close()
        self.setEnabled(True)


class SelectName(QtWidgets.QDialog):
    def __init__(self, name):
        QtWidgets.QDialog.__init__(self)

        # Widget
        self.setWindowTitle("Rename Position - Deflinator")
        self.setWindowIcon(qta.icon("fa.rocket"))
        self.setModal(True)
        main_layout = QtWidgets.QVBoxLayout(self)
        self.name = name
        self.edit = AddQLineEdit(main_layout, "Position:", value=name[0])
        # set LineEdit text to selected
        self.edit.selectAll()

        button2 = QtWidgets.QPushButton("Ok")
        button2.clicked.connect(self.ok)
        self.edit.managingLayout.addWidget(button2)

    def ok(self):
        self.name[0] = self.edit.text()
        self.done(1)


class Window(QtWidgets.QWidget):
    crop = 1
    speed = [0, 0, 0]
    last_command = [None, None, None]

    signal_recordFinished = QtCore.Signal()

    recording = False

    def sceneEventFilter(self, event):
        if event.type() == QtCore.QEvent.GraphicsSceneMousePress and event.button() == QtCore.Qt.LeftButton:
            pos = event.pos()  # self.view.mapFromView(event.pos())
            print(pos.x(), pos.y())
            autofocus(pos.x(), pos.y())
            self.last_x = pos.x()
            self.last_y = pos.y()
            self.toggleCrop()
            self.toggleCrop()
            return True
        return False

    def __init__(self, parent=None):
        global mmc, mic, exposure_time, gain_values
        QtWidgets.QWidget.__init__(self, parent)
        self.setWindowTitle('Deflinator K')
        # self.setWindowIcon(QtGui.QIcon(QtGui.QIcon(os.path.join(icon_path, "LiveViewer.ico"))))
        self.setWindowIcon(qta.icon("fa.rocket"))
        self.setGeometry(100, 100, 1300, 800)

        self.layout = QtWidgets.QVBoxLayout(self)

        self.progressbar = QtWidgets.QProgressBar()
        self.layout.addWidget(self.progressbar)

        # self.label = QtWidgets.QLabel(self)
        # self.label.setFont(QtGui.QFont("serif", 20))
        # self.layout.addWidget(self.label)
        # self.label.setAlignment(QtCore.Qt.AlignCenter)

        self.tools_layout = QtWidgets.QHBoxLayout()
        self.layout.addLayout(self.tools_layout)

        self.view_layout = QtWidgets.QHBoxLayout()
        self.layout.addLayout(self.view_layout)

        self.tools2_layout = QtWidgets.QHBoxLayout()
        self.layout.addLayout(self.tools2_layout)

        self.view = QExtendedGraphicsView()
        self.local_scene = self.view.scene
        self.origin = self.view.origin
        self.view_layout.addWidget(self.view)

        self.pixmap = QtWidgets.QGraphicsPixmapItem(QtGui.QPixmap(1344, 1024), self.origin)

        self.event_filter = GraphicsItemEventFilter(self.origin, self)
        self.pixmap.installSceneEventFilter(self.event_filter)

        self.tableWidget = QtWidgets.QTableWidget(4, 3 * 6, self)
        self.tools2_layout.addWidget(self.tableWidget)
        self.row_headers = ["%d%d" % (j + 1, i + 1) for j in range(6) for i in range(3)]
        self.tableWidget.setHorizontalHeaderLabels(self.row_headers)
        self.tableWidget.horizontalHeader().sectionDoubleClicked.connect(self.changeRowHeader)
        self.tableWidget.setVerticalHeaderLabels(["Bottom", "Layer", "Top", "Record"])
        self.tableWidget.setMinimumHeight(180)
        self.tableWidget.setCurrentCell(0, 0)
        self.tableWidget.cellClicked.connect(self.cellSelected)

        self.buttons = []

        self.button_next = QtWidgets.QPushButton("Next (T)")
        self.button_next.clicked.connect(self.goToNext)
        self.tools_layout.addWidget(self.button_next)
        self.buttons.append(self.button_next)

        self.button_previous = QtWidgets.QPushButton("Previous (Z)")
        self.button_previous.clicked.connect(self.goToPrevious)
        self.tools_layout.addWidget(self.button_previous)
        self.buttons.append(self.button_previous)

        self.button_view = QtWidgets.QPushButton("Toggle View (F)")
        self.button_view.clicked.connect(self.toggleCrop)
        self.tools_layout.addWidget(self.button_view)
        self.buttons.append(self.button_view)

        self.button_store = QtWidgets.QPushButton("Store Position (Return)")
        self.button_store.clicked.connect(self.storePosition)
        self.tools_layout.addWidget(self.button_store)
        self.buttons.append(self.button_store)

        self.button_record = QtWidgets.QPushButton("Record (R)")
        self.button_record.clicked.connect(self.record)
        self.tools_layout.addWidget(self.button_record)
        self.buttons.append(self.button_record)

        self.button_clickpoints = QtWidgets.QPushButton("KackPoints (C)")
        self.button_clickpoints.clicked.connect(self.clickPoints)
        self.tools_layout.addWidget(self.button_clickpoints)
        self.buttons.append(self.button_clickpoints)

        self.spinbox_exposure = QtWidgets.QSpinBox()
        #self.spinbox_exposure.valueChanged.connect(self.exposureChanged)
        self.tools_layout.addWidget(self.spinbox_exposure)
        self.buttons.append(self.spinbox_exposure)

        self.spinbox_frames = QtWidgets.QSpinBox()
        self.spinbox_frames.setRange(0, 10000)
        self.spinbox_frames.setValue(100)
        self.tools_layout.addWidget(self.spinbox_frames)
        self.buttons.append(self.spinbox_frames)

        self.tools_layout.addStretch()

        print("Conneting to camera server...")
        mmc = Camera()
        mmc.nowait = True
        mmc.no_exceptions = True
        mmc.startContinuousSequenceAcquisition(1)
        mic = microscope()  # mmc
        print("... connected")

        # set the roi
        self.toggleCrop()

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.updateview)
        self.timer.start(100)

        self.positions = [[None, None, None] for i in range(3 * 6)]
        self.position_index = 0
        self.positions_xy = [[None, None] for i in range(3 * 6)]
        self.xy_initialized = False
        self.row_index = 0
        self.position_recorded = [False] * (3 * 6)

        self.conversionX = mic.getResolutionX()
        self.conversionY = mic.getResolutionY()
        self.conversionZ = mic.getResolutionZ() / 1000

        self.dx = (428726 - 368438) / 2 / 2
        self.dy = (244758 - 344646) / 5 / 2

        # center window in desktop
        DRect = QtWidgets.QDesktopWidget().screenGeometry()
        WRect = self.geometry()
        self.move((DRect.width() - WRect.width()) / 2, (DRect.height() - WRect.height()) / 4)

        self.signal_recordFinished.connect(self.recordFinished)

        self.window_ask = AskWindow(self)
        self.window_ask.show()
        # self.setFilename(r"D:\Richard\\")

        # self.label.setText("Move the microscope to the first position (top left)")

    setting_exposure = False
    def setExposure(self, value):
        self.setting_exposure = True
        try:
            mmc.setExposure(value)
        finally:
            self.setting_exposure = False

    def changeRowHeader(self, index):
        name = [self.row_headers[index]]
        self.select_name_window = SelectName(name)
        self.select_name_window.exec_()
        new_name = name[0]
        old_path = os.path.join(self.folder, self.row_headers[index])
        if os.path.exists(old_path):
            shutil.move(old_path, os.path.join(self.folder, new_name))
        self.row_headers[index] = new_name
        print(self.row_headers)
        self.updateTable()
        self.save()

    def setFilename(self, filename):
        self.show()
        self.folder = filename
        if os.path.exists(os.path.join(self.folder, "data.xls")):
            book = xlrd.open_workbook(os.path.join(self.folder, "data.xls"))
            sh = book.sheet_by_index(0)
            self.row_headers = []
            for j in range(1, 3 * 6 + 1):
                row = sh.row(j)
                self.row_headers.append(row[0].value[2:-2])
                for i in range(1, 3 + 1):
                    try:
                        self.positions[j - 1][i - 1] = float(row[i].value)
                    except ValueError:
                        self.positions[j - 1][i - 1] = None
            for i in range(3 * 6):
                if len(glob.glob(os.path.join(self.folder, self.getPositionName(i), "*.tif"))):
                    self.position_recorded[i] = True
                else:
                    self.position_recorded[i] = False

            try:
                self.positions_xy = np.loadtxt(os.path.join(self.folder, "positions.txt"))
            except IOError:
                pass
            else:
                self.xy_initialized = True

            self.updateTable()

    def keyPressEvent(self, event):
        # @key ---- General ----
        # if event.key() == QtCore.Qt.Key_F1:
        #    # @key F1: toggle help window
        #    self.HelpText.ShowHelpText()

        if self.recording:
            return

        if event.key() == QtCore.Qt.Key_F:
            # @key F: fit image to view
            self.view.fitInView()
            self.toggleCrop()

        # if event.key() == QtCore.Qt.Key_R:
        #    self.pos = mic.getPos()
        #    filename = QtWidgets.QFileDialog.getExistingDirectory(self, "Save Path", "")
        #    if isinstance(filename, tuple):
        #        filename = str(filename[0])
        #    else:
        #        filename = str(filename)
        #    if filename:
        #        self.filename = filename
        #        print("Select the bottom of the device using the arrow keys")
        #        self.positions.append([])

        if not event.isAutoRepeat():
            if event.key() == QtCore.Qt.Key_Home:
                self.setSpeed(2, 999999)
            if event.key() == QtCore.Qt.Key_End:
                self.setSpeed(2, -999999)
            if event.key() == QtCore.Qt.Key_PageUp:
                self.setSpeed(2, 999999 / 4)
            if event.key() == QtCore.Qt.Key_PageDown:
                self.setSpeed(2, -999999 / 4)

            if event.key() == QtCore.Qt.Key_Left:
                self.setSpeed(0, -9999)
            if event.key() == QtCore.Qt.Key_Right:
                self.setSpeed(0, 9999)

            if event.key() == QtCore.Qt.Key_Up:
                self.setSpeed(1, 9999)
            if event.key() == QtCore.Qt.Key_Down:
                self.setSpeed(1, -9999)

        if event.key() == QtCore.Qt.Key_Return:
            self.storePosition()

        if event.key() == QtCore.Qt.Key_R:
            self.record()

        if event.key() == QtCore.Qt.Key_W:
            print(mic.getPos())

        if event.key() == QtCore.Qt.Key_T:
            if not self.xy_initialized:
                print("Initialize first position!")
            else:
                self.goToNext()
                self.goToPosition()

        if event.key() == QtCore.Qt.Key_Z:
            if not self.xy_initialized:
                print("Initialize first position!")
            else:
                self.goToPrevious()
                self.goToPosition()

        if event.key() == QtCore.Qt.Key_Escape:
            self.close()

    def keyReleaseEvent(self, event):
        if not event.isAutoRepeat():
            if event.key() == QtCore.Qt.Key_Home or event.key() == QtCore.Qt.Key_End:
                self.setSpeed(2, 0)
            if event.key() == QtCore.Qt.Key_PageUp or event.key() == QtCore.Qt.Key_PageDown:
                self.setSpeed(2, 0)
            if event.key() == QtCore.Qt.Key_Left or event.key() == QtCore.Qt.Key_Right:
                self.setSpeed(0, 0)
            if event.key() == QtCore.Qt.Key_Up or event.key() == QtCore.Qt.Key_Down:
                self.setSpeed(1, 0)

    def setSpeed(self, index, speed):
        if self.speed[index] != speed:
            self.speed[index] = speed
            print(self.speed)
            if speed == 0:
                mic.sendCommand([72, 73, 71][index], 21)
            else:
                mic.sendCommand([72, 73, 71][index], 25, self.speed[index])

    def storePosition(self):
        if self.row_index == 3:
            self.record()
        else:
            pos = mic.getPos()
            if self.xy_initialized is False:
                for i in range(3 * 6):
                    self.positions_xy[i] = [pos[0] + self.dx * (i % 3), pos[1] + self.dy * (i // 3)]
                self.xy_initialized = True
                print(self.positions_xy)
            else:
                self.positions_xy[self.position_index] = [pos[0], pos[1]]
            self.positions[self.position_index][self.row_index] = pos[2] * self.conversionZ
            self.snapfolder = os.path.join(self.folder, self.getPositionName(), 'Snapshots')
            if not os.path.exists(os.path.join(self.folder, self.getPositionName())):
                os.mkdir(os.path.join(self.folder, self.getPositionName()))
            if not os.path.exists(self.snapfolder):
                os.mkdir(self.snapfolder)
            mmc.saveImage(os.path.join(self.snapfolder, ["Bottom.tif", "Layer.tif", "Top.tif"][self.row_index]),
                          self.im, microscope=mic)

            self.row_index = (self.row_index + 1) % 4
            if self.row_index == 0:
                self.goToNext()
            else:
                self.updateTable()
            self.goToPosition()

    def goToPosition(self):
        print("goToPosition", self.position_index, self.row_index)
        j = self.row_index
        if self.row_index == 3:
            j = 2
        i = self.position_index
        while i >= 0:
            if self.positions[i][j] is not None:
                mic.setZ(self.positions[i][j] / self.conversionZ, wait=False)
                break
            i -= 1
        if self.xy_initialized:
            pos = self.positions_xy[self.position_index]
            mic.setX(pos[0], wait=False)
            mic.setY(pos[1], wait=False)

    def record(self):
        record_path = os.path.join(self.folder, self.getPositionName())
        last_recording = glob.glob(os.path.join(record_path, "*Config.txt"))
        if len(last_recording):
            timestamp = os.path.split(last_recording[0])[1][:15]
            print(last_recording, timestamp)
            last_images = glob.glob(os.path.join(record_path, timestamp + "*.tif"))
            last_images.append(last_recording[0])
            for file in last_images:
                os.remove(file)

        config_path = os.path.join(output_path, "Deflinator_Config.txt")
        config_template = os.path.join(os.path.dirname(__file__), "Record_Config.txt")
        with open(config_template, "r") as fp:
            config = fp.read()
        config = config.format(path=record_path, framecount=self.spinbox_frames.value())
        with open(config_path, "w") as fp:
            fp.write(config)
        command = "python" + " " + record_file + " " + config_path
        self.progressbar.setMaximum(0)
        self.progressbar.setValue(0)
        self.thread = Thread(target=self.doRecord, args=(command,))
        self.thread.setDaemon(True)
        self.thread.start()
        self.recording = True
        for button in self.buttons:
            button.setEnabled(False)

    def doRecord(self, command):
        os.system(command)
        self.signal_recordFinished.emit()

    def recordFinished(self):
        self.recording = False
        for button in self.buttons:
            button.setEnabled(True)
        mmc.startContinuousSequenceAcquisition(1)
        self.progressbar.setValue(0)
        self.position_recorded[self.position_index] = True

        self.row_index = 0
        self.goToNext()
        self.goToPosition()

        self.updateTable()

    def clickPoints(self):
        file = glob.glob(os.path.join(self.folder, self.getPositionName(), "*.tif"))[0]
        print(clickpoints_file + " " + file)
        os.system(clickpoints_file + " " + file)

    def updateTable(self):
        headers = []
        for i in range(len(self.positions)):
            for j in range(len(self.positions[i])):
                item = self.tableWidget.item(j, i)
                if item is None:
                    item = QtWidgets.QTableWidgetItem("")
                    self.tableWidget.setItem(j, i, item)
                if self.positions[i][j] is not None:
                    item.setText("%.2f mm" % self.positions[i][j])
                else:
                    item.setText("")
            headers.append(self.getColumnHeaderName(i))
            item = self.tableWidget.item(3, i)
            if item is None:
                item = QtWidgets.QTableWidgetItem("")
                self.tableWidget.setItem(3, i, item)
            if self.position_recorded[i]:
                item.setText("done")
            else:
                item.setText("")

        self.tableWidget.setHorizontalHeaderLabels(headers)
        self.tableWidget.setCurrentCell(self.row_index, self.position_index)
        self.save()

    def getColumnHeaderName(self, index):
        if self.position_recorded[index]:
            return "* %s *" % self.getPositionName(index)
        return "- %s -" % self.getPositionName(index)

    def cellSelected(self, row, column):
        print(self.xy_initialized)
        if not self.xy_initialized:
            self.position_index = 0
            self.row_index = 0
            self.tableWidget.setCurrentCell(0, 0)
            print("Initialize first position!")
        else:
            self.position_index = column
            self.row_index = row
        print("Selected", row, column)
        self.setFocus()
        self.goToPosition()

    def save(self):
        if self.xy_initialized:
            np.savetxt(os.path.join(self.folder, "positions.txt"), self.positions_xy, fmt="%d")
        book = xlwt.Workbook()
        sh = book.add_sheet("Data")

        sh.write(0, 4, "Deflection[mym]")
        sh.write(0, 5, "k [N/m]")
        sh.write(0, 6, "Deflection tissue [mym]")
        sh.write(0, 7, "Active Force [myN]")

        for i in range(len(self.positions)):
            sh.write(i + 1, 0, self.getColumnHeaderName(i))
            for j in range(len(self.positions[i])):
                sh.write(i + 1, j + 1, self.positions[i][j])
                if i == 0:
                    sh.write(0, j + 1, ["Bottom [mm]", "Tissue [mm]", "Top [mm]"][j])
            if i == 0:
                sh.write(0, 0, "Position")
        while True:
            try:
                book.save(os.path.join(self.folder, "data.xls"))
            except IOError:
                reply = QtWidgets.QMessageBox.critical(self, 'Error',
                                                       "Can't write on %s. Is it open in Excel?\nDo you want to retry?" % os.path.join(
                                                           self.folder, "data.xls"),
                                                       QtWidgets.QMessageBox.Ok,
                                                       QtWidgets.QMessageBox.Cancel)
                if reply == QtWidgets.QMessageBox.Cancel:
                    return sys.exit()
                continue
            else:
                break

    def toggleCrop(self):
        if self.crop:
            crop = 0
        else:
            value = 256
            crop = 1024 - value
        mmc.setROI(0, crop / 2, 1344, 1024 - crop)
        self.crop = 1 - self.crop

    def goToNext(self):
        # if self.position_index == 3*6-1:
        #    mic.setXOffset(-self.dx * 2)
        #    mic.setYOffset(-self.dy * 5)
        #    self.position_index = -1
        # elif self.position_index % 3 == 2:
        #    mic.setXOffset(-self.dx*2)
        #    mic.setYOffset(self.dy)
        # else:
        #    mic.setXOffset(self.dx)
        self.position_index = (self.position_index + 1) % (3 * 6)
        self.row_index = 0
        self.setWindowTitle('Deflinator K - %d%d' % (self.position_index // 3 + 1, self.position_index % 3 + 1))
        print(self.position_index // 3 + 1, self.position_index % 3 + 1)
        self.updateTable()

    def goToPrevious(self):
        self.position_index = (self.position_index - 1) % (3 * 6)
        self.row_index = 0

        self.setWindowTitle('Deflinator K - %d%d' % (self.position_index // 3 + 1, self.position_index % 3 + 1))
        print(self.position_index // 3 + 1, self.position_index % 3 + 1)
        self.updateTable()

    def getPositionName(self, index=None):
        if index is None:
            index = self.position_index
        return self.row_headers[index]
        return '%d%d' % (index // 3 + 1, index % 3 + 1)

    def showImage(self):
        if self.im.shape[0] != 0:

            max_brightness = np.amax(self.im)
            max_value = (100 * max_brightness / 2 ** 12 - 5.1) / (40 - 5.1) * 255
            if max_value > 255:
                max_value = 255

            if max_value < 0:
                max_value = 0
            factor = max_value / max_brightness
            self.pixmap.setPixmap(QtGui.QPixmap(array2qimage(self.im * factor)))

    def updateview(self):
        if mmc.getRemainingImageCount():
            self.im = mmc.getLastImage().copy()
            self.im_max = np.amax(self.im)
            self.im_hist, self.im_bins = np.histogram(self.im, bins=np.arange(0, 2 ** 12 + 20, 10), normed=True)
            self.showImage()
            self.view.setExtend(self.im.shape[1], self.im.shape[0])

            with open(record_progress_file, "r") as fp:
                progress = fp.read().split("/")
            if len(progress) == 2:
                self.progressbar.setMaximum(int(progress[1]))
                self.progressbar.setValue(int(progress[0]))
                # self.CheckBlocked()
                # functions = [mic.setXOffset, mic.setYOffset, mic.setZOffset]
                # print(self.speed, self.last_command)
                # for index in range(3):
                #    if self.speed[index] and (self.last_command[index] is None or self.last_command[index].state == STATE_Empty):
                #        self.last_command[index] = functions[index](self.speed[index])

    def closeEvent(self, QCloseEvent):
        self.position_index = 0
        self.row_index = 0
        self.goToPosition()
        print("End")


if __name__ == '__main__':
    if sys.platform[:3] == 'win':
        myappid = 'fabrybiophysics.deflinator'  # arbitrary string
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    # start the Qt application
    app = QtWidgets.QApplication(sys.argv)
    window = Window()
    # window.show()
    sys.exit(app.exec_())
