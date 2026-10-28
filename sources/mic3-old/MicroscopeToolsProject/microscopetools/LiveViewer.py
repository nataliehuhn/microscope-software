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

global mmc, mic, exposure_time, gain_values
from microscopehandler.CameraClient import Camera
from microscopehandler.MicroscopeClient import microscope

from ui_dialog import Ui_Dialog

icon_path = os.path.join(os.path.dirname(__file__), ".", "icons")

sensor_size = 6.45

output_path = os.path.join(os.getenv('APPDATA'), "Microscope")
if not os.path.exists(output_path):
    os.mkdir(output_path)
exposure_times_file = os.path.join(output_path, "LiveViewer_ExposureTimes.txt")
gain_values_file = os.path.join(output_path, "LiveViewer_GainValues.txt")
positions_file = os.path.join(output_path, "Positions_tmp.txt")


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

class Window(QtWidgets.QWidget, Ui_Dialog):
    signal = QtCore.Signal()
    window_settings = None

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
   
    def __init__(self, parent = None):
        global mmc, mic, exposure_time, gain_values
        QtWidgets.QWidget.__init__(self, parent)

        print("Conneting to camera server...")
        mmc = Camera()
        mmc.nowait = True
        mmc.no_exceptions = True
        mic = microscope()  # mmc
        print("... connected")

        self.setupUi(self, mmc)
        self.setWindowTitle('LiveViewer')
        self.setWindowIcon(QtGui.QIcon(QtGui.QIcon(os.path.join(icon_path, "LiveViewer.ico"))))

        self.last_folder = ""

        self.view = QExtendedGraphicsView()
        self.local_scene = self.view.scene
        self.origin = self.view.origin
        self.horizontalLayout_View.addWidget(self.view)

        self.pixmap = QtWidgets.QGraphicsPixmapItem(QtGui.QPixmap(1344,1024),self.origin)

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
        self.event_filter = GraphicsItemEventFilter(self.origin, self)
        self.pixmap.installSceneEventFilter(self.event_filter)

        self.blocked = False
        
        self.HelpText = HelpText(self.view.hud, __file__)

        self.help_text = QtWidgets.QGraphicsSimpleTextItem(self.view.hud)
        self.help_text.setFont(QtGui.QFont("", 11))
        self.help_text.setPos(0, 10)
        self.help_text.setBrush(QtGui.QBrush(QtGui.QColor(255, 255, 255)))
                
        if 0:#os.path.exists(exposure_times_file):
            exposure_time = np.loadtxt(exposure_times_file)
        else:
            exposure_time = [5]*180
            
        if 0:#os.path.exists(gain_values_file):
            gain_values = np.loadtxt(gain_values_file)
        else:
            gain_values = [0]*180
        
        self.spinBox_exposureTime.setValue(mmc.memmap.exposure)
        self.spinBox_gain.setValue(mmc.memmap.gain)

        self.ConnectToCamera()        
        
        self.UpdateExposureTime()

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.updateview)
        self.timer.start(100)
        
        self.last_mode = self.GetMode()
        mic.connectEvent(self.Event)
        mmc.event_connect = self.Event
        self.signal.connect(self.MicroscopeUpdate)
        self.Event(0, 0, "")

    def OpenCameraMenu(self):
        if self.window_settings is None:
            self.window_settings = CameraSettings()
        else:
            self.window_settings.close()
        self.window_settings.show()

    def Event(self, device, command, answer):
        self.signal.emit()
        
    def MicroscopeUpdate(self):
        self.updateButtonContinuosText()
        mode = str(mic.memmap.mode)
        if mic.memmap.mode == 0:
            mode = "BF"
        elif mic.memmap.mode == 1:
            mode = "PH"
        elif mic.memmap.mode == 3:
            mode = "DIC"
        elif mic.memmap.mode == 101:
            mode = "Tirf1"
            if mic.memmap.shutter != True:
                print(mic.memmap.shutter)
                mode += "   shutter closed"
        elif mic.memmap.mode == 102:
            mode = "Tirf2"
            if mic.memmap.shutter != True:
                print(mic.memmap.shutter)
                mode += "   shutter closed"
        elif mic.memmap.mode == 10:
            mode = "Flou%d %s" % (mic.memmap.fluo_channel, mic.memmap.fluo_channel_name)
            print(mode)
            if mic.memmap.shutter != True:
                print(mic.memmap.shutter)
                mode += "   shutter closed"
        self.Label_Mode.setText("%dx*%.1f    %s" % (mic.memmap.magnification, mic.config["Coupler"], mode))
        self.CheckBlocked()
        if self.last_mode != self.GetMode() and not self.blocked:
            self.UpdateExposureTime()
            self.UpdateGainValue()
            self.last_mode = self.GetMode()

    def CheckBlocked(self):
        if mmc.getBlockingProcess():
            self.spinBox_exposureTime.setEnabled(False)
            self.spinBox_gain.setEnabled(False)
            for button in [self.button_snap, self.button_continuous, self.button_leftPos, self.button_rightPos]:
                button.setEnabled(False)
            for button in [self.button_save_grid, self.button_save_stack, self.button_save_video]:
                button.setVisible(False)
            self.button_save_stop.setVisible(True)
            self.blocked = True
        else:
            self.spinBox_exposureTime.setEnabled(True)
            self.spinBox_gain.setEnabled(True)
            for button in [self.button_snap, self.button_continuous, self.button_leftPos, self.button_rightPos]:
                button.setEnabled(True)
            for button in [self.button_save_grid, self.button_save_stack, self.button_save_video]:
                button.setVisible(True)
            self.button_save_stop.setVisible(False)
            self.blocked = False

    def ConnectToCamera(self):
        self.help_text.setText("")
        print("... connected")
        mmc.setExposure(exposure_time[0])
        mmc.startContinuousSequenceAcquisition(1)
        self.spinBox_exposureTime.setRange(1,  100000)#mmc.getPropertyLowerLimit('Camera','Exposure'), mmc.getPropertyUpperLimit('Camera','Exposure'))
        self.spinBox_gain.setRange(0, 255)# mmc.getPropertyLowerLimit('Camera','CONTRAST GAIN'),  mmc.getPropertyUpperLimit('Camera','CONTRAST GAIN'))
            
    def GetMode(self):
        if mic.memmap.mode == 10:
            return mic.memmap.mode+mic.memmap.fluo_channel
        return mic.memmap.mode
                
    def ValueChanged(self, event):
        exposure_time[self.GetMode()] = event
        np.savetxt(exposure_times_file, exposure_time, fmt="%d")
        self.UpdateExposureTime()
        
    def ValueChanged2(self, event):
        gain_values[self.GetMode()] = event
        np.savetxt(gain_values_file, gain_values, fmt="%d")
        self.UpdateGainValue()
        
    def UpdateExposureTime(self):
        mode = self.GetMode()
        ext = exposure_time[mode]
        self.spinBox_exposureTime.setValue(ext)
        mmc.setExposure(ext)
        
    def UpdateGainValue(self):
        mode = self.GetMode()
        gain = gain_values[mode]
        self.spinBox_gain.setValue(gain)
        mmc.setGainValue(gain)

    def ButtonSave(self):
        if len(self.positions) == 0:
            detour = QtWidgets.QMessageBox.question(self,
                            "Save empty file?",
                            "No positions have been saved yet. Do you want to save an empty file?",
                            QtWidgets.QMessageBox.Yes|QtWidgets.QMessageBox.No)
            if detour == QtWidgets.QMessageBox.No:
                return False
            elif detour == QtWidgets.QMessageBox.Yes:
                pass
        filename = QtWidgets.QFileDialog.getSaveFileName(self, "Save Positions", "", "Position Files (*.txt)")
        if isinstance(filename, tuple):
            path = str(filename[0])
        else:
            path = str(filename)
        if filename:
            print("Saving:",filename)
            np.savetxt(filename, self.positions, fmt ="%d")  
    
    def ButtonLoad(self):
        fileName = QtWidgets.QFileDialog.getOpenFileName(self, "Open Positions", "", "Position Files (*.txt)")
        if isinstance(fileName, tuple):
            path = str(fileName[0])
        else:
            path = str(fileName)
        if os.path.exists(fileName):
            print("Loading:",fileName)
            positions = np.loadtxt(fileName)
            if len(positions.shape) == 1 and positions.shape[0] == 3:
                positions = positions.reshape(1,3)
            self.positions = positions.tolist()
            self.current_position = 0
            self.UpdateLabel(1)

    def ButtonSnap(self):
        self.im = None
        shutter_opened = False
        print(mic.memmap.mode, mic.memmap.shutter)
        if (mic.memmap.mode == 10 or mic.memmap.mode > 100) and not mic.memmap.shutter:
            shutter_opened = True
            mic.setShutter(True)
            mic.waitTillEvent(shutter=True)
        mmc.snapImage()
        if shutter_opened:
            mic.setShutter(False)
        self.im = mmc.getImage()
        self.showImage()
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

    def ButtonGrid(self):
        filepath = os.path.dirname(__file__)
        parameter = [sys.executable]
        parameter.extend([os.path.join(filepath, "ConfigCreator", "ConfigCreator.py")])
        parameter.extend(["-p", os.path.join(filepath, "Record.py")])
        parameter.extend(["-c", "Record_ConfigGrid"])
        parameter.extend(["-r", os.path.join(filepath, "ConfigCreator", "Record_ConfigGrid_Default.txt")])
        parameter.extend(["-t", os.path.join(filepath, "ConfigCreator", "Record_ConfigGrid_Template.txt")])
        subprocess.Popen(parameter)

    def ButtonStack(self):
        filepath = os.path.dirname(__file__)
        parameter = [sys.executable]
        parameter.extend([os.path.join(filepath, "ConfigCreator", "ConfigCreator.py")])
        parameter.extend(["-p", os.path.join(filepath, "Record.py")])
        parameter.extend(["-c", "Record_ConfigStack"])
        parameter.extend(["-r", os.path.join(filepath, "ConfigCreator", "Record_ConfigStack_Default.txt")])
        parameter.extend(["-t", os.path.join(filepath, "ConfigCreator", "Record_ConfigStack_Template.txt")])
        subprocess.Popen(parameter)

    def ButtonVideo(self):
        filepath = os.path.dirname(__file__)
        parameter = [sys.executable]
        parameter.extend([os.path.join(filepath, "ConfigCreator", "ConfigCreator.py")])
        parameter.extend(["-p", os.path.join(filepath, "Record.py")])
        parameter.extend(["-c", "Record_ConfigVideo"])
        parameter.extend(["-r", os.path.join(filepath, "ConfigCreator", "Record_ConfigVideo_Default.txt")])
        parameter.extend(["-t", os.path.join(filepath, "ConfigCreator", "Record_ConfigVideo_Template.txt")])
        subprocess.Popen(parameter)

    def ButtonStop(self):
        pid = mmc.getBlockingProcess()
        if pid:
            psutil.Process(pid).kill()

    def ButtonSaveImage(self):
        save_filename = r"{datetime}_{system}{pos}_mag{mag}x_mode{mode}_%03d.tif"
        save_filename = format_partial(save_filename, datetime=time.strftime("%Y%m%d-%H%M%S", time.localtime()), system=mic.getMicroscopeName())
        current_pos = mic.getPos()
        posname = ""
        for index, pos in enumerate(self.positions):
            if pos == current_pos:
                posname = "_pos%d" % (index+1)
                break
        save_filename = format_partial(save_filename, pos=posname)
        modeID = mic.memmap.mode
        if modeID == 0:
            mode = "BF"
        elif modeID == 1:
            mode = "PH"
        elif modeID == 3:
            mode = "DIC"
        elif modeID == 10:
            mode = "Fluo"+mic.memmap.fluo_channel_name
        elif modeID == 101:
            mode = "Tirf1"
        elif modeID == 102:
            mode = "Tirf2"
        else:
            mode = modeID
        save_filename = format_partial(save_filename, mode=mode)

        save_filename = format_partial(save_filename, mag=mic.memmap.magnification)

        filename = os.path.join(self.last_folder, save_filename)
        index = 0
        while os.path.exists(filename % index):
            index += 1
        filename = filename % index
        filename = QtWidgets.QFileDialog.getSaveFileName(self, "Save Image", filename, "TIF images (*.tif)")
        if isinstance(filename, tuple):
            path = str(filename[0])
        else:
            path = str(filename)
        if filename:
            self.last_folder = os.path.dirname(filename)
            mmc.saveImage(filename, self.im, microscope=mic)
            print(filename, "saved")

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

    def save_position(self, pos):
        position = mic.getPos()
        if pos == -1:
            self.positions.append( position )
            self.current_position = len(self.positions)-1
        else:
            self.positions[pos] = position
        self.UpdateLabel()

    def del_position(self, pos):
        if pos < len(self.positions):
            self.positions.pop(pos)
        self.UpdateLabel(1)

    def UpdateLabel(self, move=0, change=0):
        if change:
            self.current_position += change
        if self.current_position >= len(self.positions):
            self.current_position = len(self.positions)-1
        if self.current_position < 0:
            self.current_position = 0
        if len(self.positions) == 0:
            self.Label_Path.setText("No Positions")
        else:
            if move:
                mic.setPos(self.positions[self.current_position])
            self.Label_Path.setText("Position %d/%d: %d %d %d" %(self.current_position+1, len(self.positions), self.positions[self.current_position][0], self.positions[self.current_position][1], self.positions[self.current_position][2]))
        np.savetxt(positions_file, self.positions, fmt ="%d")

    def showImage(self):
        if self.im.shape[0] != 0:
            # show the histogram
            hist, bins = np.histogram(self.im, bins=np.arange(0, 2 ** mmc.config["BitDepth"] + 20, 10), normed=True)
            self.plot_line.set_data(bins[:-1], hist)
            self.plot.figure.gca().set_ylim(0, hist.max()*1.05)
            self.plot.draw()

            max_brightness = np.amax(self.im)
            max_value = (100*max_brightness/2**mmc.config["BitDepth"]-5.1)/(40-5.1)*255
            if max_value > 255:
                max_value = 255
            if max_value < 0:
                max_value = 0
            factor = max_value/max_brightness
            self.pixmap.setPixmap(QtGui.QPixmap(array2qimage(self.im*factor)))

            self.label_mode.setText("%.2f fps Illumination: %3.1f%% (%d, %dms, %d)" % (mmc.memmap.fps, 100*np.amax(self.im)/(2**mmc.config["BitDepth"]), np.amax(self.im), mmc.memmap.exposure, mmc.memmap.gain))

    def updateview(self):
        if mmc.getRemainingImageCount():
            self.im = mmc.getLastImage().copy()
            self.showImage()
            self.view.setExtend(self.im.shape[1], self.im.shape[0])
            self.CheckBlocked()

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
        if self.window_settings is not None:
            self.window_settings.close()
        exit

if __name__ == '__main__':
    if sys.platform[:3] == 'win':
        myappid = 'fabrybiophysics.clickpoints' # arbitrary string
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    window = Window()
    window.show()
    splash.finish(window)
    sys.exit(app.exec_())
