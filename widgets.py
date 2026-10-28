from PyQt5.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PyQt5.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QAbstractButton, QCheckBox

from theme import COLORS


def draw_mic(p, cx, cy, size, color):
    """A simple microphone glyph centred on (cx, cy)."""
    s = size / 40.0
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawRoundedRect(QRectF(cx - 7 * s, cy - 16 * s, 14 * s, 22 * s), 7 * s, 7 * s)
    pen = QPen(color, 3 * s, Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(cx - 12 * s, cy - 10 * s, 24 * s, 22 * s), 200 * 16, 140 * 16)
    p.drawLine(QPointF(cx, cy + 12 * s), QPointF(cx, cy + 17 * s))
    p.drawLine(QPointF(cx - 6 * s, cy + 17 * s), QPointF(cx + 6 * s, cy + 17 * s))


def make_icon(color):
    """Round microphone icon for the window and tray."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(2, 2, 60, 60)
    draw_mic(p, 32, 31, 44, QColor("white"))
    p.end()
    return QIcon(pixmap)


class RecordButton(QAbstractButton):
    """Big round record button.

    idle: mic icon. recording: stop square with a halo that grows with your voice.
    processing: spinning arc.
    """

    SIZE = 132
    RADIUS = 42

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.state = "idle"
        self.level = 0.0   # 0..1, smoothed
        self.target_level = 0.0
        self.angle = 0
        self.hover = False
        self.anim = QTimer(self)
        self.anim.timeout.connect(self._tick)

    def set_state(self, state):
        self.state = state
        self.setEnabled(state != "processing")
        self.setCursor(Qt.ArrowCursor if state == "processing" else Qt.PointingHandCursor)
        if state == "idle":
            self.anim.stop()
            self.level = self.target_level = 0.0
        else:
            self.anim.start(16)
        self.update()

    def set_level(self, level):
        self.target_level = max(0.0, min(1.0, level))

    def _tick(self):
        # Rise quickly, fall slowly, so the halo feels smooth.
        speed = 0.5 if self.target_level > self.level else 0.12
        self.level += (self.target_level - self.level) * speed
        self.angle = (self.angle + 6) % 360
        self.update()

    def enterEvent(self, event):
        self.hover = True
        self.update()

    def leaveEvent(self, event):
        self.hover = False
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        r = self.RADIUS

        color = QColor({
            "idle": COLORS["accent"],
            "recording": COLORS["recording"],
            "processing": COLORS["processing"],
        }[self.state])
        if self.hover and self.state != "processing":
            color = color.lighter(110)

        # Halo
        if self.state == "recording":
            halo = QColor(color)
            halo.setAlpha(55)
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            hr = r + 6 + self.level * 18
            p.drawEllipse(c, hr, hr)
        elif self.state == "idle":
            halo = QColor(color)
            halo.setAlpha(40 if self.hover else 22)
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(c, r + 8, r + 8)

        # Main circle
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawEllipse(c, r, r)

        white = QColor("white")
        if self.state == "idle":
            draw_mic(p, c.x(), c.y(), 40, white)
        elif self.state == "recording":
            p.setBrush(white)
            p.drawRoundedRect(QRectF(c.x() - 12, c.y() - 12, 24, 24), 5, 5)
        else:
            pen = QPen(white, 4, Qt.SolidLine, Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawArc(QRectF(c.x() - 16, c.y() - 16, 32, 32), -self.angle * 16, 270 * 16)
        p.end()


def make_pin_icon(color, size=20):
    """Push-pin icon drawn in one colour, to match the other header icons."""
    pixmap = QPixmap(size * 2, size * 2)  # 2x for sharpness on high-DPI screens
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(size / 2, size / 2)
    p.rotate(45)
    col = QColor(color)
    p.setPen(Qt.NoPen)
    p.setBrush(col)
    p.drawRoundedRect(QRectF(-3.5, -8, 7, 7), 1.5, 1.5)   # head
    p.drawRect(QRectF(-6, -1.5, 12, 2.5))                 # collar
    p.setPen(QPen(col, 1.6, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(0, 1), QPointF(0, 8))              # needle
    p.end()
    return QIcon(pixmap)


class ToggleSwitch(QCheckBox):
    """A checkbox drawn as an on/off switch, with its label on the right."""

    TRACK_W, TRACK_H = 34, 18

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(24)

    def sizeHint(self):
        hint = super().sizeHint()
        return hint.expandedTo(QSize(self.TRACK_W + 10 + self.fontMetrics().horizontalAdvance(self.text()), 24))

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        y = (self.height() - self.TRACK_H) / 2
        on = self.isChecked()

        p.setPen(Qt.NoPen if on else QPen(QColor(COLORS["border"]), 1))
        p.setBrush(QColor(COLORS["accent"] if on else COLORS["surface"]))
        p.drawRoundedRect(QRectF(0.5, y + 0.5, self.TRACK_W - 1, self.TRACK_H - 1),
                          self.TRACK_H / 2, self.TRACK_H / 2)

        knob = self.TRACK_H - 6
        x = self.TRACK_W - knob - 3 if on else 3
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("white") if on else QColor(COLORS["muted"]))
        p.drawEllipse(QRectF(x, y + 3, knob, knob))

        p.setPen(QColor(COLORS["text"]))
        text_rect = self.rect().adjusted(self.TRACK_W + 10, 0, 0, 0)
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.end()


def make_history_icon(color, size=20):
    """Clock with a small back-arrow, for the History button."""
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    col = QColor(color)
    c = size / 2
    p.setPen(QPen(col, 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    r = size * 0.36
    p.drawArc(QRectF(c - r, c - r, 2 * r, 2 * r), 120 * 16, 300 * 16)  # open circle
    p.drawLine(QPointF(c, c - r * 0.55), QPointF(c, c))                  # hour hand
    p.drawLine(QPointF(c, c), QPointF(c + r * 0.45, c + r * 0.3))         # minute hand
    ax, ay = c - r * 0.5, c - r * 0.87                                     # arrow head
    p.drawLine(QPointF(ax, ay), QPointF(ax - 3, ay - 0.5))
    p.drawLine(QPointF(ax, ay), QPointF(ax + 0.5, ay + 3))
    p.end()
    return QIcon(pixmap)
