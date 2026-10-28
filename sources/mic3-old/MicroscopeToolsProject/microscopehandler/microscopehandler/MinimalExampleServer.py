# -*- coding: utf-8 -*-
import sys, os
from microscopehandler.CameraClient import Camera
from microscopehandler.MicroscopeClient import microscope

# connect to the microscope and the camera
mic = microscope()
mmc = Camera()
mmc.timeout_value = 5

# get a position and set a camera position
print(mic.getPos())
#mic.setPos([11646582, 9097209, 526])

# snap an image and get it
mmc.snapImage()
im = mmc.getImage()

# save the image
mmc.saveImage("test.tif", im)
print(im)
