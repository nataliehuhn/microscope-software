import os
import numpy as np
from collections import OrderedDict
import xml.etree.ElementTree as ET
import xml.dom.minidom
import time

class EditLock:
    def __init__(self, command):
        self.command = command

    def __enter__(self):
        while self.command.locked:
            if time.time() - self.command.locked_time > 60:
                self.command.locked_time = time.time()
                break
            pass
        self.command.locked = True
        self.command.locked_time = time.time()

    def __exit__(self, type, value, traceback):
        self.command.locked = False


class MemMap(object):
    editLock = None

    def __init__(self, filename, layout=None, offset=0):
        self._maps = OrderedDict()
        self._layout = []
        self._single = {}
        if filename.endswith(".xml"):
            layout, filename = loadXML(filename)
        self._filename = filename
        self._start_offset = offset
        self._offset = offset
        self.add(layout)
        if "locked" in self._maps:
            self.editLock = EditLock(self)

    def add(self, layout):
        mode = 'r+' if os.path.exists(self._filename) else 'w+'
        for variable in layout:
            self._layout.append(variable)
            name = variable["name"]
            type = variable["type"]
            if "shape" in variable:
                shape = variable["shape"]
                self._single[name] = 0
            else:
                shape = (1,)
                self._single[name] = 1
            if "align" in variable:
                if self._offset % variable["align"] != 0:
                    self._offset += variable["align"] - self._offset % variable["align"]
            if type == "memmap":
                if self._single[name]:
                    map = MemMap(self._filename, variable["layout"], offset=self._offset)
                    self._offset = map.offset
                else:
                    map = []
                    try:
                        count = shape[0]
                    except TypeError:
                        count = shape
                    for i in range(count):
                        map_child = MemMap(self._filename, variable["layout"], offset=self._offset)
                        self._offset = map_child._offset
                        map.append(map_child)
            else:
                map = np.memmap(self._filename, dtype=type, mode=mode, offset=self._offset, shape=shape)
                self._offset += map.itemsize*map.size
            self._maps[name] = map
            mode = 'r+'

    def __getattr__(self, name):
        if name.startswith("_"):
            return getattr(self, name)
        if name != "_maps" and name in self._maps:
            if self._single[name] == 1:
                return self._maps[name][0]
            return self._maps[name]
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name != "_maps" and name in self._maps:
            if self._single[name] == 1:
                self._maps[name][0] = value
            else:
                raise ValueError("Access memmap array with []")
        else:
            super(MemMap, self).__setattr__(name, value)

    def __str__(self):
        text = "<Memmap: \"%s\" from bytes %d to %d>" % (self._filename, self._start_offset, self._offset)
        for name in self._maps:
            if self._single[name]:
                text += "\n%s: %s" % (name, self._maps[name][0].__str__())
            else:
                text += "\n%s: %s" % (name, self._maps[name].__str__())
        return text

    def saveXML(self, xml_filename):
        saveXML(xml_filename, self._layout, self._filename)


def getLayout(root):
    layout = []
    for child in root:
        element = child.attrib
        if element["type"] == "memmap":
            element["layout"] = getLayout(child)
        if "align" in element:
            element["align"] = int(element["align"])
        if "shape" in element:
            element["shape"] = tuple(int(part) for part in element["shape"].split())
        layout.append(element)
    return layout

def loadXML(xml_filename):
    root = ET.parse(xml_filename).getroot()
    memmap_filename = os.path.join(os.path.dirname(xml_filename), root.get("file"))
    return getLayout(root), memmap_filename

def getXML(layout, root):
    for element in layout:
        element = element.copy()
        sub_layout = None
        if "layout" in element:
            sub_layout = element["layout"]
            del element["layout"]
        if "align" in element:
            element["align"] = str(element["align"])
        if "shape" in element:
            element["shape"] = " ".join([str(i) for i in element["shape"]])
        sub_elm = ET.SubElement(root, 'entry', attrib=element)
        if sub_layout is not None:
            getXML(sub_layout, sub_elm)

def saveXML(xml_filename, layout, filename):
    filename = os.path.relpath(filename, os.path.dirname(xml_filename))
    root = ET.Element('memmap', attrib=dict(file=filename))
    getXML(layout, root)
    import xml.dom.minidom
    xml_dom = xml.dom.minidom.parseString(ET.tostring(root))
    with open(xml_filename, "w") as fp:
        fp.write(xml_dom.toprettyxml())

if __name__ == "__main__":
    ring_buffer_count = 10
    height = 10
    width = 20
    layout = (dict(name="busy", type="uint8"),
              dict(name="command", type="|S30", align=32),
              dict(name="current_index", type="uint32"),
              dict(name="current_command_index", type="uint32"),
              dict(name="images", type="memmap", shape=(ring_buffer_count,), layout=(
                  dict(name="width", type="uint16"),
                  dict(name="height", type="uint16"),
                  dict(name="data", align=64, type="uint16", shape=(height, width)),
              )),
              dict(name="commands", type="memmap", shape=(ring_buffer_count,), layout=(
                  dict(name="locked", type="uint8"),
                  dict(name="function", type="|S1024"),
                  dict(name="args", type="|S1024"),
                  dict(name="kwargs", type="|S1024"),
                  dict(name="status", type="int16"),
                  dict(name="error", type="int16"),
                  dict(name="response", type="|S1024"),
              )),
              dict(name="list", type="uint8", shape=(10)))
    #layout = loadXML('TestMemmap.xml')
    #a = MemMap(r"J:\Repositories\ClickPointsProject\clickpoints\includes\testing.xml")
    a = MemMap(r"tmp.dat", layout)
    #a.saveXML("testing2.xml")

    img = np.zeros((height, width))
    #a.saveToRingbuffer(img)
    #a.image[0].width = 131
    #a.image[0].height = 121
    #a.image[0].length = 379
    cmd = a.commands[0]
    with cmd.editLock:
        cmd.status = 1
        cmd.error = 1

    #a.image[1].width = 20
    #a.image[1].height = 221
    print(a.images[0])
    print(a.images[1])
    print(a)