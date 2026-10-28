import sys
import os
import re
import shutil

config_file = os.path.join(os.path.dirname(__file__), "..", "microscope_config.txt")
config_file_default = os.path.join(os.path.dirname(__file__), "..", "microscope_config_default.txt")


def getConfig(defaults={}):
    if not os.path.exists(config_file):
        shutil.copy(config_file_default, config_file)

    if os.path.exists(config_file):
        with open(config_file, "r") as fp:
            code = compile(fp.read(), config_file, 'exec')
            exec(code, globals(), defaults)

    defaults["filename"] = config_file

    return defaults


def writeConfigChange(config, name, value):
    with open(config["filename"], "r") as fp:
        text = fp.read()
    if re.search(name+r"\s*=[^\n]*", text) is not None:
        text = re.sub(name+r"\s*=[^\n]*", name + " = " + value, text)
    else:
        text += "\n"+name+" = "+value
    with open(config["filename"], "w") as fp:
        fp.write(text)

