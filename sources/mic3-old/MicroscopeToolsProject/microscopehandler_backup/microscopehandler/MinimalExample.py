# -*- coding: utf-8 -*-
import MMCorePy
import sys, os

def restart():
    args = sys.argv[:]
    print('Re-spawning %s' % ' '.join(args))

    args.insert(0, sys.executable)
    if sys.platform == 'win32':
        args = ['"%s"' % arg for arg in args]

    #os.chdir(_startup_cwd)
    os.execv(sys.executable, args)

def try_init():
    global mmc
    mmc = MMCorePy.CMMCore()
    mmc.loadDevice('Camera','HamamatsuHam','HamamatsuHam_DCAM')
    mmc.initializeAllDevices()

print("Trying to connect ...")
try:
    try_init()
except MMCorePy.CMMError as err:
    restart()

mmc.setCameraDevice('Camera')
print("... connected")

while True:
    try:
        mmc.snapImage()
        print("snapped")

        img = mmc.getImage()
        print("got")
        print(img)
    except MMCorePy.CMMError:
        restart()
