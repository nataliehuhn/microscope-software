# -*- coding: utf-8 -*-
import sys

sys.path.insert(0, r"C:\Software\old\Micro-Manager-1.4")
import MMCorePy

try:
    mmc = MMCorePy.CMMCore()
    mmc.loadDevice('Camera', "HamamatsuHam", "HamamatsuHam_DCAM")
    mmc.initializeAllDevices()
    mmc.setCameraDevice('Camera')
except Exception as err:
    sys.exit(-1)
sys.exit(0)
