from __future__ import division, print_function
import os
import sys
import subprocess
import math

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
        self.exposure_time.setRange(1, 1000)
        self.layout.addWidget(self.exposure_time, 1, 1)

        self.layout.addWidget(QtWidgets.QLabel("Gain"), 2, 0)
        self.gain_value = QtWidgets.QDoubleSpinBox()
        self.gain_value.setDecimals(2)
        self.gain_value.setSingleStep(0.1)
        self.gain_value.setRange(0, 255)
        self.gain_value.setToolTip(
            "Basler gain is in dB. Use the camera's supported range shown in LiveViewer."
        )
        self.layout.addWidget(self.gain_value, 2, 1)

        self.button = QtWidgets.QPushButton("ok")
        self.button.clicked.connect(self.ok)
        self.button.setShortcut("Return")
        self.layout.addWidget(self.button, 10, 0, 1, 2)

    def ok(self):
        mode = self.mode.itemText(self.mode.currentIndex())
        exp = self.exposure_time.value()
        gain = self.gain_value.value()
        text = "%s(%d, %g)" % (mode, exp, gain)
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
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        modes = split_non_excaped(text)
        for button in self.tag_buttons[::-1]:
            self.remove(button, no_signal=1)
        for mode in modes:
            if not mode:
                continue
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
                                numbers = [float(v) for v in values]
                                return all(math.isfinite(v) for v in numbers)
                            except:
                                pass
                return False
        return False

    def text(self):
        if not self.tags:
            return "[]"
        return "[Mode_"+", Mode_".join(self.tags)+"]"


class PathSelector(QtWidgets.QWidget):
    def __init__(self, path="", folder=False):
        QtWidgets.QWidget.__init__(self)
        self.setContentsMargins(0,0,0,0)
        self.layout = QtWidgets.QHBoxLayout(self)
        self.layout.setContentsMargins(0,0,0,0)

        self.edit = QtWidgets.QLineEdit(path)
        self.edit.setPlaceholderText("Current position" if not folder else "Choose an output folder")

        self.layout.addWidget(self.edit)

        self.load_button = QtWidgets.QPushButton("Browse…")
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
        self.setWindowTitle("Record" if options.program else "Recording settings")
        if options.icon:
            self.setWindowIcon(QtGui.QIcon(options.icon))
        layout_vert = QtWidgets.QVBoxLayout(self)
        layout_hor = QtWidgets.QHBoxLayout()
        layout_vert.addLayout(layout_hor)

        self.options_menu = QtWidgets.QMenu(self)
        self.options_menu.addAction("Load settings…", self.ButtonLoad)
        self.options_menu.addAction("Restore default settings", lambda: self.LoadConfig(self.options.reset))
        self.button_options = QtWidgets.QToolButton()
        self.button_options.setText("Options")
        self.button_options.setMenu(self.options_menu)
        self.button_options.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        layout_hor.addWidget(self.button_options)
        layout_hor.addStretch()
        self.advanced_toggle = QtWidgets.QCheckBox("Advanced settings")
        layout_hor.addWidget(self.advanced_toggle)

        self.plan_status = QtWidgets.QLabel()
        layout_vert.addWidget(self.plan_status)
        self.advanced_summary = QtWidgets.QLabel()
        self.advanced_summary.setWordWrap(True)
        layout_vert.addWidget(self.advanced_summary)

        layout_content = QtWidgets.QHBoxLayout()
        layout_vert.addLayout(layout_content)
        footer = QtWidgets.QHBoxLayout()
        layout_vert.addLayout(footer)
        footer.addStretch()
        self.button_cancel = QtWidgets.QPushButton("Close")
        self.button_cancel.clicked.connect(self.close)
        footer.addWidget(self.button_cancel)
        self.button_save = QtWidgets.QPushButton("Save and Start" if options.program else "Save settings…")
        self.button_save.clicked.connect(self.ButtonSave)
        footer.addWidget(self.button_save)

        self.form_scroll = QtWidgets.QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        form = QtWidgets.QWidget()
        layout_gui = QtWidgets.QVBoxLayout(form)
        self.form_scroll.setWidget(form)
        layout_content.addWidget(self.form_scroll, 1)

        layout_vert = layout_gui
        self.config_default = Config(options.template)
        self.fields = {}
        self.meta = {}
        self.group_boxes = {}
        self.row_widgets = {}
        for section in self.config_default.sections():
            box = QtWidgets.QGroupBox({"general": "Imaging", "files": "Files and positions",
                                      "stack": "Z scan", "repetition": "Repetitions",
                                      "position_sequence": "Position sequence", "cycles": "Full cycles"}
                                     .get(section, section.title()))
            box.setFlat(True)
            box_layout = QtWidgets.QGridLayout()
            items = self.config_default.items(section)
            self.fields[section] = {}
            self.meta[section] = {}
            self.row_widgets[section] = {}
            self.group_boxes[section] = box

            for index, item in enumerate(items):
                if item[0].startswith("@"):
                    continue
                name, value = item
                value, meta = getMeta(value)
                self.meta[section][name] = meta
                simple_labels = {
                    "record_modes": "Imaging modes", "wait_before_image": "Settle before image",
                    "wait_at_start": "Start delay", "positions_filename": "Positions file",
                    "target_folder": "Output folder", "slice_thickness": "Slice spacing",
                    "slice_start": "First slice", "slice_stop": "Last slice",
                    "minimum_duration_hours": "Duration (0 = count)",
                    "repetition_count": "Repetitions", "repetition_time_delta": "Interval between starts",
                    "repeat_positions_separately": "Repeat each position first",
                    "roi": "Image height (ROI)", "binning": "Pixel binning",
                }
                label = QtWidgets.QLabel(meta.get("label", simple_labels.get(name, name.replace("_", " ").capitalize())))
                box_layout.addWidget(label, index, 0)
                if meta["type"] == "int":
                    edit_field = QtWidgets.QSpinBox()
                    edit_field.setRange(-10000, 10000)
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
                    edit_field = QtWidgets.QCheckBox()
                    edit_field.setChecked(value)
                    edit_field.stateChanged.connect(lambda value, section=section, name=name: self.changed(section, name, "True" if value else "False"))
                elif meta["type"] == "file" or meta["type"] == "folder":
                    edit_field = PathSelector(value, meta["type"] == "folder")
                    edit_field.textChanged.connect(lambda value, section=section, name=name: self.changed(section, name, value))
                elif meta["type"] == "mode":
                    edit_field = ModeSelector(value)
                    edit_field.textChanged.connect(lambda value, section=section, name=name: self.changed(section, name, value))
                elif meta["type"] == "choice":
                    edit_field = QtWidgets.QComboBox()
                    values = meta["values"].split("|")
                    labels = meta.get("labels", meta["values"]).split("|")
                    if len(values) != len(labels):
                        raise ValueError("Choice labels and values must match")
                    for choice_label, choice_value in zip(labels, values):
                        edit_field.addItem(choice_label, choice_value)
                    selected = edit_field.findData(value)
                    if selected < 0:
                        raise ValueError("Unknown default choice for {}".format(name))
                    edit_field.setCurrentIndex(selected)
                    edit_field.currentIndexChanged.connect(
                        lambda index, field=edit_field, section=section, name=name:
                        self.changed(section, name, field.itemData(index))
                    )
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
                self.row_widgets[section][name] = (
                    label, edit_field, reset_button
                )
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

        layout_gui.addStretch()
        if "position_sequence" in self.fields:
            self.options_menu.addSeparator()
            presets = self.options_menu.addMenu("Presets")
            self.action_single_position_preset = presets.addAction("Single position, 24 h", self.applySinglePositionPreset)
            self.action_single_position_preset.setToolTip(
                "Use the current microscope position for at least 24 hours. "
                "Keeps the selected mode and Z scan settings; adjust the duration and interval below. "
                "To use a saved position, select a file containing exactly one position afterward."
            )
            self.action_timed_saved = presets.addAction("Timed: one saved position", self.applyTimedSavedPosition)
            self.action_repeated_saved = presets.addAction("Repetitions: saved positions", self.applyRepeatedSavedPositions)
            self.action_repeated_current = presets.addAction("Repetitions: current position", self.applyRepeatedCurrentPosition)
            self.action_assay_preset = presets.addAction("Migration assay", self.applyAssayPreset)
            self.action_assay_preset.setToolTip(
                "5 positions per condition; 22 optimized projections at 15 s; "
                "5 full cycles every 3 h. Keeps your files, modes, and Z scan settings."
            )
            self.options_menu.addAction("Preview route…", self.previewSequence)

        if qsci_loaded:
            self.Scintilla = Qsci.QsciScintilla()
            self.Scintilla.setLexer(Qsci.QsciLexerPython(self))
        else:
            self.Scintilla = QtWidgets.QTextEdit()
            self.Scintilla.text = self.Scintilla.toPlainText
        self.Scintilla.setMinimumWidth(400)

        self.no_update = False
        self.config_error = None
        self.invalid_fields = set()
        self.Scintilla.textChanged.connect(self.EditorTextChanged)
        layout_content.addWidget(self.Scintilla)
        self.Scintilla.hide()
        self.options_menu.addSeparator()
        self.action_text_editor = self.options_menu.addAction("Edit configuration text")
        self.action_text_editor.setCheckable(True)
        self.action_text_editor.toggled.connect(self.showTextEditor)
        self.advanced_toggle.toggled.connect(self.updateSimpleFields)

        self.config = Config()
        print("Load config")
        if os.path.exists(options.config):
            self.LoadConfig(options.config)
        else:
            self.LoadConfig(options.reset)
        if "projection_mode" in self.fields.get("stack", {}):
            self.fields["stack"]["projection_mode"].currentIndexChanged.connect(
                self.updateStackFields
            )
        self.updateStackFields()
        if "position_order" in self.fields.get("position_sequence", {}):
            self.fields["position_sequence"]["position_order"].currentIndexChanged.connect(
                self.updateSequenceFields
            )
        self.updateSequenceFields()
        self.updateSimpleFields()
        self.move(0, 0)
        
        # center window in desktop
        DRect = QtWidgets.QDesktopWidget().screenGeometry()
        self.resize(min(680, DRect.width() - 80), min(800, DRect.height() - 80))
        WRect = self.geometry()
        self.move((DRect.width()-WRect.width())//2, (DRect.height()-WRect.height())//4)

    def LoadConfig(self, path, editor_update=True):
        in_group = False
        lines = []
        with open(path, "r") as fp:
            for line in fp:
                if line.startswith("["):
                    in_group = not line.startswith("[dynamic]")
                if in_group:
                    lines.append(line)
        text = "".join(lines)
        candidate = ConfigParser.RawConfigParser()
        candidate.read_string(text)

        self.no_update = True
        try:
            if editor_update:
                self.Scintilla.setText(text)
            self.config = candidate
            self.config_error = None
            self.invalid_fields.clear()
            for section in self.fields:
                if not section in self.config.sections():
                    self.config.add_section(section)
                for key in self.fields[section]:
                    try:
                        value, meta = getMeta(self.config.get(section, key))
                    except ConfigParser.NoOptionError:
                        value, meta = getMeta(self.config_default.get(section, key))
                        if section == "stack" and key == "projection_mode":
                            # An older saved config's projection checkbox
                            # maps to off or the old/default method.
                            value = (
                                "default" if self.config.has_option(
                                    "stack", "projection"
                                ) and self.config.getboolean(
                                    "stack", "projection"
                                ) else "off"
                            )
                        self.config.set(section, key, value)
                    if section == "stack" and key == "projection_mode":
                        # Migrate the short-lived timed/legacy selector too.
                        if (value in ("timed", "legacy")
                                and self.config.has_option("stack", "projection")
                                and not self.config.getboolean(
                                    "stack", "projection")):
                            value = "off"
                        else:
                            value = {
                                "timed": "optimized", "legacy": "default"
                            }.get(value, value)
                        self.config.set(section, key, value)
                    field = self.fields[section][key]
                    meta = self.meta[section][key]
                    self.config.set(section, key, str(value))
                    field.setStyleSheet("")
                    try:
                        if meta["type"] == "int" or meta["type"] == "float":
                            self.fields[section][key].setValue(value)
                            if meta["type"] == "int" and isinstance(value, float):
                                raise ValueError
                            if "min" in meta and value < float(meta["min"]):
                                raise ValueError
                            if value < field.minimum() or value > field.maximum():
                                raise ValueError
                        elif meta["type"] == "bool":
                            self.fields[section][key].setChecked(value)
                        elif meta["type"] == "choice":
                            selected = self.fields[section][key].findData(value)
                            if selected < 0:
                                raise ValueError("Unknown choice {}".format(value))
                            self.fields[section][key].setCurrentIndex(selected)
                        else:
                            self.fields[section][key].setText(value)
                    except:
                        self.invalid_fields.add((section, key))
                        self.fields[section][key].setStyleSheet("background-color: #FDD;")
            if "projection_mode" in self.fields.get("stack", {}):
                self.config.remove_option("stack", "projection")
                self.config.remove_option("stack", "projection_save_raw")
        except Exception as err:
            raise err
        finally:
            self.no_update = False
        if "stack" in self.fields:
            self.updateStackFields()
        self.updateSequenceFields()
        self.updateSimpleFields()

    def showTextEditor(self, visible):
        self.Scintilla.setVisible(visible)
        width = 1100 if visible else 680
        self.resize(min(width, QtWidgets.QDesktopWidget().screenGeometry().width() - 80), self.height())

    def updateSimpleFields(self, *_):
        """Hide uncommon controls without changing their saved values."""
        advanced = self.advanced_toggle.isChecked()
        basic = {
            "general": {"record_modes", "wait_before_image"},
            "repetition": {"repetition_count", "repetition_time_delta", "minimum_duration_hours"},
        }
        advanced_sections = {"grid", "position_sequence", "cycles", "calls"}
        active = []
        for section, rows in self.row_widgets.items():
            self.group_boxes[section].setVisible(advanced or section not in advanced_sections)
            for name, (label, field, reset) in rows.items():
                uncommon = section in advanced_sections or (section in basic and name not in basic[section])
                visible = advanced or not uncommon
                label.setVisible(visible)
                field.setVisible(visible)
                reset.setVisible(visible and advanced)
                if uncommon and self.config.has_option(section, name):
                    value, _ = getMeta(self.config.get(section, name))
                    default, _ = getMeta(self.config_default.get(section, name))
                    if value != default:
                        active.append("{}: {}".format(label.text(), value))
        duration = self.fields.get("repetition", {}).get("minimum_duration_hours")
        if duration is not None:
            self.fields["repetition"]["repetition_count"].setEnabled(duration.value() == 0)
        self.advanced_summary.setText("Advanced settings in use: " + "; ".join(active))
        self.advanced_summary.setVisible(bool(active) and not advanced)
        self.updateStackFields()
        self.updatePlanStatus()

    def updateSequenceFields(self, *_):
        fields = self.fields.get("position_sequence", {})
        if "position_order" in fields:
            fields["positions_per_condition"].setEnabled(
                fields["position_order"].currentData() == "interleaved"
            )

    def applyAssayPreset(self):
        """Apply assay scheduling while retaining the user's sample settings."""
        settings = {
            ("stack", "projection_mode"): "optimized",
            ("position_sequence", "position_order"): "interleaved",
            ("position_sequence", "positions_per_condition"): 5,
            ("position_sequence", "settle_pattern_s"): "5,5,0.5,0.5",
            ("repetition", "repetition_count"): 22,
            ("repetition", "minimum_duration_hours"): 0.0,
            ("repetition", "repetition_time_delta"): 15.0,
            ("repetition", "repeat_positions_separately"): True,
            ("cycles", "cycle_count"): 5,
            ("cycles", "cycle_interval_hours"): 3.0,
            ("grid", "countx"): 1,
            ("grid", "county"): 1,
            ("general", "wait_before_image"): 0.0,
        }
        for (section, name), value in settings.items():
            field = self.fields[section][name]
            if isinstance(field, QtWidgets.QComboBox):
                field.setCurrentIndex(field.findData(value))
            elif isinstance(field, QtWidgets.QCheckBox):
                field.setChecked(value)
            elif isinstance(field, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                field.setValue(value)
            else:
                field.setText(value)
        self.updateStackFields()
        self.updateSequenceFields()

    def applySinglePositionPreset(self):
        """Set an elapsed-time experiment at the current microscope position."""
        settings = {
            ("files", "positions_filename"): "None",
            ("position_sequence", "position_order"): "as_saved",
            ("position_sequence", "settle_pattern_s"): "",
            ("repetition", "minimum_duration_hours"): 24.0,
            ("repetition", "repetition_count"): 1,
            ("repetition", "repetition_time_delta"): 15.0,
            ("repetition", "repeat_positions_separately"): False,
            ("cycles", "cycle_count"): 1,
            ("grid", "countx"): 1,
            ("grid", "county"): 1,
        }
        for (section, name), value in settings.items():
            field = self.fields[section][name]
            if isinstance(field, QtWidgets.QComboBox):
                field.setCurrentIndex(field.findData(value))
            elif isinstance(field, QtWidgets.QCheckBox):
                field.setChecked(value)
            elif isinstance(field, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                field.setValue(value)
            else:
                field.setText(value)
        self.updateSequenceFields()

    def applyTimedSavedPosition(self):
        """Use elapsed time with exactly one position from a saved file."""
        if not self.ensureSavedPositionsFile():
            return
        duration = self.fields["repetition"]["minimum_duration_hours"].value()
        self.fields["repetition"]["minimum_duration_hours"].setValue(
            duration if duration > 0 else 24.0
        )
        self.fields["repetition"]["repeat_positions_separately"].setChecked(False)
        self.fields["position_sequence"]["position_order"].setCurrentIndex(
            self.fields["position_sequence"]["position_order"].findData("as_saved")
        )
        self.fields["position_sequence"]["settle_pattern_s"].setText("")
        self.fields["cycles"]["cycle_count"].setValue(1)
        self.fields["grid"]["countx"].setValue(1)
        self.fields["grid"]["county"].setValue(1)
        self.updatePlanStatus()

    def applyRepeatedSavedPositions(self):
        """Use the repetition count with a saved positions file."""
        if not self.ensureSavedPositionsFile():
            return
        self.fields["repetition"]["minimum_duration_hours"].setValue(0)
        self.updatePlanStatus()

    def ensureSavedPositionsFile(self):
        filename, _ = getMeta(self.config.get("files", "positions_filename"))
        if filename and filename != "None":
            return True
        path = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose saved positions file"
        )
        path = path[0] if isinstance(path, tuple) else path
        if not path:
            return False
        self.fields["files"]["positions_filename"].setText(str(path))
        return True

    def applyRepeatedCurrentPosition(self):
        """Use the repetition count at the current stage position."""
        self.fields["repetition"]["minimum_duration_hours"].setValue(0)
        self.fields["files"]["positions_filename"].setText("None")
        self.fields["position_sequence"]["position_order"].setCurrentIndex(
            self.fields["position_sequence"]["position_order"].findData("as_saved")
        )
        self.fields["position_sequence"]["settle_pattern_s"].setText("")
        self.updatePlanStatus()

    def updatePlanStatus(self):
        if not hasattr(self, "plan_status") or not hasattr(self, "config"):
            return
        try:
            duration = float(self.config.get("repetition", "minimum_duration_hours"))
            filename, _ = getMeta(self.config.get("files", "positions_filename"))
        except (ConfigParser.NoOptionError, ConfigParser.NoSectionError, ValueError):
            return
        saved = bool(filename and filename != "None")
        if duration > 0:
            plan = "Timed for {:g} h at {}".format(
                duration, "one saved position" if saved else "the current position"
            )
            if saved:
                plan += " (file must contain exactly one position)"
        else:
            plan = "Fixed repetition count at {}".format(
                "saved positions" if saved else "the current position"
            )
        self.plan_status.setText("Current plan: " + plan)

    def sequencePreviewData(self):
        from leica_microscope.recording_sequence import (
            SequenceSettings, load_sequence_positions, sequence_rows,
        )
        settings = SequenceSettings.from_config(self.config)
        filename, _ = getMeta(self.config.get("files", "positions_filename"))
        if not filename or filename == "None":
            if settings.position_order != "as_saved" or settings.settle_pattern:
                raise ValueError("Choose a positions file for the condition/position sequence")
            return settings, []
        positions = load_sequence_positions(filename)
        return settings, sequence_rows(positions, settings)

    def previewSequence(self):
        try:
            settings, rows = self.sequencePreviewData()
        except (OSError, ValueError) as error:
            QtWidgets.QMessageBox.warning(self, "Check recording sequence", str(error))
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Recording route preview")
        layout = QtWidgets.QVBoxLayout(dialog)
        summary = QtWidgets.QLabel(
            "{} full cycle(s), every {:g} h from the previous cycle start.\n"
            "{} saved position(s). Each cycle runs the complete route and its repetitions.\n"
            "File rows and conditions below are numbered from 1; TIFF pos indices start at 0."
            .format(settings.cycle_count, settings.cycle_interval_hours, len(rows))
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        table = QtWidgets.QTableWidget(len(rows), 7)
        table.setHorizontalHeaderLabels(["Visit", "Condition", "Pos in condition", "File row", "X", "Y / Z", "Settle (s)"])
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        for index, row in enumerate(rows):
            x, y, z = row["xyz_steps"]
            values = [row["visit"], row["condition"], row["position_in_condition"],
                      row["saved_position"], x, "{} / {}".format(y, z), row["settle_seconds"]]
            for column, value in enumerate(values):
                table.setItem(index, column, QtWidgets.QTableWidgetItem("-" if value is None else str(value)))
        table.resizeColumnsToContents()
        layout.addWidget(table)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.resize(850, 550)
        dialog.exec_()

    def updateStackFields(self, *_):
        """Show only the controls used by the selected stack/projection mode."""
        if "projection_mode" not in self.fields.get("stack", {}):
            return
        mode = self.fields["stack"]["projection_mode"].currentData()
        legacy_fields = {"slice_thickness", "slice_start", "slice_stop"}
        optimized_fields = {
            "projection_start_um", "projection_stop_um", "projection_time_s"
        }
        visible_count = 0
        for name, widgets in self.row_widgets["stack"].items():
            visible = (
                (name not in legacy_fields and name not in optimized_fields)
                or (name in legacy_fields and mode != "optimized")
                or (name in optimized_fields and mode == "optimized")
            )
            for widget in widgets[:2]:
                widget.setVisible(visible)
            widgets[2].setVisible(visible and self.advanced_toggle.isChecked())
            visible_count += int(visible)
        self.group_boxes["stack"].setMinimumHeight(0)
        self.group_boxes["stack"].layout().invalidate()

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
        try:
            if self.config_error:
                raise ValueError("Finish editing the configuration text: " + self.config_error)
            if self.invalid_fields:
                raise ValueError("Correct the highlighted settings: " + ", ".join(
                    "{}.{}".format(*key) for key in sorted(self.invalid_fields)))
            self.validateRecordingPlan()
        except (OSError, ValueError, ConfigParser.Error) as error:
            QtWidgets.QMessageBox.warning(self, "Check recording settings", str(error))
            return
        if self.options.program:
            if "position_sequence" in self.fields:
                try:
                    self.sequencePreviewData()
                except (OSError, ValueError) as error:
                    QtWidgets.QMessageBox.warning(self, "Check recording sequence", str(error))
                    return
            with open(self.options.config, "w") as fp:
                self.config.write(fp)
            self.close()
            subprocess.run(
                [sys.executable, self.options.program, self.options.config],
                check=True,
            )
        else:
            path = QtWidgets.QFileDialog.getSaveFileName(self, "Open File")
            if isinstance(path, tuple):
                path = str(path[0])
            else:
                path = str(path)
            if path:
                with open(path, "w") as fp:
                    self.config.write(fp)

    def validateRecordingPlan(self):
        if "position_sequence" not in self.fields:
            return
        settings, rows = self.sequencePreviewData()
        modes = self.fields["general"]["record_modes"]
        if not modes.tags or not all(modes.CheckIfModeIsValid(mode) for mode in modes.tags):
            raise ValueError("Choose at least one valid imaging mode.")
        duration = self.fields["repetition"]["minimum_duration_hours"].value()
        if duration > 0:
            if len(rows) > 1:
                raise ValueError("Duration recording found {} saved positions; it needs exactly one saved position. Clear the positions file to use the current stage position.".format(len(rows)))
            if len(modes.tags) != 1 or settings.cycle_count != 1 or any(
                    self.fields["grid"][name].value() != 1 for name in ("countx", "county")):
                raise ValueError("Duration recording needs one imaging mode, a 1 x 1 grid and one full cycle.")
        stack = self.fields["stack"]
        if self.fields["repetition"]["repetition_time_delta"].value() < 0:
            raise ValueError("The interval between starts must be nonnegative.")
        if stack["projection_mode"].currentData() == "default" and stack["slice_start"].value() == stack["slice_stop"].value():
            raise ValueError("A projection needs different first and last Z slices.")
        if stack["projection_mode"].currentData() == "optimized" and stack["projection_start_um"].value() == stack["projection_stop_um"].value():
            raise ValueError("An optimized projection needs different start and stop Z offsets.")

    def EditorTextChanged(self):
        if self.no_update:
            return
        with open(tmp_config, 'w') as fp:
            fp.write(self.Scintilla.text())
        try:
            self.LoadConfig(tmp_config, editor_update=False)
        except (ConfigParser.Error, ValueError, TypeError) as error:
            self.config_error = str(error)
            self.Scintilla.setToolTip("Incomplete configuration: " + str(error))

    def changed(self, section, name, value):
        if self.no_update:
            return
        meta = self.meta[section][name]
        field = self.fields[section][name]
        if "unit_plus" in meta and value >= 0:
            field.setSuffix(" "+meta["unit_plus"])
        if "unit_minus" in meta and value < 0:
            field.setSuffix(" "+meta["unit_minus"])
        if meta["type"] in ("file", "folder") and not str(value).strip():
            value = "None"
        self.config.set(section, name, str(value))
        self.invalid_fields.discard((section, name))
        field.setStyleSheet("")

        if not self.no_update:
            self.no_update = True
            with open(tmp_config, "w") as fp:
                self.config.write(fp)
            self.Scintilla.setText(open(tmp_config).read())
            self.no_update = False
            self.config_error = None
            self.updateSimpleFields()

    def reset(self, section, name):
        value, _ = getMeta(self.config_default.get(section, name))
        field = self.fields[section][name]
        if isinstance(field, QtWidgets.QSpinBox) or isinstance(field, QtWidgets.QDoubleSpinBox):
            field.setValue(value)
        elif isinstance(field, QtWidgets.QCheckBox):
            field.setChecked(bool(value))
        elif isinstance(field, QtWidgets.QComboBox):
            selected = field.findData(value)
            if selected < 0:
                raise ValueError("Unknown default choice {}".format(value))
            field.setCurrentIndex(selected)
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
