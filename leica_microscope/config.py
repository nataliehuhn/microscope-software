import sys
import os

PY3 = sys.version_info[0] == 3

config_file = os.path.join(os.path.dirname(__file__), "Microscope_Config.txt")


def getConfig(defaults):
    if os.path.exists(config_file):
        if PY3:
            with open(config_file, "r") as fp:
                code = compile(fp.read(), config_file, 'exec')
                exec(code, globals(), defaults)
        else:
            execfile(config_file, globals(), defaults)

    return defaults
