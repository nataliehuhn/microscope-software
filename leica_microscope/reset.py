# -*- coding: utf-8 -*-

import os
import psutil
import time
from pathlib import Path
from leica_microscope import Microscope


def KillPythonProcesses():
    import win32api
    pid = win32api.GetCurrentProcessId()
    count = 0
    for process in psutil.process_iter():
        try:
            if process.name().find("python") != -1:
                script_name = os.path.split(process.cmdline()[-1])[1]
                if process.pid != pid:
                    for child in process.children(recursive=True):
                        child.kill()
                    process.kill()
                    count += 1
                    print("Killed pid %d (%s)" % (process.pid, script_name))
        except psutil.AccessDenied:
            pass
    return count

def main():
    KillPythonProcesses()
    time.sleep(0.1)

    print(__file__)
    base_dir = Path(__file__).parent
    memmap_def = base_dir / "includes/camera.xml"
    memmap_file = base_dir / "includes/camera.mmap"

    print(memmap_def, memmap_file)
    try:
        os.remove(memmap_def)
    except WindowsError as err:
        print(err)
    try:
        os.remove(memmap_file)
    except WindowsError as err:
        print(err)
        
    mic = Microscope(no_camera=True, no_init=True)
    #mic.send_command_and_wait("70007")
    mic.send_command_and_wait("71007")
    mic.send_command_and_wait("72007")
    mic.send_command_and_wait("73007")

if __name__ == "__main__":
    main()
