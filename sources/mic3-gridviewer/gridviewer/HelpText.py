from qtpy import QtGui, QtCore, QtWidgets

import numpy as np
import os

class BoxGrabber(QtWidgets.QGraphicsRectItem):
    def __init__(self, parent):
        QtWidgets.QGraphicsRectItem.__init__(self, parent)

        self.parent = parent
        self.setCursor(QtGui.QCursor(QtCore.Qt.OpenHandCursor))
        width = parent.rect().width()
        self.setRect(QtCore.QRectF(0, 0, width, 10))
        self.setPos(parent.rect().x(), 0)

        self.setBrush(QtGui.QBrush(QtGui.QColor(0, 0, 0, 128)))

        path = QtGui.QPainterPath()
        path.moveTo(5, 3)
        path.lineTo(width - 5, 3)
        path.moveTo(5, 6)
        path.lineTo(width - 5, 6)
        pathItem = QtWidgets.QGraphicsPathItem(path, self)
        pathItem.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255)))
        pathItem.setBrush(QtGui.QBrush(QtGui.QColor(255, 255, 255)))

        self.dragged = False
        self.drag_offset = None

    def mousePressEvent(self, event):
        if event.button() == 1:
            self.dragged = True
            self.drag_offset = self.parent.mapToParent(self.mapToParent(event.pos())) - self.parent.pos()

    def mouseMoveEvent(self, event):
        if self.dragged:
            pos = self.parent.mapToParent(self.mapToParent(event.pos())) - self.drag_offset
            self.parent.setPos(pos.x(), pos.y())

    def mouseReleaseEvent(self, event):
        self.dragged = False


class HelpText(QtWidgets.QGraphicsRectItem):
    def __init__(self, parent, file):
        QtWidgets.QGraphicsRectItem.__init__(self, parent)

        self.setCursor(QtGui.QCursor(QtCore.Qt.ArrowCursor))

        self.help_text = QtWidgets.QGraphicsSimpleTextItem(self)
        self.help_text.setFont(QtGui.QFont("", 11))
        self.help_text.setPos(0, 10)
        self.help_text.setBrush(QtGui.QBrush(QtGui.QColor(255, 255, 255)))

        self.setBrush(QtGui.QBrush(QtGui.QColor(0, 0, 0, 128)))
        self.setPos(100, 100)
        self.setZValue(19)

        self.UpdateText(file)
        BoxGrabber(self)
        self.setVisible(False)

    def ShowHelpText(self):
        if self.isVisible():
            self.setVisible(False)
        else:
            self.setVisible(True)

    def UpdateText(self, file):
        import re
        text = ""
        with open(file) as fp:
            for line in fp.readlines():
                m = re.match(r'\w*# @key (.*)$', line.strip())
                if m:
                    text += m.groups()[0].replace(":", ":\t", 1) + "\n"
        self.help_text.setText(text[:-1])
        rect = self.help_text.boundingRect()
        rect.setX(-5)
        rect.setWidth(rect.width() + 5)
        rect.setHeight(rect.height() + 15)
        self.setRect(rect)

    def mousePressEvent(self, event):
        pass

    def mouseMoveEvent(self, event):
        pass

    def mouseReleaseEvent(self, event):
        pass
