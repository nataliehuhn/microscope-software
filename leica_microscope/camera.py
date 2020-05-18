from leica_microscope.includes.config import getConfig
import importlib


def Camera():
    config = getConfig()
    module = importlib.import_module(f"leica_microscope.camera_{config['camera']}")
    return module.Camera()


a = importlib.import_module(f"leica_microscope.camera_basler")
print(a.Camera())