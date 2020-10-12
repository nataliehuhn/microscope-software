from setuptools import setup

setup(name='leica_microscope',
      version='1.0',
      description='Used to talk to a Leice microscope.',
      url='',
      author='Richard Gerum',
      author_email='richard.gerum@fau.de',
      license='MIT',
      packages=['leica_microscope'],
      install_requires=[
            "winshell",
            "pyserial",
            "tifffile",
            "lucam",
            "configparser",
            "qscintilla",
      ],
      include_package_data=True,
      zip_safe=False)

import sys, os
try:
    import winshell
    winshell_imported = True
except ImportError:
    winshell_imported = False
from pathlib import Path

directory = Path(__file__).absolute().parent / "leica_microscope"
icon_path = Path(__file__).absolute().parent / "leica_microscope" / "icons"

python = sys.executable
pythonw = python.replace("python.exe", "pythonw.exe")
if sys.platform.startswith('win'):
    """ Live Viewer """
    if winshell_imported:
        print("Create desktop shortcut LiveViewer.lnk")
        link_filepath = os.path.join(winshell.desktop(), "LiveViewer.lnk")
        with winshell.shortcut(link_filepath) as link:
          link.path = str(directory / "live_viewer.bat")
          link.working_directory = str(directory)
          link.description = "Live microscope display"
          link.icon_location = (str(icon_path / "LiveViewer.ico"), 0)

    """ Record """
    if winshell_imported:
        print("Create desktop shortcut Record.lnk")
        link_filepath = os.path.join(winshell.desktop(), "Record.lnk")
        with winshell.shortcut(link_filepath) as link:
            link.path = str(directory / "record.bat")
            link.working_directory = str(directory)
            link.description = "Record"
            link.icon_location = (str(icon_path / "Record.ico"), 0)

    """ Record """
    if winshell_imported:
        print("Create desktop shortcut reset.lnk")
        link_filepath = os.path.join(winshell.desktop(), "reset.lnk")
        with winshell.shortcut(link_filepath) as link:
            link.path = str(directory / "reset.bat")
            link.working_directory = str(directory)
            link.description = "Reset the microscope"

    """ Record """
    if winshell_imported:
        print("Create desktop shortcut MicroscopeConsole.lnk")
        link_filepath = os.path.join(winshell.desktop(), "microscope console.lnk")
        with winshell.shortcut(link_filepath) as link:
            link.path = str(directory / "MicroscopeConsole.bat")
            link.working_directory = str(directory)
            link.description = "Reset the microscope"

    """ Record """
    if winshell_imported:
        print("Create desktop shortcut MicroscopeConsole.lnk")
        link_filepath = os.path.join(winshell.desktop(), "microscope config.lnk")
        with winshell.shortcut(link_filepath) as link:
            link.path = str(directory / "microscope_config.txt")
            link.working_directory = str(directory)
            link.description = "Reset the microscope"



else:
    pass