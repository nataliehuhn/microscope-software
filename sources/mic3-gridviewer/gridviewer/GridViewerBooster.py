# -*- coding: utf-8 -*-
from __future__ import division, print_function

import os
import sys
import time
from qtpy import QtCore, QtWidgets

from gridviewer.ConfigLoad import Config
from gridviewer import GridViewerWindow


class Booster(QtWidgets.QWidget):
    new_window = QtCore.Signal(str)

    def __init__(self, parent=None):
        global start_new_time
        super(QtWidgets.QWidget, self).__init__(parent)
        self.new_window.connect(self.OpenNewWindow)

        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        start_new_time = 0
        class MyHandler(FileSystemEventHandler):
            def __init__(self, file_path):
                FileSystemEventHandler.__init__(self)
                self.file_path = os.path.normpath(file_path)
                with open(self.file_path, "w") as fp:
                    fp.write("")
                self.last_position = 0
                self.signal = None

            def on_modified(self, event):
                global start_new_time
                start_new_time = time.time()
                if os.path.normpath(event.src_path) == self.file_path:
                    if self.last_position > os.path.getsize(self.file_path):
                        self.last_position = 0

                    with open(self.file_path) as fp:
                        fp.seek(self.last_position)
                        commands = fp.read()
                        self.last_position = fp.tell()
                        for command in commands.split("\n"):
                            command = command.strip()
                            if command.startswith('"'):
                                command = command[1:-1]
                            if os.path.exists(command):
                                self.signal.emit(command)

        event_handler = MyHandler(os.path.join(os.getenv('APPDATA'), "..", "Local", "Temp", "GridViewer.txt"))
        observer = Observer()
        observer.schedule(event_handler, path=os.path.join(os.getenv('APPDATA'), "..", "Local", "Temp"),
                          recursive=False)
        observer.start()
        event_handler.signal = self.new_window

    def OpenNewWindow(self, command):
        window = GridViewerWindow.GridViewerWindow(command)
        print("GridViewer started", time.time()-start_new_time, "s")
        try:
            from win32gui import SetWindowPos
            import win32con

            SetWindowPos(window.winId(),
                         win32con.HWND_TOPMOST,  # = always on top. only reliable way to bring it to the front on windows
                         0, 0, 0, 0,
                         win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW)
            SetWindowPos(window.winId(),
                         win32con.HWND_NOTOPMOST,  # disable the always on top, but leave window at its top position
                         0, 0, 0, 0,
                         win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW)
        except ImportError:
            pass
        window.raise_()
        window.show()
        window.activateWindow()


def BoosterRunning():
    import win32api
    import psutil
    pid = win32api.GetCurrentProcessId()
    python_filename = os.path.basename(__file__)
    python_filename = python_filename.replace(".pyc", ".py")
    for process in psutil.process_iter():
        try:
            process_name = process.name()
        except psutil.AccessDenied:
            continue
        if process_name == "python.exe":
            for command in process.cmdline():
                script_name = os.path.split(command)[1]
                if script_name == python_filename and process.pid != pid:
                    sys.exit(-1)
        if process_name == "gridviewerbooster.exe":
            sys.exit(-1)
    return 0

def main():
    #BoosterRunning()

    app = QtWidgets.QApplication(sys.argv)

    # start window
    window = Booster()

    while True:
        app.exec_()

if __name__ == '__main__':
    main()
