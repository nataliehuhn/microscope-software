from __future__ import division, print_function
import os
import sys

from qtpy import QtGui, QtCore, QtWidgets
sys.path.insert(0, os.path.dirname(__file__))
from FlowLayout import FlowLayout
try:
    from PyQt5 import Qsci
    qsci_loaded = True
except ImportError:
    try:
        from PyQt4 import Qsci
        qsci_loaded = True
    except ImportError:
        qsci_loaded = False

try:
    import ConfigParser  # Py2
except ImportError:
    import configparser as ConfigParser  # Py3
import json

""" some magic to prevent PyQt5 from swallowing exceptions """
# Back up the reference to the exceptionhook
sys._excepthook = sys.excepthook
# Set the exception hook to our wrapping function
sys.excepthook = lambda *args: sys._excepthook(*args)

icon_path = os.path.join(os.path.dirname(__file__), "..", "icons")
output_path = os.path.join(os.getenv('APPDATA'), "Microscope")
if not os.path.exists(output_path):
    os.mkdir(output_path)
tmp_config = os.path.join(output_path, "config.tmp")

def split_non_excaped(s):
    parts = []
    bracket_level = 0
    current = []
    quote_level = 0
    # trick to remove special-case of trailing chars
    for c in (s + "\a"):
        if (c == "," and bracket_level == 0 and quote_level == 0) or c == "\a":
            parts.append("".join(current).strip())
            current = []
        else:
            if c == "(":
                bracket_level += 1
            elif c == ")":
                bracket_level -= 1
            elif quote_level == 0 and (c == "\"" or c == "\'"):
                quote_level = c
            elif quote_level == c:
                quote_level = 0
            current.append(c)
    return parts


class ConfigAccessHelper:
    def __init__(self, parent, section):
        self.parent = parent
        self.section = section

    def __getattr__(self, key):
        try:
            data = self.parent.get(self.section, key)
        except ConfigParser.NoOptionError:
            return ""
        try:
            return json.loads(data)
        except ValueError:
            return data


class Config(ConfigParser.ConfigParser):
    def __init__(self, filename=None, *args, **kwargs):
        ConfigParser.ConfigParser.__init__(self, *args, **kwargs)
        if filename is not None:
            self.read(filename)

    def __getattr__(self, key):
        if key in self.sections():
            return ConfigAccessHelper(self, key)
        return ConfigParser.ConfigParser.__getattr__(self, key)


class ModeDialog(QtWidgets.QDialog):
    def __init__(self, parent):
        QtWidgets.QDialog.__init__(self)
        self.setWindowTitle("Mode")
        self.parent = parent
        self.layout = QtWidgets.QGridLayout(self)

        self.layout.addWidget(QtWidgets.QLabel("Mode"), 0, 0)
        self.mode = QtWidgets.QComboBox()
        for mode in ["BF", "POL", "PH", "Fluo1", "Fluo2", "Fluo3", "Fluo4", "Fluo5", "Fluo6", "Current"]:
            self.mode.addItem(mode)
        self.layout.addWidget(self.mode, 0, 1)

        self.layout.addWidget(QtWidgets.QLabel("Exposure Time (ms)"), 1, 0)
        self.exposure_time = QtWidgets.QSpinBox()
        self.exposure_time.setRange(1, 1e3)
        self.layout.addWidget(self.exposure_time, 1, 1)

        self.layout.addWidget(QtWidgets.QLabel("Gain Value (0-255)"), 2, 0)
        self.gain_value = QtWidgets.QSpinBox()
        self.gain_value.setRange(0, 255)
        self.layout.addWidget(self.gain_value, 2, 1)

        self.button = QtWidgets.QPushButton("ok")
        self.button.clicked.connect(self.ok)
        self.button.setShortcut("Return")
        self.layout.addWidget(self.button, 10, 0, 1, 2)

    def ok(self):
        mode = self.mode.itemText(self.mode.currentIndex())
        exp = self.exposure_time.value()
        gain = self.gain_value.value()
        if gain:
            text = "%s(%d, %d)" % (mode, exp, gain)
        else:
            text = "%s(%d)" % (mode, exp)
        self.parent.add_mode(text)
        self.close()


class ModeSelector(QtWidgets.QWidget):
    textChanged = QtCore.Signal(str)

    def __init__(self, text=""):
        QtWidgets.QWidget.__init__(self)
        self.setContentsMargins(0, 0, 0, 0)
        self.layout = QtWidgets.QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout2 = FlowLayout()#QtGui.QHBoxLayout(self)
        self.layout.addLayout(self.layout2)
        self.add_button = QtWidgets.QPushButton("")
        self.add_button.setIcon(QtGui.QIcon(os.path.join(icon_path, "Add.png")))
        self.add_button.clicked.connect(self.add)
        self.add_button.setMaximumWidth(25)
        self.add_button.setToolTip("Add a mode")
        self.layout.addWidget(self.add_button)
        self.tags = []
        self.tag_buttons = []
        self.setText(text)

    def add(self):
        dialog = ModeDialog(self)
        dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        dialog.exec_()

    def add_mode(self, text, no_signal=False):
        self.tags.append(text)
        button = QtWidgets.QPushButton(text+"          ")
        style_sheet = "QPushButton { border-width: 0px; background-image: url('"+os.path.join(icon_path, "delete2.png").replace("\\", "/")+"'); border-style: outset; background-repeat:no-repeat; background-position:right top; }"
        button.setStyleSheet(style_sheet)
        button.setToolTip("Remove this mode")
        button.clicked.connect(lambda clicked, text=text: self.remove(button))
        self.layout2.addWidget(button)
        self.tag_buttons.append(button)
        if not no_signal:
            self.textChanged.emit(self.text())
        return button

    def remove(self, button, no_signal=False):
        index = self.tag_buttons.index(button)
        self.layout2.removeWidget(button)
        button.deleteLater()
        self.tag_buttons.pop(index)
        self.tags.pop(index)
        if not no_signal:
            self.textChanged.emit(self.text())

    def setText(self, text):
        text = text.strip()
        if text[0] == "[" and text[-1] == "]":
            text = text[1:-1]
        modes = split_non_excaped(text)
        for button in self.tag_buttons[::-1]:
            self.remove(button, no_signal=1)
        for mode in modes:
            if mode.startswith("Mode_"):
                valid = True
                mode = mode[5:]
            else:
                valid = False
            if valid is not False:
                valid = self.CheckIfModeIsValid(mode[:])
            button = self.add_mode(mode, no_signal=1)
            if not valid:
                style_sheet = "QPushButton { color: #A00; border-width: 0px; background-image: url("+os.path.join(icon_path, "delete2.png").replace("\\", "/")+"); border-style: outset; background-repeat:no-repeat; background-position:right top; }"
                button.setStyleSheet(style_sheet)
        self.textChanged.emit(self.text())

    def CheckIfModeIsValid(self, mode):
        for possible_mod in ["BF", "POL", "PH", "Fluo1", "Fluo2", "Fluo3", "Fluo4", "Fluo5", "Fluo6", "Current"]:
            if mode.startswith(possible_mod):
                mode_comments = mode[len(possible_mod):]
                if mode_comments != "" and mode_comments[0] == "(" and mode_comments[-1] == ")":
                    mode_comments = mode_comments[1:-1]
                    if mode_comments == "":
                        return True
                    else:
                        values = split_non_excaped(mode_comments)
                        if len(values) <= 2:
                            try:
                                [int(v) for v in values]
                                return True
                            except:
                                pass
                return False
        return False

    def text(self):
        return "[Mode_"+", Mode_".join(self.tags)+"]"


class PathSelector(QtWidgets.QWidget):
    def __init__(self, path="", folder=False):
        QtWidgets.QWidget.__init__(self)
        self.setContentsMargins(0,0,0,0)
        self.layout = QtWidgets.QHBoxLayout(self)
        self.layout.setContentsMargins(0,0,0,0)

        self.edit = QtWidgets.QLineEdit(path)
        self.edit.setDisabled(True)

        self.layout.addWidget(self.edit)

        self.load_button = QtWidgets.QPushButton("open")
        self.load_button.clicked.connect(self.load)
        self.layout.addWidget(self.load_button)

        self.folder = folder
        self.textChanged = self.edit.textChanged
        self.text = self.edit.text
        self.setText = self.edit.setText

    def load(self):
        value = self.edit.text()
        if self.folder:
            path = QtWidgets.QFileDialog.getExistingDirectory(self, "Open Folder", value)
        else:
            path = QtWidgets.QFileDialog.getOpenFileName(self, "Open File", value)
        if isinstance(path, tuple):
            path = path[0]
        print(path)
        if path:
            self.setText(path)


def getMeta(text):
    text = str(text)
    try:
        value, meta = text.split("#")
    except ValueError:
        value = text
        meta = {}
    else:
        metalist = split_non_excaped(meta)
        meta = {}
        try:
            for pair in metalist:
                p_key, p_value = pair.split(":", 1)
                p_value = p_value.strip()
                if p_value[0] == "\"" and p_value[-1] == "\"":
                    p_value = p_value[1:-1]
                p_value = p_value.replace("\\n", "\n")
                meta[p_key.strip()] = p_value.strip()
        except ValueError:
            meta = {}
    value = value.strip()
    try:
        value = json.loads(value)
    except ValueError:
        pass
    if value == "True":
        value = True
    if value == "False":
        value = False
    if "type" not in meta:
        if isinstance(value, bool):
            meta["type"] = "bool"
        elif isinstance(value, int):
            meta["type"] = "int"
        elif isinstance(value, float):
            meta["type"] = "float"
        else:
            meta["type"] = "str"
    return value, meta


class ConfigEditor(QtWidgets.QWidget):
    def __init__(self, options):
        QtWidgets.QWidget.__init__(self)

        # widget layout and elements
        self.options = options
        self.setWindowTitle("Config")
        if options.icon:
            self.setWindowIcon(QtGui.QIcon(options.icon))
        layout_vert = QtWidgets.QVBoxLayout(self)
        layout_hor = QtWidgets.QHBoxLayout()
        layout_vert.addLayout(layout_hor)

        self.button_cancel = QtWidgets.QPushButton("Cancel")
        self.button_cancel.clicked.connect(lambda x: self.close())
        layout_hor.addWidget(self.button_cancel)

        self.button_reset = QtWidgets.QPushButton("Reset")
        self.button_reset.clicked.connect(lambda x: self.LoadConfig(self.options.reset))
        layout_hor.addWidget(self.button_reset)

        self.button_load = QtWidgets.QPushButton("Load")
        self.button_load.clicked.connect(self.ButtonLoad)
        layout_hor.addWidget(self.button_load)

        self.button_save = QtWidgets.QPushButton("Save")
        if options.program:
            self.button_save.setText("Save and Start")
        self.button_save.clicked.connect(self.ButtonSave)
        layout_hor.addWidget(self.button_save)

        layout_content = QtWidgets.QHBoxLayout()
        layout_vert.addLayout(layout_content)

        layout_gui = QtWidgets.QVBoxLayout()
        layout_content.addLayout(layout_gui)

        layout_vert = layout_gui
        self.config_default = Config(options.template)
        self.fields = {}
        self.meta = {}
        for section in self.config_default.sections():
            box = QtWidgets.QGroupBox(section)
            box.setFlat(True)
            box_layout = QtWidgets.QGridLayout()
            items = self.config_default.items(section)
            box.setMinimumHeight(len(items)*25+30+10)
            self.fields[section] = {}
            self.meta[section] = {}

            for index, item in enumerate(items):
                if item[0].startswith("@"):
                    continue
                name, value = item
                value, meta = getMeta(value)
                self.meta[section][name] = meta
                label = QtWidgets.QLabel(name)
                box_layout.addWidget(label, index, 0)
                if meta["type"] == "int":
                    edit_field = QtWidgets.QSpinBox()
                    edit_field.setRange(-1e4, 1e4)
                    edit_field.setValue(value)
                    edit_field.valueChanged.connect(lambda value, section=section, name=name: self.changed(section, name, value))
                    if "min" in meta:
                        edit_field.setMinimum(int(meta["min"]))
                    if "max" in meta:
                        edit_field.setMaximum(int(meta["max"]))
                    if "unit" in meta:
                        edit_field.setSuffix(" "+meta["unit"])
                    if "unit_plus" in meta and value >= 0:
                        edit_field.setSuffix(" "+meta["unit_plus"])
                    if "unit_minus" in meta and value < 0:
                        edit_field.setSuffix(" "+meta["unit_minus"])
                elif meta["type"] == "float":
                    edit_field = QtWidgets.QDoubleSpinBox()
                    edit_field.setRange(-1e4, 1e4)
                    edit_field.setValue(value)
                    edit_field.valueChanged.connect(lambda value, section=section, name=name: self.changed(section, name, value))
                    if "min" in meta:
                        edit_field.setMinimum(float(meta["min"]))
                    if "unit" in meta:
                        edit_field.setSuffix(" "+meta["unit"])
                elif meta["type"] == "bool":
                    value = value == "True"
                    edit_field = QtWidgets.QCheckBox()
                    edit_field.setChecked(value)
                    edit_field.stateChanged.connect(lambda value, section=section, name=name: self.changed(section, name, "True" if value else "False"))
                elif meta["type"] == "file" or meta["type"] == "folder":
                    edit_field = PathSelector(value, meta["type"] == "folder")
                    edit_field.textChanged.connect(lambda value, section=section, name=name: self.changed(section, name, value))
                elif meta["type"] == "mode":
                    edit_field = ModeSelector(value)
                    edit_field.textChanged.connect(lambda value, section=section, name=name: self.changed(section, name, value))
                else:
                    edit_field = QtWidgets.QLineEdit(value)
                    edit_field.textChanged.connect(lambda value, section=section, name=name: self.changed(section, name, value))
                if "desc" in meta:
                    edit_field.setToolTip(meta["desc"])
                edit_field.setMinimumHeight(20)
                self.fields[section][name] = edit_field
                box_layout.addWidget(edit_field, index, 1)
                reset_button = QtWidgets.QPushButton()
                reset_button.setIcon(QtGui.QIcon(os.path.join(icon_path, "undo.png")))
                reset_button.setMaximumWidth(20)
                reset_button.setToolTip("Revert to default value")
                reset_button.clicked.connect(lambda clicked, section=section, name=name: self.reset(section, name))
                box_layout.addWidget(reset_button, index, 3)
            box.setLayout(box_layout)
            layout_vert.addWidget(box)

            try:
                tooltip = self.config_default.get(section, "@desc")
            except ConfigParser.NoOptionError:
                tooltip = None
            if tooltip:
                button2 = QtWidgets.QLabel("", box)
                button2.setMinimumSize(20, 20)
                button2.setStyleSheet("QLabel { border-width: 0px; background-image: url("+os.path.join(icon_path, "Help2.png").replace("\\", "/")+"); border-style: outset; background-repeat:no-repeat; background-position:top right; }")
                box.resizeEvent = lambda event, button2=button2, box=box: button2.move(box.width()-button2.width(), 0)
                button2.setToolTip(tooltip)

        if qsci_loaded:
            self.Scintilla = Qsci.QsciScintilla()
            self.Scintilla.setLexer(Qsci.QsciLexerPython(self))
        else:
            self.Scintilla = QtWidgets.QTextEdit()
            self.Scintilla.text = self.Scintilla.toPlainText
        self.Scintilla.setMinimumWidth(400)

        self.no_update = False
        self.Scintilla.textChanged.connect(self.EditorTextChanged)
        layout_content.addWidget(self.Scintilla)

        self.config = Config()
        print("Load config")
        if os.path.exists(options.config):
            self.LoadConfig(options.config)
        else:
            self.LoadConfig(options.reset)
        self.move(0, 0)
        
        # center window in desktop
        DRect = QtWidgets.QDesktopWidget().screenGeometry()
        WRect = self.geometry()
        self.move((DRect.width()-WRect.width())/2, (DRect.height()-WRect.height())/4)

    def LoadConfig(self, path, editor_update=True):
        in_group = False
        with open("temp_config.txt", "w") as fp2:
            with open(path, "r") as fp:
                for line in fp:
                    if line.startswith("["):
                        if not line.startswith("[dynamic]"):
                            in_group = True
                        else:
                            in_group = False
                    if in_group is True:
                        fp2.write(line)

        self.no_update = True
        try:
            if editor_update:
                self.Scintilla.setText(open("temp_config.txt").read())
            self.config = ConfigParser.RawConfigParser()
            self.config.read("temp_config.txt")
            for section in self.fields:
                if not section in self.config.sections():
                    self.config.add_section(section)
                for key in self.fields[section]:
                    try:
                        value, meta = getMeta(self.config.get(section, key))
                    except ConfigParser.NoOptionError:
                        value, meta = getMeta(self.config_default.get(section, key))
                        self.config.set(section, key, value)
                    field = self.fields[section][key]
                    meta = self.meta[section][key]
                    field.setStyleSheet("")
                    try:
                        if meta["type"] == "int" or meta["type"] == "float":
                            self.fields[section][key].setValue(value)
                            if meta["type"] == "int" and isinstance(value, float):
                                raise ValueError
                            if "min" in meta and value < float(meta["min"]):
                                raise ValueError
                        elif meta["type"] == "bool":
                            self.fields[section][key].setChecked(value)
                        else:
                            self.fields[section][key].setText(value)
                    except:
                        self.fields[section][key].setStyleSheet("background-color: #FDD;")
        except Exception as err:
            raise err
        finally:
            self.no_update = False

    def ButtonLoad(self):
        path = QtWidgets.QFileDialog.getOpenFileName(self, "Open File")
        if isinstance(path, tuple):
            path = str(path[0])
        else:
            path = str(path)
        if path:
            print("loading config")
            self.LoadConfig(path)

    def ButtonSave(self):
        print("saving config")
        if self.options.program:
            with open(options.config, "w") as fp:
                self.config.write(fp)
            self.close()
            if options.program:
                os.system(sys.executable + " " + options.program + " " + options.config)
        else:
            path = QtWidgets.QFileDialog.getSaveFileName(self, "Open File")
            if isinstance(path, tuple):
                path = str(path[0])
            else:
                path = str(path)
            if path:
                with open(path, "w") as fp:
                    self.config.write(fp)

    def EditorTextChanged(self):
        with open(tmp_config, 'w') as fp:
            fp.write(self.Scintilla.text())
        if not self.no_update:
            self.LoadConfig(tmp_config, editor_update=False)

    def changed(self, section, name, value):
        meta = self.meta[section][name]
        field = self.fields[section][name]
        if "unit_plus" in meta and value >= 0:
            field.setSuffix(" "+meta["unit_plus"])
        if "unit_minus" in meta and value < 0:
            field.setSuffix(" "+meta["unit_minus"])
        self.config.set(section, name, value)

        if not self.no_update:
            self.no_update = True
            with open(tmp_config, "w") as fp:
                self.config.write(fp)
            self.Scintilla.setText(open(tmp_config).read())
            self.no_update = False

    def reset(self, section, name):
        value, _ = getMeta(self.config_default.get(section, name))
        field = self.fields[section][name]
        if isinstance(field, QtWidgets.QSpinBox) or isinstance(field, QtWidgets.QDoubleSpinBox):
            field.setValue(value)
        elif isinstance(field, QtWidgets.QCheckBox):
            field.setChecked(value == "True")
        else:
            field.setText(value)


if __name__ == '__main__':
    from optparse import OptionParser
    path = os.path.dirname(__file__)
    parser = OptionParser()
    parser.add_option("-p", "--program", dest="program", default=None)
    parser.add_option("-c", "--config", dest="config", default="Config.txt")
    parser.add_option("-r", "--reset", dest="reset", default=os.path.join(path, "Config_Default.txt"))
    parser.add_option("-t", "--template", dest="template", default=os.path.join(path, "Config_Template.txt"))
    parser.add_option("-i", "--icon", dest="icon", default=None)
    (options, args) = parser.parse_args()

    # ensure output is written to output path
    options.config = os.path.join(output_path, options.config)

    app = QtWidgets.QApplication(sys.argv)

    window = ConfigEditor(options)
    window.show()
    app.exec_()
