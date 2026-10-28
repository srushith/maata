"""Small floating bar at the bottom of the screen that shows what Maata is doing.

It never takes focus, so the app you're dictating into stays active.
"""
import ctypes
import math

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QApplication, QWidget

from theme import COLORS

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080

BG = QColor(28, 30, 34, 240)
TEXT = QColor("#F2F3F5")
MUTED = QColor("#A0A6AF")


class RecordingPill(QWidget):
    stop_clicked = pyqtSignal()
    cancel_clicked = pyqtSignal()
    open_clicked = pyqtSignal()

    W, H = 236, 46
    BTN = 30  # button diameter

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(self.W, self.H)
        self.setMouseTracking(True)

        self.state = "hidden"   # recording, processing, done, error
        self.text = ""
        self.level = 0.0
        self.target_level = 0.0
        self.phase = 0.0
        self.hover = None       # "stop", "cancel" or None

        self.anim = QTimer(self)
        self.anim.timeout.connect(self._tick)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide_pill)

        font = QFont("Segoe UI Variable Text")
        font.setFamilies(["Segoe UI Variable Text", "Segoe UI"])
        font.setPixelSize(13)
        font.setWeight(QFont.DemiBold)
        self.setFont(font)

    # ---- Public ---------------------------------------------------------

    def show_recording(self):
        self._show("recording", "0:00")

    def set_time(self, text):
        self.text = text
        self.update()

    def set_level(self, value):
        self.target_level = max(0.0, min(1.0, value))

    def show_processing(self, text="Transcribing"):
        self._show("processing", text)

    def show_done(self, text):
        self._show("done", text)
        self.hide_timer.start(1400)

    def show_error(self, text):
        self._show("error", text)
        self.hide_timer.start(5000)

    def hide_pill(self):
        self.state = "hidden"
        self.anim.stop()
        self.hide_timer.stop()
        self.hide()

    # ---- Internals ------------------------------------------------------

    def _show(self, state, text):
        self.state = state
        self.text = text
        self.hover = None
        self.hide_timer.stop()
        if state != "recording":
            self.level = self.target_level = 0.0
        if not self.isVisible():
            self._place()
            self.show()
            self._make_non_activating()
        self.anim.start(16)
        self.update()

    def _place(self):
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(area.center().x() - self.W // 2, area.bottom() - self.H - 28)

    def _make_non_activating(self):
        # Clicking the bar mustn't pull focus away from the app being typed into.
        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        except Exception:
            pass

    def _tick(self):
        speed = 0.5 if self.target_level > self.level else 0.15
        self.level += (self.target_level - self.level) * speed
        self.phase += 0.12
        self.update()

    def _button_rects(self):
        y = (self.H - self.BTN) / 2
        stop = QRectF(self.W - 8 - self.BTN, y, self.BTN, self.BTN)
        cancel = QRectF(stop.left() - 6 - self.BTN, y, self.BTN, self.BTN)
        return stop, cancel

    def _hit(self, pos):
        if self.state != "recording":
            return None
        stop, cancel = self._button_rects()
        if stop.contains(QPointF(pos)):
            return "stop"
        if cancel.contains(QPointF(pos)):
            return "cancel"
        return None

    def mouseMoveEvent(self, event):
        hover = self._hit(event.pos())
        if hover != self.hover:
            self.hover = hover
            self.setCursor(Qt.PointingHandCursor if hover or self.state == "error"
                           else Qt.ArrowCursor)
            self.setToolTip({"stop": "Stop and transcribe",
                             "cancel": "Cancel (Esc)"}.get(hover, ""))
            self.update()

    def leaveEvent(self, event):
        self.hover = None
        self.update()

    def mouseReleaseEvent(self, event):
        hit = self._hit(event.pos())
        if hit == "stop":
            self.stop_clicked.emit()
        elif hit == "cancel":
            self.cancel_clicked.emit()
        elif self.state in ("error", "done"):
            self.open_clicked.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        body = QPainterPath()
        body.addRoundedRect(QRectF(0.5, 0.5, self.W - 1, self.H - 1), self.H / 2, self.H / 2)
        p.fillPath(body, BG)
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.drawPath(body)

        cy = self.H / 2
        x = 18
        if self.state == "recording":
            red = QColor(COLORS["recording"])
            pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(self.phase * 0.8))
            glow = QColor(red)
            glow.setAlpha(int(70 * pulse))
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QPointF(x + 5, cy), 9, 9)
            p.setBrush(red)
            p.drawEllipse(QPointF(x + 5, cy), 5, 5)

            # Level bars that move with your voice.
            bx = x + 20
            p.setBrush(TEXT)
            for i in range(5):
                wobble = 0.6 + 0.4 * math.sin(self.phase + i * 1.3)
                h = 4 + 18 * self.level * wobble
                p.drawRoundedRect(QRectF(bx + i * 6, cy - h / 2, 3, h), 1.5, 1.5)
            text_x = bx + 38
        elif self.state == "processing":
            amber = QColor(COLORS["processing"])
            p.setPen(QPen(amber, 2.5, Qt.SolidLine, Qt.RoundCap))
            p.setBrush(Qt.NoBrush)
            angle = int(self.phase * 50) % 360
            p.drawArc(QRectF(x - 2, cy - 7, 14, 14), -angle * 16, 270 * 16)
            text_x = x + 24
        elif self.state == "done":
            green = QColor(COLORS["success"])
            p.setPen(Qt.NoPen)
            p.setBrush(green)
            p.drawEllipse(QPointF(x + 5, cy), 8, 8)
            p.setPen(QPen(QColor("white"), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPolyline(QPointF(x + 1.5, cy), QPointF(x + 4, cy + 2.8), QPointF(x + 8.8, cy - 2.6))
            text_x = x + 24
        else:  # error
            red = QColor(COLORS["error"])
            p.setPen(Qt.NoPen)
            p.setBrush(red)
            p.drawEllipse(QPointF(x + 5, cy), 8, 8)
            p.setPen(QPen(QColor("white"), 2, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(x + 5, cy - 4), QPointF(x + 5, cy + 0.5))
            p.drawPoint(QPointF(x + 5, cy + 3.8))
            text_x = x + 24

        # Text
        right = self.W - 16
        if self.state == "recording":
            right = self._button_rects()[1].left() - 6
        p.setPen(TEXT)
        rect = QRectF(text_x, 0, right - text_x, self.H)
        text = p.fontMetrics().elidedText(self.text, Qt.ElideRight, int(rect.width()))
        p.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, text)

        # Buttons: cancel (x) and stop (square)
        if self.state == "recording":
            stop, cancel = self._button_rects()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 46 if self.hover == "cancel" else 22))
            p.drawEllipse(cancel)
            p.setPen(QPen(MUTED if self.hover != "cancel" else TEXT, 1.8, Qt.SolidLine, Qt.RoundCap))
            c = cancel.center()
            p.drawLine(QPointF(c.x() - 4.5, c.y() - 4.5), QPointF(c.x() + 4.5, c.y() + 4.5))
            p.drawLine(QPointF(c.x() + 4.5, c.y() - 4.5), QPointF(c.x() - 4.5, c.y() + 4.5))

            red = QColor(COLORS["recording"])
            if self.hover == "stop":
                red = red.lighter(115)
            p.setPen(Qt.NoPen)
            p.setBrush(red)
            p.drawEllipse(stop)
            p.setBrush(QColor("white"))
            c = stop.center()
            p.drawRoundedRect(QRectF(c.x() - 5, c.y() - 5, 10, 10), 2, 2)
        p.end()
