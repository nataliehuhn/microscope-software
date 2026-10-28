import numpy as np
import time
import psutil
import subprocess
import os
import sys
from pathlib import Path

# Keep direct worker launches tied to the same checkout as this file.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from leica_microscope.camera import Camera
from leica_microscope.includes.MemMap import MemMap
from leica_microscope.includes.config import getConfig

base_dir = Path(__file__).resolve().parent
memmap_def_header = base_dir / "includes/camera_header.xml"
memmap_def = base_dir / "includes/camera.xml"
memmap_file = base_dir / "includes/camera.mmap"


def has_handle(fpath):
    """ check if the file is currently open in another process """
    for proc in psutil.process_iter():
        try:
            for item in proc.open_files():
                if fpath == item.path:
                    return True
        except Exception:
            pass

    return False


class MemmapWriter:
    def __init__(self, cam):
        self.mmap = MemMap(memmap_def_header)

        # kill the old process that is connected
        while self.mmap.pid != 0 and psutil.pid_exists(self.mmap.pid) and self.mmap.pid != os.getpid():
            p = psutil.Process(self.mmap.pid)
            p.terminate()
            p.kill()
            time.sleep(0.1)

        # note that we are now the writer of the memmap
        self.mmap.pid = os.getpid()

        # the number of images in the buffer
        self.N = 10

        # store the camera
        self.cam = cam

        # get an image
        im = self.cam.getImage()

        # and store its shape
        shape = im.shape
        if len(shape) == 2:
            shape = (shape[0], shape[1], 1)

        self.mmap.shape[:] = shape
        # add the buffer in the memory map
        self.mmap.add((dict(name="images", type="memmap", shape=(self.N),
                      layout=(
                          dict(name="counter", type="uint64"),
                          dict(name="shape", shape=len(im.shape), type="uint16"),
                          dict(name="data", shape=im.shape, type="uint16"),
                            )
                      ),)
                 )
        # add the camera paramters
        self.mmap.add((
            dict(name="height", type="uint32"),
            dict(name="width", type="uint32"),
            dict(name="exposure", shape=3, type="float32"),
            dict(name="gain", shape=3, type="float32"),
            dict(name="roi", shape=4, type="uint16"),
            dict(name="binning", type="uint8"),
            dict(name="max_value", type="uint64"),
            dict(name="dtype", type="S20"),
            dict(name="pixel_size", type="float"),
           )
        )
        # add a list of commands
        self.mmap.add((dict(name="commands", type="memmap", shape=(self.N),
                           layout=(
                               dict(name="counter", type="uint64"),
                               dict(name="name", type="S20"),
                               dict(name="value", type="S100"),
                               dict(name="written", type="bool"),
                               dict(name="done", type="bool"),
                           )
                           ),
                      ))

        # initialize the images in the buffer
        for image in self.mmap.images:
            image.counter = 0
            image.shape[:] = 0
            image.data[:] = 0

        # initialize the commands in the buffer
        for command in self.mmap.commands:
            command.counter = 0
            command.name = ""
            command.value = ""
            command.written = False
            command.done = False

        # start the counter
        self.counter = 1

        # store the parameters
        self.store_parameters()

        # save the current shape of the memmory map
        # Publish the definition only after it has been written completely.
        pending_def = memmap_def.with_suffix(".xml.tmp")
        self.mmap.saveXML(pending_def)
        os.replace(pending_def, memmap_def)

    def store_parameters(self):
        # store all camera parameters in the memmory map
        self.mmap.width = self.cam.getWidth()
        self.mmap.height = self.cam.getHeight()

        self.mmap.roi[:] = self.cam.roi()
        self.mmap.exposure[:] = [self.cam.exposure(), self.cam.get_exposure_range()[0], self.cam.get_exposure_range()[1]]
        self.mmap.gain[:] = [self.cam.gain(), self.cam.get_gain_range()[0], self.cam.get_gain_range()[1]]
        self.mmap.binning = self.cam.binning()
        self.mmap.max_value = self.cam.getMaxValue()
        self.mmap.dtype = self.cam.getDtype().__name__
        self.mmap.pixel_size = self.cam.getPixelSize()

    def store_image(self, im):
        # store an image in the memmory map
        buffer = self.mmap.images[self.counter % self.N]
        buffer.shape[:] = im.shape
        if len(im.shape) == 2:
            buffer.data[:im.shape[0], :im.shape[1]] = im
        else:
            buffer.data[:im.shape[0], :im.shape[1], :im.shape[2]] = im
        # set and increase the counter
        buffer.counter = self.counter
        self.counter += 1

    def stream(self):
        # start infinite streaming
        #print("start")
        while True:
            #print("streaming")
            # wait until the next image
            im = self.cam.getImage()
            while im is None:
                im = self.cam.getImage()

            # store the image
            self.store_image(im)

            # look for open commands
            for command in self.mmap.commands:
                if command.written == True and command.done == False:
                    # and execute them
                    try:
                        if command.name == b"exposure":
                            self.cam.setExposure(float(command.value))
                        elif command.name == b"gain":
                            self.cam.setGain(float(command.value))
                        elif command.name == b"roi":
                            self.cam.setROI(*[int(i) for i in command.value.split(b" ")])
                        elif command.name == b"binning":
                            self.cam.setBinning(int(command.value))
                        else:
                            print("ERROR unknown command", command.name)
                    except Exception as err:
                        print(err)
                    # Publish the actual camera values before acknowledging.
                    self.store_parameters()
                    command.done = True


class MemmapReader:
    streamer = None
    inactive_timer = None
    startup_timeout = 30.0
    parameter_timeout = 15.0

    def __init__(self):
        self.mmap = MemMap(memmap_def_header)

        # if no process is connected to the camera, start the streamer
        if self.mmap.pid == 0 or not psutil.pid_exists(self.mmap.pid) or not os.path.exists(memmap_def):
            self.start_streamer()

        self.mmap = MemMap(memmap_def)

        self.counter = np.max([im.counter for im in self.mmap.images])

    def start_streamer(self):
        try:
            del self.mmap
        except AttributeError:
            pass
        try:
            os.remove(memmap_file)
        except (FileNotFoundError, PermissionError):
            pass

        # remove the memmap definition
        if os.path.exists(memmap_def):
            os.remove(memmap_def)
        # Use the viewer's interpreter and this checkout, independent of cwd.
        self.streamer = subprocess.Popen(
            [sys.executable, "-u", str(base_dir / "streamer.py")],
            cwd=str(base_dir),
        )
        # A failed worker must not leave the viewer waiting forever.
        deadline = time.monotonic() + self.startup_timeout
        while True:
            exit_code = self.streamer.poll()
            if exit_code is not None:
                raise RuntimeError(
                    "Camera streamer exited with code {}. Check the console "
                    "for the camera error.".format(exit_code)
                )
            if memmap_def.exists():
                break
            if time.monotonic() >= deadline:
                self.streamer.kill()
                self.streamer.wait()
                raise RuntimeError(
                    "Camera did not start within {:g} seconds. Check its "
                    "connection and close other camera applications.".format(
                        self.startup_timeout
                    )
                )
            time.sleep(0.01)
        self.mmap = MemMap(memmap_def)

    def stop(self):
        if self.streamer is not None:
            self.streamer.kill()
        if self.stream_thread is not None:
            self.do_streaming = False
            self.stream_thread.join()

    stream_thread = None
    do_streaming = True

    def setStreamCallback(self, callback):
        from threading import Thread
        self.stream_callback = callback
        self.stream_thread = Thread(target=self.streaming, args=())
        self.stream_thread.start()

    def streaming(self):
        while self.do_streaming:
            im = self.getImage()
            if im is not None:
                self.stream_callback(im)
            time.sleep(0.0001)

    def getImage(self):
        # if no process is connected to the camera, start the streamer
        if not psutil.pid_exists(self.mmap.pid):
            # if there is no inactive timer started yet, start it
            if self.inactive_timer is None:
                self.inactive_timer = time.time()
                return None
            # if the other process has been inactive for less than a second, wait
            if time.time() - self.inactive_timer < 1:
                return None
            # the other process has been inactive for too long, start a new streamer
            self.start_streamer()
        # reset the inactive timer
        self.inactive_timer = None

        counter_list = [im.counter for im in self.mmap.images]

        # if our counter got out of data (e.g. an new streamer was started), reset the counter
        if self.counter > np.min(counter_list):
            self.counter = 0

        # get the newest image
        counter = np.max(counter_list)
        index = np.argmax(counter_list)
        # if it is newer than our last imagte, take it
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
        command.counter = counter+1
        command.written = True
        deadline = time.monotonic() + self.parameter_timeout
        # MemMap returns numpy.bool_, so identity comparison with False fails.
        while not command.done:
            if not psutil.pid_exists(int(self.mmap.pid)):
                raise RuntimeError("Camera process stopped while setting {}".format(name))
            if time.monotonic() >= deadline:
                raise TimeoutError("Camera did not apply {} within {:g} seconds".format(
                    name, self.parameter_timeout
                ))
            time.sleep(0.001)
        return

    def roi(self):
        return self.mmap.roi

    def setROI(self, x, y, w, h):
        self.setParameter("roi", f"{x} {y} {w} {h}")

    def exposure(self) -> float:
        return self.mmap.exposure[0]

    def setExposure(self, exposure: float):
        self.setParameter("exposure", str(exposure))

    def get_exposure_range(self):
        return self.mmap.exposure[1:]

    def gain(self) -> float:
        gain = float(self.mmap.gain[0])
        return gain if np.isfinite(gain) else None

    def setGain(self, gain: float):
        gain = float(gain)
        minimum, maximum = self.get_gain_range()
        if not np.isfinite(gain) or not minimum <= gain <= maximum:
            raise ValueError("Gain must be between {:g} and {:g}".format(minimum, maximum))
        self.setParameter("gain", str(gain))

    def get_gain_range(self):
        return self.mmap.gain[1:]

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

    def getHeight(self) -> int:
        return self.mmap.height

    def getWidth(self) -> int:
        return self.mmap.width


if __name__ == "__main__":
    cam = Camera()
    memmap_writer = MemmapWriter(cam)
    memmap_writer.stream()
