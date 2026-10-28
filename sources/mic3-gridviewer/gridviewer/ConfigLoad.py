try:
    import ConfigParser  # Python 2
except ImportError:
    import configparser as ConfigParser  # Python 3
import json
import os
import re

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
                raise AttributeError("No option "+key+" in config file found.")
            try:
                data = self.default.get(self.section, key)
            except ConfigParser.NoOptionError:
                raise AttributeError("No option "+key+" neither in config file nor in default file found.")
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
        # remove duplicate dynamic section
        with open(filename, "r") as fp:
            text = fp.read()
        position = [m.start() for m in re.finditer('\[dynamic\]', text)]
        if len(position) > 1:
            text = text[:position[0]] + text[position[-1]:]
            with open(filename, "w") as fp:
                fp.write(text)

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

    def __getattr__(self, key):
        if key in self.sections():
            return ConfigAccessHelper(self, key, self.default)
        elif self.default and key in self.default.sections():
            return ConfigAccessHelper(self.default, key)
        return ConfigParser.ConfigParser.__getattr__(self, key)
