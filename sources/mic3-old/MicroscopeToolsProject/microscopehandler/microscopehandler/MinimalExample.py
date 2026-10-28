# -*- coding: utf-8 -*-
import MMCorePy
import sys, os
import numpy as np

mmc = MMCorePy.CMMCore()
mmc.loadDevice('Camera','Lumenera','LuCam')
mmc.initializeAllDevices()

mmc.setCameraDevice('Camera')
print("... connected")

mmc.snapImage()
print("snapped")

img = mmc.getImage()
print("got")
print(np.amax(img))
