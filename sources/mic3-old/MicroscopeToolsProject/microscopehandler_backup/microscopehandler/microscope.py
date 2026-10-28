from __future__ import division, print_function
import time, serial
import os
import collections
import thread
import traceback
import sys

PortMagnification = 52
FastFilterwheel = 54
MA4Mirror = 56
Docuport = 60
Master = 70
ZDrive = 71
XAxis = 72
YAxis = 73
MicroscopeButtons = 74
MicroscopeDisplay = 75
ObjectiveTurret = 76
Lamp = 77
ILTurret = 78
MagnificationChanger = 79
SwitchablePrisms = 80
FlappingCondenser = 81
CondenserDisk = 82
ApertureDiaphragmTL = 84
DICTurret = 85
ZHandwheel = 86
FieldDiaphragmIL = 94
ApertureDiaphragmIL = 95
ZoomLensTL = 96
CCWheel = 97
Polarizer = 98

class QueryObject:
    def __init__(self, device, command, wait):
        self.device = device
        self.command = command
        self.wait = wait
        self.answered = False
        self.answer = None
        self.err = None
        self.stack = traceback.extract_stack()[:-2]

#class for handling stage. it imports a modul "serial" (=the PySerial-Module)
class microscope:
    class MicroscopeError(Exception):
        pass
        
    def __init__(self):
        self.events = collections.deque(maxlen=100)
        self.queries = collections.deque(maxlen=100)
        
        self.blocked = False
        self.stream = ""
        self.moving = [False, False, False]
        self.moving_event = [False, False, False]
        self.shutter = False
        self.fluo_channel = -1
        self.fluo_channel_name = ""
        self.mode = -1
        
        self.conv_x = -1
        self.conv_y = -1
        self.conv_z = -1
          
        # Get com port from config and connect to it
        config_file = os.path.join(os.path.dirname(__file__),"Microscope_Config.txt")
        if os.path.exists(config_file):
            config = dict(ComPort='com3')
            execfile(config_file, globals(), config)  
        self.ser = serial.Serial(config["ComPort"], 19200, timeout=0.1)
        
        # Try if we have read access to the log file
        with open("serial_log.txt", 'w') as fp:
            pass
        
        # Start listening thread
        thread.start_new_thread(self.listen_thread, ())
        
        # Start recieving commands
        self.sendCommand(XAxis, 03, parameter=[1, 0, 0, 0, 0, 0, 0, 0, 0])  # Event x axis start/stop
        self.sendCommand(YAxis, 03, parameter=[1, 0, 0, 0, 0, 0, 0, 0, 0])  # Event y axis start/stop
        self.sendCommand(ZDrive, 03, parameter=[1, 0, 0, 0, 0, 0, 0, 0, 0])  # Event z axis start/stop
        
        self.sendCommand(Lamp, 03, parameter=[0, 0, 0, 0, 0, 1])  # Event shutter
        self.sendCommand(Master, 03, parameter=[1, 0, 0, 0, 0])  # Event mode
        
        self.sendCommand(ILTurret, 03, parameter=1)  # fluo filter
        
        # Get the current status
        self.mode = self.getMode()
        self.fluo_channel, self.fluo_channel_name = self.getFluoChannel()
        self.conv_x = self.getResolutionX()
        self.conv_y = self.getResolutionY()
        self.conv_z = self.getResolutionZ()
        
    def open(self, port=None):
        # deprecated
        pass
        
    def write(self,x):
        # Write to serial port
        self.ser.write(x)
        # Log communication
        with open("serial_log.txt", 'a') as fp:
            fp.write("Send: %s"%x)
        
    def read(self):
        # Do we have recieved a full command yet?
        if self.stream.find("\r") == -1:
            # then listen
            self.stream += self.ser.readline()
        
        # Do we now have recieved a full command?
        if self.stream.find("\r") != -1:
            # Then split it from the stream
            answer, self.stream = self.stream.split("\r", 1)
            # Log
            with open("serial_log.txt", 'a') as fp:
                fp.write("Recieve: %s\n"%answer)
            # return answer
            return answer
            
        return None

    def listen_thread(self):
        while True:
            time.sleep(0.01)
            answer = self.read()
            if answer is None:
                continue
            if len(answer) == 0:
                continue
            if answer[0] == "$":
                answer = answer[1:]
                event = True
            else:
                event = False
            device = int(answer[:2])
            error = int(answer[2])
            command = int(answer[3:5])
            answer = answer[6:]
            error_msg = self.get_error_msg(device, error, command, answer)
            print("Recieved", "Event:", event, "Device", device, "Error", error, "Command", command, "Answer", answer)
            if not event:
                self.recieved_response(device, command, answer, error_msg)
            else:
                self.recieved_event(device, command, answer)
       
    def get_error_msg(self, device, error, command, answer):
        if error == 0: # No error
            return None
        elif error == 1:
            return "ParErr: Parameter out of range"
        elif error == 2:
            return "SequenceErr:"
        elif error == 3:
            return "FlowErr: Command %d aborted." % command
        elif error == 9:
            if command == 99:
                return "ComErr: Command can't be executed."
            elif command == 98:
                return "IDErr: Unknown id %d." % device
            elif command == 97:
                return "FuiErr:"
            else:
                return "UncErr:"
        else:
            raise Exception("Unknown Error Code", device, error, command)
                        
    def recieved_response(self, device, command, answer, error_msg):
        if command == 22 or command == 24:
            if device == XAxis:
                self.moving[0] = False
            if device == YAxis:
                self.moving[1] = False
            if device == ZDrive:
                self.moving[2] = False
        for query in self.queries:
            if not query.answered and query.device == device and query.command == command:
                query.answer = answer                
                msg = None
                if error_msg:
                    msg = "Traceback (most recent call last):\n"
                    msg += "".join(traceback.format_list(query.stack))
                    msg += error_msg
                if not query.wait:
                    self.queries.remove(query)
                    if msg:
                        traceback._print(sys.stderr, msg)
                else:
                    query.err = msg                    
                    query.answered = True
                return 
            
    def recieved_event(self, device, command, answer):
        answers = answer.split()
        if command == 4:
            if device == XAxis:  # X moving status
                self.moving_event[0] = bool(int(answers[0]))
            if device == YAxis:  # Y moving status
                self.moving_event[1] = bool(int(answers[0]))
            if device == ZDrive:  # Z moving status
                self.moving_event[2] = bool(int(answers[0]))
        if device == Lamp and command == 33:  # shutter status
            self.shutter = bool(int(answers[1]))
        if device == Master and command == 28:  # mode
            self.mode = int(answers[0])
        if device == ILTurret and command == 23:  # fluo channel
            self.fluo_channel = int(answers[0])
            self.fluo_channel_name = answers[1]
            
        self.events.appendleft([device, command, answer])

    """ External functions """        
        
    def waitTillEvent(self, moving=None, shutter=None, mode=None):
        while True:
            if (moving == None or self.moving == [moving, moving, moving]) and \
               (shutter == None or self.shutter == shutter) and \
               (mode == None or self.mode == mode):
                return 0            
            time.sleep(0.010)
        
    def getEvent(self):                
        if len(self.events):
            return self.events.pop()
        return None
        
    def isMoving(self):
        return self.moving
    
    """ Sending Commands """
    
    def sendCommand(self, device, command, parameter=None, formats=None, wait=0):
        print("SendCommand", device, command, parameter, formats)
        # Compose command from device id and command id
        microscope_command = "%02d%03d" % (device, command)
        # Add paremeter if specified
        if parameter is not None:
            if type(parameter) != list:
                parameter = [parameter]
            microscope_command += ' '+' '.join([str(par) for par in parameter])
        # Add query to list
        query = QueryObject(device, command, wait)
        self.queries.append(query)
        # Send to microscope
        self.write(microscope_command+'\r')
        # Return or wait        
        if not wait:
            return
        while not query.answered:
            time.sleep(0.1)
        # Remove query from list
        self.queries.remove(query)
        # Raise error if one occured
        if query.err:
            raise self.MicroscopeError(query.err)
        # Format output if desired
        if formats:
            answers = query.answer.split()
            if type(formats) != list:
                formats = [formats]*len(answers)
            if len(answers) != len(formats):
                raise IndexError("Not enough formats specified for the number of answers")
            answers = [fmt(ans) for ans, fmt in zip(answers, formats)]
            if len(answers) == 1:
                return answers[0]
            return answers
        return query.answer
        
    def sendRequest(self, device, command, formats=float, parameter=None):  
        return self.sendCommand(device, command, parameter=parameter, formats=formats, wait=1)

    """ Set Functions """    
    
    def setPos(self,a, wait=0):
        if a[0] != None:
            self.setX(a[0], wait=wait)
        if a[1] != None:
            self.setY(a[1], wait=wait)
        if a[2] != None:
            self.setZ(a[2], wait=wait)
            
    def setX(self, a, wait=0):
        while self.moving[0]:
            time.sleep(0.01)
        self.moving[0] = True
        self.sendCommand(XAxis, 22, int(a), wait=wait)
        
    def setY(self, a, wait=0):
        while self.moving[1]:
            time.sleep(0.01)
        self.moving[1] = True
        self.sendCommand(YAxis, 22, int(a), wait=wait)
        
    def setZ(self,a, wait=0):
        while self.moving[2]:
            time.sleep(0.01)
        self.moving[2] = True
        self.sendCommand(ZDrive, 22, int(a), wait=wait)        
        
    def setXOffset(self,offset, wait=0):
        while self.moving[0]:
            time.sleep(0.01)
        self.moving[0] = True
        return self.sendCommand(XAxis, 24, offset, wait=wait)

    def setYOffset(self,offset, wait=0):
        while self.moving[1]:
            time.sleep(0.01)
        self.moving[1] = True
        return self.sendCommand(YAxis, 24, offset, wait=wait)
        
    def setZOffset(self,offset, wait=0):
        while self.moving[2]:
            time.sleep(0.01)
        self.moving[2] = True
        return self.sendCommand(ZDrive, 24, offset, wait=wait)
        
    def setRampSpeedX(self,ramp, wait=0):
        return self.sendCommand(XAxis, 30, ramp, wait=wait)
        
    def setRampSpeedY(self,ramp, wait=0):
        return self.sendCommand(YAxis, 30, ramp, wait=wait)
        
    def setRampSpeedZ(self,ramp, wait=0):
        return self.sendCommand(ZDrive, 30, ramp, wait=wait)

    def setXSpeed(self,speed, wait=0):
        return self.sendCommand(XAxis, 32, speed, wait=wait)       
        
    def setYSpeed(self,speed, wait=0):
        return self.sendCommand(YAxis, 32, speed, wait=wait)
        
    def setZSpeed(self,speed, wait=0):
        return self.sendCommand(ZDrive, 32, speed, wait=wait)
        
    def setShutter(self, shutter_open, wait=0):
        if self.shutter == shutter_open:
            return True
        self.shutter = None
        return self.sendCommand(Lamp, 32, [1, int(shutter_open)], wait=wait)
            
    def setFluoMode(self, wait=0):
        return self.setMode(10, wait=wait)

    def setFluoChannel(self, channel, wait=0):
        if self.fluo_channel == channel:
            return True
        self.fluo_channel = -1
        return self.sendCommand(ILTurret, 22, channel, wait=wait)
              
    def setBFMode(self, wait=0):
        return self.setMode(0, wait=wait)

    def setPHMode(self, wait=0):
        return self.setMode(1, wait=wait)		
        
    def setMode(self, mode, wait=0):
        if self.mode == mode:
            return True
        self.mode = -1
        return self.sendCommand(Master, 29, mode, wait=wait)
        
    """ Get Functions """        
        
    def getMode(self):
        return self.sendRequest(Master, 28, formats=int)
      
    def getFluoChannel(self):
        if self.fluo_channel != -1:
            return [self.fluo_channel, self.fluo_channel_name]
        return self.sendRequest(ILTurret, 23, formats=[int, str])
        
    def getMagnification(self):
        return self.sendRequest(ObjectiveTurret, 33, parameter=["a","1"], formats=int)[2]
        
    def getObjectiveIndex(self):
        return self.sendRequest(ObjectiveTurret, 23, formats=int)
        
    def getNumericalAperture(self):
        return self.sendRequest(ObjectiveTurret, 33, parameter=["a","2"], formats=float)[2]
        
    def getObjective(self):
        return self.sendRequest(ObjectiveTurret, 33, parameter=["a","3"], formats=int)[2]
        
    def getPos(self):
        x = self.sendRequest(XAxis, 23, formats=int)
        y = self.sendRequest(YAxis, 23, formats=int)
        z = self.sendRequest(ZDrive, 23, formats=int)
        return [x, y, z]
        
    def getZ(self):
        return self.sendRequest(ZDrive, 23, formats=int)
        
    def getResolutionX(self):
        if self.conv_x != -1:
            return self.conv_x
        return self.sendRequest(XAxis, 34)
        
    def getResolutionY(self):
        if self.conv_y != -1:
            return self.conv_y
        return self.sendRequest(YAxis, 34)
        
    def getResolutionZ(self):
        if self.conv_z != -1:
            return self.conv_z
        return self.sendRequest(ZDrive, 42)
                
    #is z-drive of stage moving?
    def getMovingZ(self):
        return self.sendRequest(ZDrive, 04, formats=int)[0]
        
    def getMovingX(self):
        return self.sendRequest(XAxis, 04, formats=int)[0]
        
    def getMovingY(self):
        return self.sendRequest(YAxis, 04, formats=int)[0]
        
    def getEffectiveMagnification(self):  # TODO implemented in server maybe move here
        return self.getMagnification()
        
if __name__ == '__main__':
    stage = microscope()
    stage.open()
