# -*- coding: utf-8 -*-
from __future__ import division, print_function
import os
import sys
import numpy as np
import re
import time
import shutil
from pathlib import Path


def format_partial(s, **kwargs):
    s = str(s)
    patterns = re.findall("({([^:}]*)[^}]*})", s)
    for pattern in patterns:
        field, key = pattern
        if key in kwargs:
            s = s.replace(field, field.format(**kwargs))
        #else:
        #    s = s.replace(field, "~")
    return Path(s)

def format_with_default(s, *args, **kwargs):
    s = str(s)
    patterns = re.findall("({([^:}]*)[^}]*})", s)
    for pattern in patterns:
        field, key = pattern
        if key not in kwargs:
            kwargs[key] = 0
        s = s.replace(field, field.format(**kwargs))
    return Path(s)

def set_format_zeros(formatstring, key, amount):
    fomat_placeholder = ":" + "0%d" % int(np.ceil(np.log10(amount)) + 1) + "d"
    return formatstring.replace("{"+key+"}", "{"+key+fomat_placeholder+"}")
    
def print_with_border(msg):
    msg = u"║  %s  ║" % msg
    print(u"%s" % (" " * len(msg)*2))
    print(u"╔%s╗" % (u"═"*(len(msg)-2)))
    print(u"║  %s    ║" % (" "*(len(msg)-8)))
    print(msg)
    print(u"║  %s    ║" % (" "*(len(msg)-8)))
    print(u"╚%s╝\n" % (u"═"*(len(msg)-2)))

def print_with_border2(msg):
    msg = "##  %s  ##" % msg
    print("%s" % (" " * len(msg)*2))
    print("%s" % ("#"*len(msg)))
    print("##  %s  ##" % (" "*(len(msg)-8)))
    print(msg)
    print("##  %s  ##" % (" "*(len(msg)-8)))
    print("%s\n" % ("#"*len(msg)))

def print_revert(*args):
    msg = " ".join(str(s) for s in args)
    print(msg, "\r" * len(msg), end="")

def print_indented(indent, *args):
    msg = " ".join(str(s) for s in args)
    print("%s%s%s" % ("  " * indent, msg, " "*60))

def CheckPath(target_folder):
    app = None
    if target_folder is None:
        from qtpy import QtGui, QtWidgets
        app = QtWidgets.QApplication(sys.argv)
        target_folder = str(QtWidgets.QFileDialog.getExistingDirectory(None, "Choose target folder", os.getcwd()))
        if target_folder is "":
            print("ERROR: No path selected")
            sys.exit(1)
        if not os.path.exists(target_folder):
            print("ERROR: path", target_folder, "does not exist.")
            sys.exit(-1)

    if not os.path.exists(target_folder):
        try:
            os.mkdir(target_folder)
        except:
            from qtpy import QtGui, QtWidgets
            if not app:
                app = QtWidgets.QApplication(sys.argv)
            reply = QtWidgets.QMessageBox.question(None, 'Create folder',
                "The folder %s does not exist.\n\nDo you want to create it?" % target_folder, QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.Cancel)
            if reply == QtWidgets.QMessageBox.Cancel:
                print("ERROR: user canceled folder creation")
                sys.exit(1)
            try:
                os.makedirs(target_folder)
            except:
                print("ERROR: can't create folder", target_folder)
                sys.exit(1)

    elif os.listdir(target_folder) != [] and 0:  # deactivated overwrite warning
        from qtpy import QtGui, QtWidgets
        if not app:
           app = QtWidgets.QApplication(sys.argv)
        reply = QtWidgets.QMessageBox.warning(None, 'Overwrite',
            "The folder does already contain files. Files could be overwritten if a new measurement is saved to an existing folder!\n\nDo you want to proceed anyway?", QtGui.QMessageBox.Yes, QtGui.QMessageBox.Cancel)
        if reply == QtWidgets.QMessageBox.Cancel:
            print("ERROR: User canceled writing to folder")
            sys.exit(1)

    return target_folder

try:
    import ConfigParser  # Py2
except ImportError:
    import configparser as ConfigParser # Py3
import json

class ConfigAccessHelper:
    def __init__(self, parent, section, default=None):
        self.parent = parent
        self.section = section
        self.default = default

    def __getattr__(self, key):
        try:
            data = self.parent.get(self.section, key)
        except ConfigParser.NoOptionError:
            if self.default is None:
                raise NameError("No option "+key+" in config file found.")
            try:
                data = self.default.get(self.section, key)
            except ConfigParser.NoOptionError:
                raise NameError("No option "+key+" neither in config file nor in default file found.")
        try:
            if data == "True":
                return True
            elif data == "False":
                return False
            return json.loads(data)
        except ValueError:
            if data == "None":
                return None
            return data

class Config(ConfigParser.ConfigParser):
    def __init__(self, filename=None, default=None, *args, **kwargs):
        try:
            ConfigParser.ConfigParser.__init__(self, *args, **kwargs)
        except:
            kwargs["interpolation"] = None
            ConfigParser.ConfigParser.__init__(self, *args, **kwargs)
        if default:
            if not os.path.exists(default):
                raise IOError("No such file or directory: "+default)
            self.default = ConfigParser.ConfigParser(*args, **kwargs)
            self.default.read(default)
        else:
            self.default = None
        if filename is not None:
            self.read(filename)
            #print("Readed config", self.sections())
            #with open(filename) as fp:
            #    print(fp.read())

    def __getattr__(self, key):
        if key in self.sections():
            return ConfigAccessHelper(self, key, self.default)
        elif self.default and key in self.default.sections():
            return ConfigAccessHelper(self.default, key)
        print(key)#, self.default)
        return ConfigParser.ConfigParser.__getattr__(self, key)

def split_non_excaped(s):
     parts = []
     bracket_level = 0
     current = []
     quote_level = 0
     # trick to remove special-case of trailing chars
     for c in (s + "\a"):
         if (c == "," and bracket_level == 0 and quote_level == 0) or c == "\a":
             parts.append("".join(current).strip())
             current = []
         else:
             if c == "(":
                 bracket_level += 1
             elif c == ")":
                 bracket_level -= 1
             elif quote_level == 0 and (c == "\"" or c == "\'"):
                 quote_level = c
             elif quote_level == c:
                 quote_level = 0
             current.append(c)
     return parts

def getModes(text):
    text = text.strip()
    if text[0] == "[" and text[-1] == "]":
        text = text[1:-1]
    modes = split_non_excaped(text)
    return modes

""" modes """


class Mode:
    mode = None
    name = ""

    def __init__(self, exp=None, gain=0):
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

    def to_dict(self):
        data = {}
        if self.name != "":
            data["mode"] = self.name
        if self.exp is not None:
            data["exposure"] = self.exp
        if self.gain is not None:
            data["gain"] = self.gain
        return data

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

    def __init__(self, exp=None, gain=0):
        self.exp = exp
        self.gain = gain

def modesToDictList(config_modes):
    modes = []
    for mode in getModes(config_modes):
        if mode.startswith("Mode_"):
            mode = eval(mode).to_dict()
        if "mode" in mode:
            mode["mode"] = mode["mode"]
        modes.append(mode)
    return modes

def formatDict(dict, escape=False):
    if escape is True:
        def to_string(v):
            if isinstance(v, str):
                return '"'+v+'"'
            return str(v)
    else:
        to_string = str
    return ", ".join(k+"="+to_string(v) for k, v in dict.items())

def getConfig():
    if len(sys.argv) >= 2:
        config_filename = sys.argv[1]
    else:
        config_filename = os.path.expandvars(r"%APPDATA%\Microscope\Config.txt")

    # overwrite defaults with personal cfg if available
    if os.path.exists(config_filename):
        config = Config(config_filename, os.path.join(os.path.dirname(__file__), "..", "ConfigCreator", "Config_Default.txt"))
    else:
        print("ERROR: no config file found.")
        sys.exit(-1)

    timestamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())

    # Check if path exists
    target_folder = CheckPath(config.files.target_folder)

    # Copy config to path
    target_filename = None
    if os.path.exists(config_filename):
        target_filename = os.path.join(target_folder, timestamp + "_" + os.path.split(config_filename)[1])
        try:
            shutil.copyfile(config_filename, target_filename)
        except shutil.Error:
            pass

    return config, timestamp

indent = -1
class bar:
    def __init__(self, iterable, desc=None):
        self.iterable = iter(iterable)
        self.name = desc
        self.iteration = 0
        try:
            self.len = len(iterable)
        except TypeError:
            self.len = None

    def __iter__(self):
        global indent
        indent += 1
        start_time = time.time()
        while True:
            try:
                value = next(self.iterable)
            except StopIteration:
                indent -= 1
                return None
            percent = self.iteration / self.len
            element_count = 10
            element_count_full = int(np.floor(element_count * percent))
            if indent > 0:
                print("\n"+("   " * indent), end="")
            print(self.name + ":", str(self.iteration+1)+"/"+str(self.len), end=" ")# f"({int(time.time()-start_time)}s)")
            self.iteration += 1
            yield value

if __name__ == "__main__":
    name = "{bla} asd {blub}"
    print(name)
    print(format_partial(name, bla="hey"))
    print(name)
