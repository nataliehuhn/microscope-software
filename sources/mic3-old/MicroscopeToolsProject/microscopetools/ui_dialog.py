# -*- coding: utf-8 -*-

import qtawesome as qta
from qtpy import QtCore, QtGui, QtWidgets
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from matplotlibwidget import MatplotlibWidget
import numpy as np

class Ui_Dialog(object):
    def setupUi(self, Dialog, mmc):
        Dialog.resize(760, 600)
        self.horizontalLayout = QtWidgets.QHBoxLayout(Dialog)
        self.horizontalLayout.setContentsMargins(0, 0, 0, 0)

        self.Layout_CCD_View = QtWidgets.QVBoxLayout()

        """ First row """
        self.horizontalLayout_2 = QtWidgets.QHBoxLayout()
        layout = self.horizontalLayout_2

        self.button_load = QtWidgets.QPushButton("Load Pos File")
        layout.addWidget(self.button_load)

        self.button_addPos = QtWidgets.QPushButton()
        self.button_addPos.setIcon(qta.icon("fa.plus"))
        self.button_addPos.setMaximumWidth(20)
        layout.addWidget(self.button_addPos)

        self.button_delPos = QtWidgets.QPushButton()
        self.button_delPos.setIcon(qta.icon("fa.minus"))
        self.button_delPos.setMaximumWidth(20)
        layout.addWidget(self.button_delPos)

        self.button_changePos = QtWidgets.QPushButton()
        self.button_changePos.setIcon(qta.icon("fa.star"))
        self.button_changePos.setMaximumWidth(20)
        layout.addWidget(self.button_changePos)

        self.button_leftPos = QtWidgets.QPushButton()
        self.button_leftPos.setIcon(qta.icon("fa.arrow-left"))
        self.button_leftPos.setMaximumWidth(20)
        layout.addWidget(self.button_leftPos)

        self.button_rightPos = QtWidgets.QPushButton()
        self.button_rightPos.setIcon(qta.icon("fa.arrow-right"))
        self.button_rightPos.setMaximumWidth(20)
        layout.addWidget(self.button_rightPos)

        layout.addStretch()

        self.Label_Mode = QtWidgets.QLabel(Dialog)
        layout.addWidget(self.Label_Mode)

        layout.addStretch()
        
        self.label_gain = QtWidgets.QLabel("Gain:")
        layout.addWidget(self.label_gain)
        
        self.spinBox_gain = QtWidgets.QSpinBox(Dialog)
        layout.addWidget(self.spinBox_gain)
        
        self.label = QtWidgets.QLabel("Exposure Time:")
        layout.addWidget(self.label)
        
        self.spinBox_exposureTime = QtWidgets.QSpinBox(Dialog)
        self.spinBox_exposureTime.setSuffix(" ms")
        layout.addWidget(self.spinBox_exposureTime)

        self.button_camera_options = QtWidgets.QPushButton()
        self.button_camera_options.setIcon(qta.icon("fa.gears"))
        layout.addWidget(self.button_camera_options)
        
        self.Layout_CCD_View.addLayout(self.horizontalLayout_2)

        """ Second row """
        self.horizontalLayout_3 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_3.setContentsMargins(0, -1, 10, -1)
        layout = self.horizontalLayout_3

        self.button_save = QtWidgets.QPushButton("Save Pos File")
        layout.addWidget(self.button_save)

        self.Label_Path = QtWidgets.QLabel(Dialog)
        layout.addWidget(self.Label_Path)

        layout.addStretch()
        
        self.label_mode = QtWidgets.QLabel(Dialog)
        layout.addWidget(self.label_mode)
        
        self.Layout_CCD_View.addLayout(self.horizontalLayout_3)

        """ View """
        self.horizontalLayout_View = QtWidgets.QHBoxLayout()
        self.Layout_CCD_View.addLayout(self.horizontalLayout_View)

        """ Matplotlib """

        self.plot = MatplotlibWidget()
        self.plot.figure.patch.set_facecolor([0, 1, 0, 0])
        self.plot.setMinimumHeight(50)
        self.plot.setMaximumHeight(50)
        self.plot_line, = self.plot.figure.gca().plot(np.arange(0, 2**mmc.config["BitDepth"]+20, 20), np.arange(0, 2**mmc.config["BitDepth"]+20, 20))
        ax = self.plot.figure.gca()
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.set_yticks([])
        ax.set_xticks([])
        ax.set_xlim(0, 2 ** 12 + 20)
        self.Layout_CCD_View.addWidget(self.plot)

        """ Bottom row """
        self.horizontalLayout_4 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_4.setContentsMargins(5, -5, 5, 5)
        self.Layout_CCD_View.addLayout(self.horizontalLayout_4)

        self.button_snap = QtWidgets.QPushButton("Snap Image")
        self.horizontalLayout_4.addWidget(self.button_snap)

        self.button_continuous = QtWidgets.QPushButton("Continuous Sequence")
        self.horizontalLayout_4.addWidget(self.button_continuous)

        self.button_save_image = QtWidgets.QPushButton("Save Image")
        self.horizontalLayout_4.addWidget(self.button_save_image)

        self.horizontalLayout_4.addStretch()

        self.button_save_grid = QtWidgets.QPushButton("Record Grid")
        self.horizontalLayout_4.addWidget(self.button_save_grid)

        self.button_save_stack = QtWidgets.QPushButton("Record Stack")
        self.horizontalLayout_4.addWidget(self.button_save_stack)

        self.button_save_video = QtWidgets.QPushButton("Record Video")
        self.horizontalLayout_4.addWidget(self.button_save_video)

        self.button_save_stop = QtWidgets.QPushButton("Stop Recording")
        self.button_save_stop.setVisible(False)
        self.horizontalLayout_4.addWidget(self.button_save_stop)

        self.horizontalLayout.addLayout(self.Layout_CCD_View)
