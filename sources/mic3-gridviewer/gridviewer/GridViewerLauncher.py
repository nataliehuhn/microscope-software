import sys
import os
import ctypes

from qtpy import QtCore, QtGui, QtWidgets

from .GridViewerBooster import BoosterRunning
from .GridViewerWindow import GridViewerWindow

def main():
    #try:
    #    BoosterRunning()
    #except ImportError:
    #    pass
    if sys.platform[:3] == 'win':
        myappid = 'fabrybiophysics.gridview'  # arbitrary string
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    app = QtWidgets.QApplication(sys.argv)

    # if no path is supplied ask for one
    if len(sys.argv) > 1:
        srcpath = sys.argv[1]
    else:
        srcpath = QtWidgets.QFileDialog.getOpenFileName(None, "Choose Image", os.getcwd(), "Images (*.tif)")
        if isinstance(srcpath, tuple):
            srcpath = srcpath[0]
        else:
            srcpath = str(srcpath)
        if not os.path.exists(srcpath):
            sys.exit(-1)

    # start window
    window = GridViewerWindow(srcpath)
    window.show()
    app.exec_()

if __name__ == '__main__':
    main()