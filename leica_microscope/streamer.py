import numpy as np
import time
import psutil
import subprocess
import os
from pathlib import Path

from leica_microscope.camera import Camera
from leica_microscope.includes.MemMap import MemMap
from leica_microscope.includes.config import getConfig


class MemmapWriter:
    def __init__(self, cam):
        self.mmap = MemMap("includes/camera_header.xml")

        # kill the old process that is connected
        p = psutil.Process(self.mmap.pid)
        p.terminate()

        # note that we are now the writer of the memmap
        self.mmap.pid = os.getpid()

        self.N = 10

        self.cam = cam
        im = self.cam.getImage()
        print(im.shape)
        shape = im.shape
        if len(shape) == 2:
            shape = (shape[0], shape[1], 1)

        self.mmap.shape = shape
        self.mmap.add(dict(name="images", type="memmap", shape=(self.N),
                      layout=(
                          dict(name="counter", type="uint64"),
                          dict(name="shape", shape=len(im.shape), type="uint16"),
                          dict(name="data", shape=im.shape, type="uint16"),
                            )
                      )
                 )
        self.mmap.add((
            dict(name="exposure", type="float32"),
            dict(name="gain", type="float32"),
            dict(name="roi", shape=4, type="uint16"),
            dict(name="binning", type="uint8"),
            dict(name="max_value", type="uint64"),
            dict(name="dtype", type="S20"),
            dict(name="pixel_size", type="float"),
           )
        )
        self.mmap.add(dict(name="commands", type="memmap", shape=(self.N),
                           layout=(
                               dict(name="counter", type="uint64"),
                               dict(name="name", type="S20"),
                               dict(name="value", type="S100"),
                               dict(name="written", type="bool"),
                               dict(name="done", type="bool"),
                           )
                           )
                      )
        self.mmap.saveXML("includes/camera.xml")

        for i in range(self.N):
            self.mmap.images.counter = 0

        self.counter = 1

        self.store_parameters()

    def store_parameters(self):
        self.mmap.roi = self.cam.getROI()
        self.mmap.exposure = self.cam.getExposure()
        self.mmap.gain = self.cam.getGain()
        self.mmap.binning = self.cam.getBinning()
        self.mmap.max_value = self.cam.getMaxValue()
        self.mmap.dtype = self.cam.getDtype().__name__
        self.mmap.pixel_size = self.cam.getPixelSize()

    def store_image(self, im):
        buffer = self.mmap.images[self.counter % self.N]
        buffer.shape[:] = im.shape
        if len(im.shape) == 2:
            buffer.data[:im.shape[0], :im.shape[1]] = im
        else:
            buffer.data[:im.shape[0], :im.shape[1], :im.shape[2]] = im
        buffer.counter = self.counter
        self.counter += 1

    def stream(self):
        while True:
            im = self.cam.getImage()
            while im is None:
                im = self.cam.getImage()

            self.store_image(im)

            for command in self.mmap.commands:
                if command.written is True and command.done is False:
                    if command.name == "exposure":
                        self.cam.setExposure(float(command.value))
                    if command.name == "gain":
                        self.cam.setGain(float(command.value))
                    if command.name == "roi":
                        self.cam.setROI(*[int(i) for i in command.value.split(" ")])
                    if command.name == "binning":
                        self.cam.setBinning(int(command.value))
                    command.done = True

            self.store_parameters()


class MemmapReader:
    def __init__(self):
        self.mmap = MemMap("includes/camera_header.xml")

        # if no process is connected to the camera, start the streamer
        if not psutil.pid_exists(self.mmap.pid):
            self.start_streamer()

        self.mmap = MemMap("includes/camera.xml")
        self.counter = np.max([im.counter for im in self.mmap.images])

    def start_streamer(self):
        os.remove("includes/camera.mmap")
        self.streamer = subprocess.Popen(["python", "streamer.py"])

    def getImage(self):
        # if no process is connected to the camera, start the streamer
        if not psutil.pid_exists(self.mmap.pid):
            self.start_streamer()

        counter_list = [im.counter for im in self.mmap.images]

        counter = np.max(counter_list)
        index = np.argmax(counter_list)
        if counter > self.counter:
            self.counter = counter
            return self.mmap.images[index].data[tuple(slice(0, s) for s in self.mmap.images[index].shape)]
        return None

    def setParameter(self, name, value):
        index = np.argmin([command.counter for command in self.mmap.commands])
        counter = np.max([command.counter for command in self.mmap.commands])

        command = self.mmap.commands[index]
        command.written = False
        command.name = str(name)
        command.value = str(value)
        command.done = False
        command.written = True
        command.counter = counter+1
        while command.done is False:
            pass
        return

    def roi(self):
        return self.mmap.roi

    def setROI(self, x, y, w, h):
        self.setParameter("roi", f"{x} {y} {w} {h}")

    def exposure(self) -> float:
        return self.mmap.exposure

    def setExposure(self, exposure: float):
        self.setParameter("exposure", str(exposure))

    def gain(self) -> float:
        return self.mmap.gain

    def setGain(self, gain: float):
        self.setParameter("gain", str(gain))

    def binning(self) -> int:
        return self.mmap.binning

    def setBinning(self, binning: int):
        self.setParameter("binning", str(binning))

    def getMaxValue(self) -> int:
        return self.mmap.max_value

    def getDtype(self):
        return np.typeDict[self.mmap.dtype]

    def getPixelSize(self) -> float:
        return self.mmap.pixel_size


if __name__ == "__main__":
    cam = Camera()
    memmap_writer = MemmapWriter(cam)
    memmap_writer.stream()
