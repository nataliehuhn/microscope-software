from __future__ import division, print_function
import sys, os
from PyQt4 import QtGui, Qsci

config_config = "ConfigLoader_"
do_start = False

class Window(QtGui.QWidget):
    def __init__(self, filename, programm_basename):
        super(QtGui.QWidget, self).__init__()
        self.setWindowTitle(programm_basename+" Config Editor")

        self.layout = QtGui.QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.layout)
                
        self.layout_buttons = QtGui.QHBoxLayout()
        self.layout_buttons.setContentsMargins(5, 5, 5, 0)
        self.layout.addLayout(self.layout_buttons)
        
        self.button_load = QtGui.QPushButton('L&oad', self)
        self.button_load.pressed.connect(self.load)
        self.layout_buttons.addWidget(self.button_load)

        self.button_save = QtGui.QPushButton('Sa&ve as', self)
        self.button_save.pressed.connect(self.saveAs)
        self.layout_buttons.addWidget(self.button_save)         
        
        self.button_cancel = QtGui.QPushButton('C&ancel', self)
        self.button_cancel.pressed.connect(self.close)
        self.layout_buttons.addWidget(self.button_cancel)    
        
        self.layout_buttons.addStretch()
        
        self.button_start = QtGui.QPushButton('S&ave and Start', self)
        self.button_start.pressed.connect(self.SaveNStart)
        self.layout_buttons.addWidget(self.button_start)
        
        self.filename_label = QtGui.QLabel("  "+filename)
        self.layout.addWidget(self.filename_label)        
        
        self.filename = filename
        self.Scintilla = Qsci.QsciScintilla()
        self.Scintilla.setLexer(Qsci.QsciLexerPython(self))
        self.Scintilla.setText(open(os.path.abspath(self.filename)).read())
        self.Scintilla.textChanged.connect(self.text_changed)
        self.changed = False
        
        self.layout.addWidget(self.Scintilla)

    def SaveNStart(self):
        global do_start
        if self.changed == True:
            self.save()
        do_start = True
        self.close()
    
    def saveAs(self):
        self.filename = QtGui.QFileDialog.getSaveFileName(None,"Save Config","")
        self.filename_label.setText("  "+self.filename)
        self.save()

    def load(self):
        self.filename = QtGui.QFileDialog.getOpenFileName(None,"Choose Config","")
        self.filename_label.setText("  "+self.filename)
        self.Scintilla.setText(open(os.path.abspath(self.filename)).read())

    def text_changed(self):
        self.changed = True

    def closeEvent(self, event):
        if self.changed == True:
            reply = QtGui.QMessageBox.question(self, 'Message',
                "File has been changed. Do you want to save?", QtGui.QMessageBox.Yes, QtGui.QMessageBox.No, QtGui.QMessageBox.Cancel)
            if reply == QtGui.QMessageBox.Yes:
                self.save()
            elif reply == QtGui.QMessageBox.Cancel:
                event.ignore()

    def save(self):
        with open(self.filename, 'w') as fp:
            fp.write(self.Scintilla.text().replace("\n",""))
        with open(config_config, 'w') as fp:
            fp.write(self.filename)
            print("Saving")
        print("Config saved...")
        self.changed = False

if __name__ == '__main__':
    app = QtGui.QApplication(sys.argv)
    programm_path, programm_name = os.path.split(sys.argv[1])
    programm_basename, programm_ext = os.path.splitext(programm_name)
    if len(sys.argv) >= 3:
        programm_basename = sys.argv[2]
    default_config = None
    if len(sys.argv) >= 4:
        default_config = sys.argv[3]
    print(programm_basename)
    config_config = config_config+programm_basename+".txt"
    config = ""
    if os.path.exists(config_config):
        with open(config_config) as fp:
            config = fp.readline().strip()
    elif default_config:
        config = default_config
    if config == "" or not os.path.isfile(config):
        config = QtGui.QFileDialog.getOpenFileName(None, "Choose Config", "")
    if not os.path.isfile(config):
        sys.exit(-1)
    print(config)
    window = Window(config, programm_basename)
    window.setGeometry(500, 300, 800, 800)
    window.show()
    app.exec_()
    if do_start:
        os.system(sys.executable + " " + sys.argv[1] + " " + str(config))
