# -*- coding: utf-8 -*-
from __future__ import division, print_function
import os
import sys
import numpy as np
import re

#from statsmodels.emplike.elanova import _ANOVAOpt


def format_partial(s, **kwargs):
    patterns = re.findall("({([^:}]*)[^}]*})", s)
    for pattern in patterns:
        field, key = pattern
        if key in kwargs:
            s = s.replace(field, field.format(**kwargs))
        #else:
        #    s = s.replace(field, "~")
    return s

def format_with_default(s, *args, **kwargs):
    patterns = re.findall("({([^:}]*)[^}]*})", s)
    for pattern in patterns:
        field, key = pattern
        if key not in kwargs:
            kwargs[key] = 0
        s = s.replace(field, field.format(**kwargs))
    return s

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

if __name__ == "__main__":
    name = "{bla} asd {blub}"
    print(name)
    print(format_partial(name, bla="hey"))
    print(name)