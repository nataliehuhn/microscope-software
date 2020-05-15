from leica_microscope.config import getConfig
import importlib


def Camera():
    config = getConfig()
    module = importlib.import_module(f"leica_microscope_{config['camera']}")
    return module.Camera()
