from leica_microscope.includes.config import getConfig
import importlib


def Camera():
    config = getConfig()
    module = importlib.import_module(f"leica_microscope.camera_{config['camera']}")
    return module.Camera()
