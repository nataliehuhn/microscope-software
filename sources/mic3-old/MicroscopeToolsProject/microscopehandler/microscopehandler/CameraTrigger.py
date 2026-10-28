from __future__ import division
import time
import sys, glob
try:
    import PyDAQmx
except (ImportError, NotImplementedError):
    print("No NiDAQ available")
import serial

class Serial(serial.Serial):

    def __init__(self, *args, **kwargs):
        serial.Serial.__init__(self, *args, **kwargs)

    def write(self, string):
        return serial.Serial.write(self, string.encode())

    def readline(self):
        return serial.Serial.readline(self).decode()

def serial_ports():
    """ Lists serial port names

        :raises EnvironmentError:
            On unsupported or unknown platforms
        :returns:
            A list of the serial ports available on the system
    """
    if sys.platform.startswith('win'):
        ports = ['COM%s' % (i + 1) for i in range(256)]
    elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
        # this excludes your current terminal "/dev/tty"
        ports = glob.glob('/dev/tty[A-Za-z]*')
    elif sys.platform.startswith('darwin'):
        ports = glob.glob('/dev/tty.*')
    else:
        raise EnvironmentError('Unsupported platform')

    result = []
    for port in ports:
        try:
            s = serial.Serial(port)
            s.close()
            result.append(port)
        except (OSError, serial.SerialException):
            pass
    return result

def find_trigger_port():
    ports = serial_ports()
    for port in ports:
        s = Serial(port, timeout=0.1)
        line = s.readline()
        s.write("?\n")
        line = s.readline()
        s.close()
        if line.startswith("trigger"):
            return port
    raise serial.serialutil.SerialException("Port not found!")
    return None

class NiDAQ_Trigger():

    def __init__(self):
        self.DOtaskHandle = None
        self.delta = None
        self.done = PyDAQmx.bool32()
        self.count = 0

        PyDAQmx.DAQmxResetDevice("Dev1")
        self.setFPS(8)

    def __del__(self):
        PyDAQmx.DAQmxClearTask(self.DOtaskHandle)
        PyDAQmx.DAQmxResetDevice("Dev1")

    def setFPS(self, fps):
        self.setDelta(1./fps)

    def setDelta(self, delta):
        # if no change is set, don't do anything
        if delta == self.delta:
            return
        # store the new delta
        self.delta = delta
        # clear old task handle
        if self.DOtaskHandle is not None:
            PyDAQmx.DAQmxClearTask(self.DOtaskHandle)
        # create new task handle
        self.DOtaskHandle = PyDAQmx.TaskHandle()
        # create the task for digital output with pulses
        PyDAQmx.DAQmxCreateTask("DO", PyDAQmx.byref(self.DOtaskHandle))
        PyDAQmx.DAQmxCreateCOPulseChanTime(self.DOtaskHandle, "Dev1/Ctr0", "",
                                           PyDAQmx.DAQmx_Val_Seconds, PyDAQmx.DAQmx_Val_Low,
                                           0, self.delta / 2, self.delta / 2)

    def TriggerOnce(self):
        # Wait for the last trigger to finish
        self.WaitForStop()

        # set the amount of images to take
        PyDAQmx.DAQmxCfgImplicitTiming(self.DOtaskHandle, PyDAQmx.DAQmx_Val_FiniteSamps, 1)
        self.count = 1

        # start the pulses
        PyDAQmx.DAQmxStartTask(self.DOtaskHandle)

        # Wait for the last trigger to finish
        self.WaitForStop()

    def Trigger(self, count=0, delta=None, fps=None):
        # Wait for the last trigger to finish
        self.WaitForStop()
        # set new frame rate
        if delta is not None:
            self.setDelta(delta)
        if fps is not None:
            self.setFPS(fps)

        # set the amount of images to take
        if count == 0:  # 0 means infinite
            PyDAQmx.DAQmxCfgImplicitTiming(self.DOtaskHandle, PyDAQmx.DAQmx_Val_ContSamps, 1)
        else:
            PyDAQmx.DAQmxCfgImplicitTiming(self.DOtaskHandle, PyDAQmx.DAQmx_Val_FiniteSamps, count)
        self.count = count

        # start the pulses
        PyDAQmx.DAQmxStartTask(self.DOtaskHandle)

    def WaitForStop(self):
        # don't wait for an infinite recording
        if self.count == 0:
            self.Stop()
        # wait until the task is done
        PyDAQmx.DAQmxIsTaskDone(self.DOtaskHandle, PyDAQmx.byref(self.done))
        while not self.done:
            time.sleep(0.1)
            PyDAQmx.DAQmxIsTaskDone(self.DOtaskHandle, PyDAQmx.byref(self.done))
        PyDAQmx.DAQmxStopTask(self.DOtaskHandle)

    def Stop(self):
        if self.DOtaskHandle is None:
            return
        PyDAQmx.DAQmxStopTask(self.DOtaskHandle)
        
        
class SerialOpen:
    def __init__(self, port):
        self.port = port

    def __enter__(self):
        while True:
            try:
                self.ser = Serial(self.port, 19200, timeout=0.1)
                return self.ser
            except serial.serialutil.SerialException:
                pass

    def __exit__(self, type, value, traceback):
        self.ser.close()
        
        
class Arduino_Trigger():

    def __init__(self):
        self.port = find_trigger_port()
        self.count = 0
        self.delta = 0

        self.setFPS(8)

    def setFPS(self, fps):
        self.setDelta(1./fps)

    def setDelta(self, delta):
        # if no change is set, don't do anything
        if delta == self.delta:
            return
        # store the new delta
        self.delta = delta        

    def TriggerOnce(self):
        # Wait for the last trigger to finish
        self.WaitForStop()

        with SerialOpen(self.port) as ser:
            ser.write("C+\n")
            ser.readline()

    def Trigger(self, count=0, delta=None, fps=None):
        # Wait for the last trigger to finish
        self.WaitForStop()
        # set new frame rate
        if delta is not None:
            self.setDelta(delta)
        if fps is not None:
            self.setFPS(fps)

        with SerialOpen(self.port) as ser:
            ser.write("C%d\n" % (int(self.delta*1000)))
        

    def WaitForStop(self):
        self.Stop()

    def Stop(self):
        with SerialOpen(self.port) as ser:
            ser.write("C-\n")
            ser.readline()

if __name__ == '__main__':
    from CameraConnection import CameraConnection
    mmc = CameraConnection()
    #mmc.setProperty('Camera', 'TRIGGER SOURCE', 'EXTERNAL')
    mmc.clearROI()
    mmc.startContinuousSequenceAcquisition(1000)
    
    #trig = Arduino_Trigger()
    #trig.TriggerOnce()
    #trig.Trigger(fps=5)
    #time.sleep(10)

    #daq = NiDAQ_Trigger()
    #daq.Trigger(fps=3)
    #daq.TriggerOnce()
    #daq.TriggerOnce()
