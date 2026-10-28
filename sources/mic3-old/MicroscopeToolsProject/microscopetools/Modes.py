class Mode:
    mode = None
    name = ""

    def __init__(self, exp=1, gain=0):
        self.exp = exp
        self.gain = gain

    def set_mode(self, mic, mmc):
        mic.setMode(self.mode)
        mmc.setExposure(self.exp)
        mmc.setGainValue(self.gain)

    def pre_measurement(self, mic, mmc):
        #self.wait_for_mode(mic, mmc)
        pass

    def post_measurement(self, mic, mmc):
        pass

    def wait_for_mode(self, mic, mmc):
        pass
        #mic.waitTillEvent(moving=False, mode=self.mode)

class Mode_BF(Mode):
    mode = 0
    name = "BF"

class Mode_PH(Mode):
    mode = 1
    name = "PH"

class Mode_POL(Mode):
    mode = 4
    name = "POL"

class Mode_Fluo(Mode):
    mode = 10
    name = "Fluo"
    channel = 0

    def set_mode(self, mic, mmc):
        mic.setMode(self.mode)
        #print("channel", self.channel)
        mic.setFluoChannel(self.channel)
        mmc.setExposure(self.exp)
        mmc.setGainValue(self.gain)

    def pre_measurement(self, mic, mmc):
        mic.setShutter(True)
        #self.wait_for_mode(mic, mmc)

    def post_measurement(self, mic, mmc):
        mic.setShutter(False)
        #mic.waitTillEvent(moving=None, mode=None, shutter=False)

    def wait_for_mode(self, mic, mmc):
        pass
        #mic.waitTillEvent(moving=False, mode=self.mode, shutter=True)

class Mode_Fluo1(Mode_Fluo):
    name = "Fluo1"
    channel = 1

class Mode_Fluo2(Mode_Fluo):
    name = "Fluo2"
    channel = 2

class Mode_Fluo3(Mode_Fluo):
    name = "Fluo3"
    channel = 3

class Mode_Fluo4(Mode_Fluo):
    name = "Fluo4"
    channel = 4

class Mode_Fluo5(Mode_Fluo):
    name = "Fluo5"
    channel = 5

class Mode_Fluo6(Mode_Fluo):
    name = "Fluo6"
    channel = 6

class Mode_Current(Mode):
    name = ""

    def __init__(self, exp=None, gain=None):
        self.exp = exp
        self.gain = gain

    def set_mode(self, mic, mmc):
        self.mode = mic.getMode()
        if self.exp is not None:
            mmc.setExposure(self.exp)
        if self.gain is not None:
            mmc.setGainValue(self.gain)
        if self.mode == 10:
            self.pre_measurement = Mode_Fluo.pre_measurement
            self.post_measurement = Mode_Fluo.post_measurement
            self.wait_for_mode = Mode_Fluo.wait_for_mode
