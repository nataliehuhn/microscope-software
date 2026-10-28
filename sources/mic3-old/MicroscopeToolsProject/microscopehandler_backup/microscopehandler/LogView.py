#!/usr/bin/python
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import os
import sys

from PyQt4 import QtGui, QtCore

class Console(QtGui.QWidget):
    signal = QtCore.pyqtSignal()

    def __init__(self, file_path, name):
        super(QtGui.QWidget, self).__init__()
        self.setWindowTitle(name)
        self.file_path = file_path
        self.last_position = 0

        self.layout = QtGui.QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.layout)

        font = QtGui.QFont("Miriam Fixed", 12)
        self.text = QtGui.QTextEdit()
        self.text.setReadOnly(True)
        self.layout.addWidget(self.text)
        self.text.setFont(font)
        self.text.setTextColor(QtGui.QColor("white"))
        self.text.setStyleSheet("QTextEdit { background-color: rgb(0, 0, 0); }")
        self.text_string = ""

        self.file_changed()

        self.signal.connect(self.file_changed)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.file_changed)
        self.timer.start(5)

    def add_text(self, text, clear=False):
        if clear:
            self.text_string = ""
        else:
            self.text_string += text
        self.text.setText(self.text_string)
        c = self.text.textCursor()
        c.movePosition(QtGui.QTextCursor.End)
        self.text.setTextCursor(c)

    def file_changed(self):
        if self.last_position > os.path.getsize(self.file_path):
            self.last_position = 0
            self.add_text("", clear=True)

        with open(self.file_path) as fp:
            fp.seek(self.last_position)
            self.add_text(fp.read())
            self.last_position = fp.tell()

class MyHandler(FileSystemEventHandler):
    def __init__(self, file_path):
        FileSystemEventHandler.__init__(self)
        self.file_path = os.path.normpath(file_path)

    def on_modified(self, event):
        if os.path.normpath(event.src_path) == self.file_path:
            self.signal.emit()

if __name__ == "__main__":
    if len(sys.argv) > 2:
        path = sys.argv[1]
        name = sys.argv[2]
    else:
        path = "microscope.log"
        name = ""
    event_handler = MyHandler(path)
    observer = Observer()
    observer.schedule(event_handler, path='.', recursive=False)

    observer.start()

    app = QtGui.QApplication(sys.argv)
    window = Console(path, name)
    event_handler.signal = window.signal
    window.setGeometry(500, 300, 800, 800)
    window.show()
    app.exec_()

    observer.join()
