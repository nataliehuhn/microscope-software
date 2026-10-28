# -*- coding: utf-8 -*-
"""
Created on Thu Jan 28 14:38:56 2016

@author: Micro3
"""

import MicroscopeClient as microscope
import time
import matplotlib.pyplot as plt
import numpy as np

mic = microscope.microscope()
mic.open()

print(mic.sendRequest(72, 33)) # 1200000
mic.sendCommand(72, 32, 10000)
step_to_mu = mic.sendRequest(72, 34)

"""
durations = []
distances = []
for i in xrange(1, 100, 10):
    distance = i*100
    distances.append(distance)
    mic.sendCommand(microscope.XAxis, 22, 234147-distance*0.5, wait=1)
    t = time.time()
    mic.sendCommand(microscope.XAxis, 22, 234147+distance*0.5, wait=1)
    duration = time.time()-t
    durations.append(duration)
    print(i, duration)

np.savetxt("data.txt", np.vstack((durations, distances)))
"""
durations, distances = np.loadtxt("data.txt")
p = np.polyfit(distances*step_to_mu, durations)