# -*- coding: utf-8 -*-
from __future__ import division, print_function
print("GridView")
import time
start_t = time.time()
import sys
import os
import ctypes
import imageio
import tifffile
import json
import numpy as np
import re
import datetime
import glob
from natsort import natsorted
from pathlib import Path

from qtpy import QtGui, QtCore, QtWidgets
from qtpy.QtCore import Qt

from qimage2ndarray import array2qimage, rgb_view

try:
    import ConfigParser  # Python 2
except ImportError:
    import configparser as ConfigParser  # Python 3

from gridviewer.includes.QExtendedGraphicsView import QExtendedGraphicsView
#from .ConfigLoad import Config
from gridviewer.HelpText import HelpText

icon_path = os.path.join(os.path.dirname(__file__), "icons")
print("boot time", time.time()-start_t)

try:
    import cv2
    cv_loaded = True
except ImportError:
    print("No OpenCV found. Image stitching won't work")
    cv_loaded = False

def getCrossCorr(frameImg, lastframe, method=None):
    if not cv_loaded:
        return [0, 0]
    if method is None:
        method = cv2.TM_CCORR_NORMED
    res = cv2.matchTemplate(lastframe, frameImg, method)
    return res

def get_meta(file):
    if file is None:
        return {}
    import tifffile
    import json
    from distutils.version import LooseVersion

    if LooseVersion(tifffile.__version__) > LooseVersion("0.13"):
        try:
            with tifffile.TiffFile(file) as tif:
                metadata = tif.shaped_metadata
                if metadata is None:
                    return {}
                return tif.shaped_metadata[0]
        except FileNotFoundError:
            return {}
    else:
        try:
            with tifffile.TiffFile(file) as tif:
                try:
                    tif.shaped_metadata[0]
                except AttributeError:
                    try:
                        metadata = tif[0].image_description
                    except (TypeError, AttributeError):
                        return {}
                try:
                    return json.loads(metadata.decode('utf-8'))
                except (AttributeError, ValueError, KeyError):
                    return {}
        except ValueError:  # invalid tiff file
            return {}

def getDimensions(filename):
    filename = Path(filename)
    regex = re.compile(r"(?P<timestamp>[-0-9]*)_(?P<mic_name>.*)_rep(?P<rep>[-0-9]*)_pos(?P<pos>[-0-9]*)_x(?P<x>[-0-9]*)_y(?P<y>[-0-9]*)_mode(?P<mode>[^_]*)_z(?P<z>[^._]*)\.")

    selected_file_match = regex.match(filename.name).groupdict()
    dimensions = {}
    look_up = {}

    for file in Path(filename).parent.glob("*.tif"):
        match = regex.match(file.name).groupdict()
        if match["timestamp"] == selected_file_match["timestamp"]:
            for key in match:
                if key not in dimensions:
                    dimensions[key] = set()
                dimensions[key].add(match[key])
            look_up[str(match)] = file
        print(file)

    for key in dimensions:
        dimensions[key] = sorted(list(dimensions[key]))
    print(dimensions)
    return dimensions, look_up, selected_file_match


class GridViewerWindow(QtWidgets.QWidget):
    def zoomEvent(self, scale, pos):
        if self.pixtomu:
            mu = 100*self.pixtomu/scale
            values = [1, 5, 10, 25, 50, 75, 100, 150, 200, 250, 500, 1000, 1500, 2000, 2500, 5000, 10000]
            old_v = mu
            for v in values:
                if mu < v:
                    mu = old_v
                    break
                old_v = v
            self.scalebar.setRect(0, 0, -mu/self.pixtomu*scale, 5)
            self.scalebar_text.setPos(-mu/self.pixtomu*scale-20-25, -20-30)
            self.scalebar_text.setTextWidth(mu/self.pixtomu*scale+50)
            self.scalebar_text.setHtml(u"<center>%d&thinsp;µm</center>" % mu)

    def __init__(self, path, parent=None):
        super(QtWidgets.QWidget, self).__init__(parent)
        self.setWindowIcon(QtGui.QIcon(os.path.join(icon_path, "GridViewer.ico")))

        # window layout
        self.layout = QtWidgets.QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.layout)

        # view/scene setup
        self.view = QExtendedGraphicsView()
        self.view.zoomEvent = self.zoomEvent
        self.local_scene = self.view.scene
        self.origin = self.view.origin
        self.layout.addWidget(self.view)

        self.HelpText = HelpText(self.view.hud, __file__)

        self.font = QtGui.QFont()
        self.font.setPointSize(16)

        self.dimensions, self.lookup, self.current_dimensions = getDimensions(path)

        # get image shape
        dirname, path = os.path.split(path)
        if dirname:
            os.chdir(dirname)
        im = imageio.imread(path)
        self.timestamp = ""
        timestamp = re.search("(\d{8}-\d{6})", path)
        if timestamp:
            self.timestamp = timestamp.group()
        self.width = im.shape[1]
        self.height = im.shape[0]

        # get image meta data
        self.metadata = get_meta(path)

        # Try to get scaling
        try:
            self.pixtomu = self.metadata["PixelSize"]/(self.metadata["Magnification"]*self.metadata["Coupler"])
        except KeyError:
            self.pixtomu = None
        if self.pixtomu is not None:
            self.scalebar = QtWidgets.QGraphicsRectItem(0, 0, 1, 1, self.view.hud_lowerRight)
            self.scalebar.setBrush(QtGui.QBrush(QtGui.QColor("white")))
            self.scalebar.setPen(QtGui.QPen(QtGui.QColor("white")))
            self.scalebar.setPos(-20, -20)
            self.scalebar_text = QtWidgets.QGraphicsTextItem("", self.view.hud_lowerRight)
            self.scalebar_text.setFont(self.font)
            self.scalebar_text.setDefaultTextColor(QtGui.QColor("white"))

        # add progessbar
        self.progressbar = QtWidgets.QGraphicsRectItem(0, 0, 0, 1, self.view.hud)
        self.progressbar.setBrush(QtGui.QBrush(QtGui.QColor("red")))
        self.progressbar.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 0)))

        if 1:#self.grid_information is True:
            # Create a template from the path
            path = re.sub("_x[-0-9]*_", "_x{x}_", path)
            path = re.sub("_y[-0-9]*_", "_y{y}_", path)
            path = re.sub("_z[^._]*\.", "_z{z}.", path)
            path = re.sub("_pos[-0-9]*_", "_pos{pos}_", path)
            path = re.sub("_rep[-0-9]*_", "_rep{rep}_", path)
            path = re.sub("_mode[^_]*_", "_mode{mode}_", path)

            # add time display
            try:
                count = len(self.dimensions["rep"])#self.config.repetition.repetition_count
            except AttributeError:
                count = 0
            if count > 1:
                self.time_text = QtWidgets.QGraphicsTextItem("", self.view.hud)
                self.time_text.setFont(self.font)
                self.time_text.setDefaultTextColor(QtGui.QColor("white"))
                self.time_text.setPos(5, 5)
            else:
                self.time_text = None

            # add z display
            try:
                self.stack_count = abs(self.config.stack.slice_start-self.config.stack.slice_stop)
            except AttributeError:
                self.stack_count = 0
            if self.stack_count > 1 and self.config.stack.projection != "True":
                self.z_text = QtWidgets.QGraphicsSimpleTextItem("", self.view.hud_upperRight)
                self.z_text.setFont(self.font)
                self.z_text.setBrush(QtGui.QColor("white"))
                self.z_text.setPos(-300, -5)
                self.z_bar = QtWidgets.QGraphicsRectItem(0, 0, -3, 100, self.view.hud_upperRight)
                self.z_bar.setBrush(QtGui.QBrush(QtGui.QColor("white")))
                self.z_bar.setPen(QtGui.QPen(QtGui.QColor("white")))
                self.z_bar.setPos(-10, 30)
                self.z_tick = QtWidgets.QGraphicsRectItem(0, 0, 10, 1, self.view.hud_upperRight)
                self.z_tick.setBrush(QtGui.QBrush(QtGui.QColor("white")))
                self.z_tick.setPen(QtGui.QPen(QtGui.QColor("white")))
                self.z_tick.setPos(-20, 30)

            # get modes from config
            try:
                self.modes = re.findall(r"Mode_([A-z0-9]*)\(", self.config.general.record_modes)
            except AttributeError:
                self.modes = []
            for i in range(len(self.modes)):
                if self.modes[i] == "Current":
                    self.modes[i] = ""
            try:
                self.mode_index = self.current_dimensions["mode"]#self.modes.index(self.mode)
            except ValueError:
                self.mode_index = 0
        else:
            self.time_text = None

        # create an empty image
        self.empty_im = np.zeros([self.height, self.width, 3], np.uint8)
        self.empty_im[:, :, 0] = 255
        self.empty_im[:, :, 2] = 255

        self.path = path
        try:
            self.path = os.path.split(self.config.dynamic.filename)[1]
            self.path = self.path.replace("{repetition", "{rep")
        except AttributeError:
            pass

        # create pixmaps for the images
        if 1:#self.grid_information is True:
            self.pixmaps = []
            self.positions = []
            self.image_max_index = len(self.dimensions["y"])*len(self.dimensions["x"])#self.config.grid.countx*self.config.grid.county
            self.rotation = 0
            start_x = 0
            start_y = 0
            for y in [i for i in self.dimensions["y"]]:#range(self.config.grid.starty, self.config.grid.starty+self.config.grid.county):
                for x in [i for i in self.dimensions["x"]]:#range(self.config.grid.startx, self.config.grid.startx+self.config.grid.countx):
                    self.positions.append([x, y])
                    self.pixmaps.append(QtWidgets.QGraphicsPixmapItem(QtGui.QPixmap(self.width, self.height), self.origin))
                    self.pixmaps[-1].setOffset(start_x, start_y)
                    self.pixmaps[-1].setTransformOriginPoint(start_x+im.shape[1]*0.5, start_y+im.shape[0]*0.5)
                    start_x += im.shape[1]#*(1-self.config.grid.overlap)
                start_y += im.shape[0]#*(1-self.config.grid.overlap)
                self.view.setExtend(start_x, start_y)
                start_x = 0
            self.images = np.zeros([len(self.pixmaps), self.height, self.width, 3], np.uint16)
            self.xoffsets = np.zeros(len(self.dimensions["x"]))
            self.yoffsets = np.zeros(len(self.dimensions["y"]))
        else:
            self.pixmaps = []
            self.image_max_index = 1
            self.pixmaps.append(QtWidgets.QGraphicsPixmapItem(QtGui.QPixmap(self.width, self.height), self.origin))
            self.view.setExtend(im.shape[1], im.shape[0])
            self.images = np.zeros([len(self.pixmaps), self.height, self.width, 3], np.uint16)
        try:
            r = float(self.config.general.rotation)
            self.setRotation(r)
        except (ValueError, AttributeError):
            pass

        # create the display timer
        self.image_index = 0
        self.current_timer = QtCore.QTimer()
        self.current_timer.timeout.connect(self.ShowImage)

        self.stretch_contrast = False
        self.brightness_min = 0
        self.brightness_max = 2**12

        self.x_offsets = [0, 0]
        self.y_offsets = [0, 0]

        self.DisplayImages()

    def GetTimestampOfImage(self, path):
        try:
            return datetime.datetime.strptime(get_meta(path)["Time"], "%Y%m%d-%H%M%S-%f")
        except (KeyError, ValueError):
            return None

    def DisplayImages(self, noTimer=False):
        if 1:#self.grid_information:
            # update window title
            texts = []
            if self.timestamp is not None:
                texts.append(self.timestamp)
            if self.current_dimensions["rep"] is not None:
                texts.append("Rep " + self.current_dimensions["rep"])
            if self.current_dimensions["pos"] is not None:
                texts.append("Pos " + self.current_dimensions["pos"])
            if self.current_dimensions["z"] is not None:
                texts.append("Z %s" % self.current_dimensions["z"])
            if self.current_dimensions["mode"] is not None:
                texts.append("mode %s" % self.current_dimensions["mode"])
            self.setWindowTitle(" ".join(texts))

            # update time display
            if self.time_text:
                start_time = datetime.datetime.strptime(self.current_dimensions["timestamp"], "%Y%m%d-%H%M%S")
                image_time = self.GetTimestampOfImage(self.lookup[str(self.current_dimensions)])
                if start_time is not None and image_time is not None:
                    time_elapsed = image_time-start_time
                    self.time_text.setPlainText(str(time_elapsed))
                else:
                    self.time_text.setPlainText("")

            # update z display
            if self.stack_count > 1 and self.config.stack.projection != "True":
                try:
                    self.z_text.setText(u"Z %d µm" % (self.config.stack.slice_thickness*(self.z+self.config.stack.slice_start)))
                    self.z_text.setPos(-self.z_text.boundingRect().width() - 5, +5)
                    self.z_tick.setPos(-20, 30 + 100 - self.z / self.stack_count * 100)
                except TypeError:
                    self.z_text.setText(u"%s" % self.z)
                    self.z_text.setPos(-self.z_text.boundingRect().width() - 5, +5)
                    self.z_tick.setPos(-20, 30 + 100 - 50)
        else:
            # update window title
            self.setWindowTitle(self.image_list[self.current_dimensions["rep"]])

        # start display timer
        self.color_channels = 1
        self.image_index = 0
        self.valid_images = 0
        if noTimer:
            self.ShowImage()
            while self.image_index != 0:
                self.ShowImage()
        else:
            self.current_timer.start(1)

    def ShowImage(self):
        # update progress bar
        self.progressbar.setRect(0, 0, self.view.size().width()*self.image_index/(self.image_max_index-2), 5)

        # get path
        if 1:#self.grid_information:
            x, y = self.positions[self.image_index]
            self.current_dimensions["x"] = x
            self.current_dimensions["y"] = y
            try:
                path = self.lookup[str(self.current_dimensions)]
            except KeyError:
                path = None
            #path = self.path.format(x=x, y=y, z=self.z, mode=self.mode, rep=self.current_dimensions["rep"], pos=self.current_dimensions["pos"])
        else:
            path = self.image_list[self.current_dimensions["rep"]]

        # try to read image
        try:
            im = imageio.imread(path)
            if len(im.shape) == 2:
                self.color_channels = 1
                self.images[self.image_index, :, :, :] = im[:, :, None]
            else:
                self.color_channels = 3
                self.images[self.image_index, :, :, :] = im
            if self.stretch_contrast:
                im = (im.astype(int)-self.brightness_min)/(self.brightness_max-self.brightness_min)
                im[im < 0] = 0
                im[im > 1] = 1
                im = (im*255).astype('uint8')
            elif im.dtype == np.uint16:
                im >>= 4
            self.valid_images += 1
        except IOError:
            im = self.empty_im
            self.images[self.image_index, :, :, :] = 0

        # reload meta data
        if self.image_index == 0:
            self.metadata = get_meta(path)
            try:
                self.pixtomu = self.metadata["PixelSize"]/(self.metadata["Magnification"]*self.metadata["Coupler"])
            except KeyError:
                self.pixtomu = None

        # display image
        self.pixmaps[self.image_index].setPixmap(QtGui.QPixmap(array2qimage(im.astype(np.uint8))))

        # check if we already have displayed all images
        self.image_index += 1
        if self.image_index >= self.image_max_index:
            self.image_index = 0
            self.progressbar.setRect(0, 0, 0, 5)
            self.current_timer.stop()

    def fitDisplacement(self):
        if not self.grid_information:
            return
        if not cv_loaded:
            print("ERROR: for fitting the cv2 module is required.")
            return
        xoffsets = np.zeros(self.config.grid.countx)
        yoffsets = np.zeros(self.config.grid.county)

        stageOffsetX = self.width*(1-self.config.grid.overlap)
        stageOffsetY = self.height*(1-self.config.grid.overlap)

        print("Stitching X")
        for x in range(self.config.grid.countx-1):
            offset_range = xrange(-60, 60)
            errors = np.zeros(len(offset_range))
            for index, off in enumerate(offset_range):
                xoffsets[x+1] = off

                start1 = stageOffsetX*x + np.cumsum(xoffsets)[x]
                start2 = stageOffsetX*(x+1) + np.cumsum(xoffsets)[x+1]
                if start1+self.width > start2:
                    overlap_X = start1+self.width-start2
                    for y in range(self.config.grid.county):
                        im1 = (self.images[x+y*self.config.grid.countx, :, -int(overlap_X):] >> 4).astype(np.uint8)
                        im2 = (self.images[x+1+y*self.config.grid.countx, :, :int(overlap_X)] >> 4).astype(np.uint8)
                        errors[index] += getCrossCorr(im1, im2)[0,0]
            xoffsets[x+1] = offset_range[np.argmax(errors)]
            print(xoffsets, np.argmin(errors), offset_range[np.argmax(errors)])

        print("Stitching Y")
        for y in xrange(self.config.grid.county-1):
            offset_range = xrange(-60, 60)
            errors = np.zeros(len(offset_range))
            for index, off in enumerate(offset_range):
                yoffsets[y+1] = off

                start1 = stageOffsetY*y + np.cumsum(yoffsets)[y]
                start2 = stageOffsetY*(y+1) + np.cumsum(yoffsets)[y+1]
                if start1+self.height > start2:
                    overlap_Y = start1+self.height-start2
                    for x in xrange(self.config.grid.countx):
                        im1 = (self.images[x+y*self.config.grid.countx, -int(overlap_Y):, :] >> 4).astype(np.uint8)
                        im2 = (self.images[x+(y+1)*self.config.grid.countx, :int(overlap_Y), :] >> 4).astype(np.uint8)
                        errors[index] += getCrossCorr(im1, im2)[0, 0]#, method=cv2.TM_SQDIFF)
            yoffsets[y+1] = offset_range[np.argmax(errors)]
            print(yoffsets, np.argmin(errors), offset_range[np.argmax(errors)])

        self.xoffsets = xoffsets
        self.yoffsets = yoffsets
        start_x = 0
        start_y = 0
        i = 0
        for y in range(self.config.grid.county):
            for x in range(self.config.grid.countx):
                self.pixmaps[i].setOffset(start_x+xoffsets[x], start_y+yoffsets[y])
                i += 1
                start_x += self.width*(1-self.config.grid.overlap)
            start_y += self.height*(1-self.config.grid.overlap)
            start_x = 0

    def fitDisplacement(self):
        print(self.x_offsets, self.y_offsets)
        start_x = 0
        start_y = 0
        i = 0
        for y in range(self.config.grid.county):
            for x in range(self.config.grid.countx):
                self.pixmaps[i].setOffset(start_x + self.x_offsets[0]*x + self.y_offsets[0]*y, start_y + self.x_offsets[1]*x + self.y_offsets[1]*y)
                i += 1
                start_x += self.width * (1 - self.config.grid.overlap)
            start_y += self.height * (1 - self.config.grid.overlap)
            start_x = 0

    def saveMatrixCopy(self, target, source, offset):
        target_rect = [[int(offset[i]), int(offset[i]+source.shape[i])] for i in range(2)]
        source_rect = [[0, source.shape[i]] for i in range(2)]
        for i in range(2):
            # check if start >= 0
            if target_rect[i][0] < 0:
                source_rect[i][0] += (0 - target_rect[i][0])
                target_rect[i][0] = 0
            if target_rect[i][1] > target.shape[i]:
                source_rect[i][1] -= (target_rect[i][1] - target.shape[i])
                target_rect[i][1] = target.shape[i]
        target[target_rect[0][0]:target_rect[0][1], target_rect[1][0]:target_rect[1][1], :] = source[source_rect[0][0]:source_rect[0][1], source_rect[1][0]:source_rect[1][1], :self.color_channels]

    def saveImage(self):
        if not self.grid_information:
            print("Only saving grids.")
            return
        if self.valid_images == 0:
            print("Nothing to save")
            return
        out_path = re.sub("x{[^}]*}_y{[^}]*}", "grid", self.path).format(z=self.z, mode=self.mode, rep=self.current_dimensions["rep"], pos=self.current_dimensions["pos"])
        dir, filename = os.path.split(out_path)
        out_path = os.path.join(dir, "grid")
        if not os.path.exists(out_path):
            os.mkdir(out_path)
        out_path = os.path.join(out_path, filename)
        max_x = self.width*(1-self.config.grid.overlap)*(self.config.grid.countx-1)+self.width+self.xoffsets[-1]
        max_y = self.height*(1-self.config.grid.overlap)*(self.config.grid.county-1)+self.height+self.yoffsets[-1]
        type = np.uint8
        if os.path.splitext(filename)[1] == ".tif" and not self.stretch_contrast:
            type = np.uint16
        big_image = np.zeros((int(max_y), int(max_x), self.color_channels), type)
        start_x = 0
        start_y = 0
        i = 0
        for y in range(self.config.grid.county):
            for x in range(self.config.grid.countx):
                im = self.images[i]
                if self.stretch_contrast:
                    im = im.copy()
                    from scipy.misc import imrotate
                    im = imrotate(im, self.rotation)
                    im = (im.astype(int)-self.brightness_min)/(self.brightness_max-self.brightness_min)
                    im[im < 0] = 0
                    im[im > 1] = 1
                    im = (im*255).astype('uint8')
                if abs(self.rotation) > 0.001:
                    r = cv2.getRotationMatrix2D((im.shape[1]//2, im.shape[0]//2), -self.rotation, 1.0)
                    im = cv2.warpAffine(im, r, (im.shape[1], im.shape[0]))
                offy = self.yoffsets[y] + self.x_offsets[1]*x + self.y_offsets[1]*y
                offx = self.xoffsets[x] + self.x_offsets[0]*x + self.y_offsets[0]*y
                # copy the im to the big_image
                self.saveMatrixCopy(big_image, im, (start_y+offy, start_x+offx))
                i += 1
                start_x += self.width*(1-self.config.grid.overlap)
            start_y += self.height*(1-self.config.grid.overlap)
            start_x = 0
        metadata = self.metadata.copy()
        if metadata:
            del metadata["shape"]
        metadata["grid_x"] = self.config.grid.countx
        metadata["grid_y"] = self.config.grid.county
        print("Saving...")
        if os.path.splitext(filename)[1] == ".tif":
            tifffile.imsave(out_path, big_image, metadata=metadata)
        else:
            imageio.imsave(out_path, big_image)
        print("Saved image", out_path)

    def saveAllImages(self):
        if 1:  # export only images from every repetition (and not every mode and z)
            for self.current_dimensions["rep"] in range(0, self.config.repetition.repetition_count):
                self.DisplayImages(noTimer=True)
                self.saveImage()
        else:
            for self.current_dimensions["rep"] in range(0, self.config.repetition.repetition_count):
                #self.current_dimensions["rep"] = iRep
                if not isinstance(self.z, int):
                    zrange = self.z_modes
                else:
                    zrange = range(0, self.stack_count)
                for self.z in zrange:
                    #self.z = iz
                    for self.mode in self.modes:
                        #self.mode = m
                        self.DisplayImages(noTimer=True)
                        self.saveImage()

    def setRotation(self, rotation):
        self.rotation = rotation
        print(self.rotation)
        for pixmap in self.pixmaps:
            pixmap.setRotation(self.rotation)

    def changeDimension(self, name, offset):
        index = self.dimensions[name].index(self.current_dimensions[name]) + offset
        self.current_dimensions[name] = self.dimensions[name][index % len(self.dimensions[name])]

    def keyPressEvent(self, event):
        # @key ---- General ----
        if event.key() == QtCore.Qt.Key_F1:
            # @key F1: toggle help window
            self.HelpText.ShowHelpText()

        if event.key() == QtCore.Qt.Key_F:
            # @key F: fit image to view
            self.view.fitInView()

        if event.key() == QtCore.Qt.Key_Escape:
            # @key Escape: close window
            self.close()

        # @key W: full screen toggle
        if event.key() == QtCore.Qt.Key_W:
            if self.isFullScreen():
                self.setWindowState(Qt.WindowMaximized)
            else:
                self.setWindowState(Qt.WindowFullScreen)

        # @key C: stretch contrast
        if event.key() == QtCore.Qt.Key_C:
            self.stretch_contrast = True
            self.brightness_min, self.brightness_max = np.percentile(self.images, [0.1, 99.9]).astype(int)
            self.DisplayImages()

        # @key X: no contrast stretching
        if event.key() == QtCore.Qt.Key_X:
            self.stretch_contrast = False
            self.DisplayImages()

        # @key D: fit displacements
        if event.key() == QtCore.Qt.Key_D:
            self.fitDisplacement()

        # @key S: save image (+ctrl for all images)
        if event.key() == QtCore.Qt.Key_S:
            if event.modifiers() & QtCore.Qt.ControlModifier:
                self.saveAllImages()
            else:
                self.saveImage()

        if event.modifiers() & Qt.ControlModifier:
            if event.key() == QtCore.Qt.Key_Left:
                self.x_offsets[0] -= 1
                self.fitDisplacement()
            elif event.key() == QtCore.Qt.Key_Right:
                self.x_offsets[0] += 1
                self.fitDisplacement()
            elif event.key() == QtCore.Qt.Key_Up:
                self.x_offsets[1] -= 1
                self.fitDisplacement()
            elif event.key() == QtCore.Qt.Key_Down:
                self.x_offsets[1] += 1
                self.fitDisplacement()
        elif event.modifiers() & Qt.ShiftModifier:
            if event.key() == QtCore.Qt.Key_Left:
                self.y_offsets[0] -= 1
                self.fitDisplacement()
            elif event.key() == QtCore.Qt.Key_Right:
                self.y_offsets[0] += 1
                self.fitDisplacement()
            elif event.key() == QtCore.Qt.Key_Up:
                self.y_offsets[1] -= 1
                self.fitDisplacement()
            elif event.key() == QtCore.Qt.Key_Down:
                self.y_offsets[1] += 1
                self.fitDisplacement()
            return

        # @key ---- Navigation (grid display) ----
        if not (event.modifiers() & Qt.ControlModifier):
            """ Repetition """
            if "rep" in self.current_dimensions:
                if event.key() == QtCore.Qt.Key_Left:
                    # @key Left: previous repetition
                    self.changeDimension("rep", -1)
                    self.DisplayImages()

                if event.key() == QtCore.Qt.Key_Right:
                    # @key Right: next repetition
                    self.changeDimension("rep", +1)
                    self.DisplayImages()

            """ Z Position """
            if "z" in self.current_dimensions:
                if event.key() == QtCore.Qt.Key_Down:
                    # @key Down: move z down
                    self.changeDimension("z", -1)
                    self.DisplayImages()

                if event.key() == QtCore.Qt.Key_Up:
                    # @key Up: move z up
                    self.changeDimension("z", +1)
                    self.DisplayImages()

            """ Modes """
            if "mode" in self.current_dimensions:
                if event.key() == QtCore.Qt.Key_PageUp:
                    # @key PageUp: next mode
                    self.changeDimension("mode", -1)
                    self.DisplayImages()

                if event.key() == QtCore.Qt.Key_PageDown:
                    # @key PageDown: previous mode
                    self.changeDimension("mode", +1)
                    self.DisplayImages()

            """ Positions """
            if self.current_dimensions["pos"] is not None:
                if event.key() == QtCore.Qt.Key_End:
                    # @key End: previous position
                    self.changeDimension("pos", -1)
                    self.DisplayImages()

                if event.key() == QtCore.Qt.Key_Home:
                    # @key Home: next mode
                    self.changeDimension("pos", +1)
                    self.DisplayImages()


        # @key I: rotate left
        if event.key() == QtCore.Qt.Key_I:
            self.setRotation(self.rotation + 0.1)

        # @key O: rotate right
        if event.key() == QtCore.Qt.Key_O:
            self.setRotation(self.rotation - 0.1)



