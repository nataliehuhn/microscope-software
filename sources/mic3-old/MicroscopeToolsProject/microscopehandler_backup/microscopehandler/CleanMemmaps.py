# -*- coding: utf-8 -*-
from __future__ import print_function, division

import os
import psutil
import time

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

    output_path = os.path.join(os.getenv('APPDATA'), "Microscope")
    memmap_file1 = os.path.join(output_path, "microscope.dat")
    memmap_file2 = os.path.join(output_path, "camera.dat")
    try:
        os.remove(memmap_file1)
    except WindowsError as err:
        print(err)
    try:
        os.remove(memmap_file2)
    except WindowsError as err:
        print(err)

if __name__ == "__main__":
    main()
