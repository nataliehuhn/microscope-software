# -*- coding: utf-8 -*-
import MMCorePy
import sys

try:
    mmc = MMCorePy.CMMCore()
    mmc.loadDevice('Camera', sys.argv[1], sys.argv[2])
    mmc.initializeAllDevices()
    mmc.setCameraDevice('Camera')
except Exception as err:
    sys.exit(-1)
sys.exit(0)
