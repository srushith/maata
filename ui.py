import ctypes
import ctypes.wintypes
import math

from PyQt5.QtWidgets import (
    QAction, QApplication, QFrame, QHBoxLayout, QLabel, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QSystemTrayIcon, QToolButton, QVBoxLayout, QWidget,
)
from PyQt5.QtCore import QElapsedTimer, QSize, Qt, QThread, QTimer, pyqtSignal

import settings
import recorder
import theme
from theme import COLORS
from hotkey import get_hotkey_candidates
from settings_dialog import SettingsDialog
from transcriber_api import transcribe_audio
from typer import get_foreground_window, is_paste_target, paste_text
from widgets import RecordButton, ToggleSwitch, make_icon, make_pin_icon

APP_ID = "Maata.App"  # lets Windows show our own taskbar icon instead of Python's
HOTKEY_ID = 1
WM_HOTKEY = 0x0312
MAX_SECONDS = 13 * 60  # OpenAI's 25 MB limit is about 13.5 minutes at 16 kHz

user32 = ctypes.windll.user32


def format_time(seconds):
    return f"{seconds // 60}:{seconds % 60:02d}"


class PasteWorker(QThread):
    """Pastes in the background so the window doesn't freeze while waiting."""
    done = pyqtSignal(str)

    def __init__(self, text, target_hwnd):
        super().__init__()
        self.text = text
        self.target_hwnd = target_hwnd

    def run(self):
        try:
            self.done.emit(paste_text(self.text, self.target_hwnd))
        except Exception as e:
            self.done.emit(f"Paste failed: {e}")


class Worker(QThread):
    finished = pyqtSignal(str, str)  # (text, error)

    def __init__(self, mic_name):
        super().__init__()
        self.mic_name = mic_name

    def run(self):
        try:
            filename = recorder.record_audio(mic_name=self.mic_name)
            text = (transcribe_audio(filename) or "").strip()
            self.finished.emit(text, "" if text else "No speech was recognised.")
        except Exception as e:
            self.finished.emit("", str(e))


class MaataUI(QWidget):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.paste_worker = None
        self.is_recording = False
        self.is_processing = False
        self.quitting = False
        self.tray = None
        self.tray_hint_shown = False
        self.target_hwnd = None         # window to paste into for this recording
        self.last_external_hwnd = None  # last app window the user used
        self.hotkey_registered = False
        self.hotkey_label = ""
        self.elapsed = QElapsedTimer()

        self.icons = {
            "idle": make_icon(COLORS["accent"]),
            "recording": make_icon(COLORS["recording"]),
            "processing": make_icon(COLORS["processing"]),
        }

        self.init_ui()
        self.init_tray()

        # Remember which app the user was in, so clicking our button or the
        # tray still pastes back into that app.
        self.focus_timer = QTimer(self)
        self.focus_timer.timeout.connect(self.track_foreground_window)
        self.focus_timer.start(250)

        # Updates the recording timer and mic level.
        self.record_timer = QTimer(self)
        self.record_timer.timeout.connect(self.update_recording_status)

        problem = self.register_hotkey()
        self.set_state("idle")
        if problem:
            self.set_hint(problem, error=True)
        if not settings.has_api_key():
            # First run: ask for the OpenAI key straight away.
            self.set_hint("Add your OpenAI API key in Settings to get started.", error=True)
            QTimer.singleShot(400, self.open_settings)

    # ---- Window ---------------------------------------------------------

    def window_flags(self, on_top):
        flags = (Qt.Window | Qt.WindowTitleHint | Qt.WindowMinimizeButtonHint
                 | Qt.WindowCloseButtonHint)
        return flags | Qt.WindowStaysOnTopHint if on_top else flags

    def init_ui(self):
        self.setObjectName("root")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle("Maata")
        self.setWindowIcon(self.icons["idle"])
        self.resize(420, 560)
        self.setMinimumSize(360, 460)
        on_top = settings.get_bool(settings.ON_TOP)
        self.setWindowFlags(self.window_flags(on_top))

        # Header: title, pin, settings
        title = QLabel("Maata")
        title.setObjectName("title")

        self.pin_button = QToolButton()
        self.pin_button.setObjectName("icon")
        self.pin_button.setIconSize(QSize(20, 20))
        self.pin_button.setCheckable(True)
        self.pin_button.setChecked(on_top)
        self.pin_button.setCursor(Qt.PointingHandCursor)
        self.pin_button.toggled.connect(self.set_on_top)
        self.update_pin_tooltip()

        self.settings_button = QToolButton()
        self.settings_button.setObjectName("icon")
        self.settings_button.setText("⚙")
        self.settings_button.setToolTip("Settings")
        self.settings_button.setCursor(Qt.PointingHandCursor)
        self.settings_button.clicked.connect(self.open_settings)

        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.pin_button)
        header.addWidget(self.settings_button)

        # Record button and status
        self.record_button = RecordButton()
        self.record_button.clicked.connect(self.toggle_recording)

        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setAlignment(Qt.AlignCenter)

        self.hint = QLabel()
        self.hint.setObjectName("hint")
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setWordWrap(True)

        # Transcript card
        self.text_box = QPlainTextEdit()
        self.text_box.setPlaceholderText("Your words will appear here.")
        self.text_box.textChanged.connect(self.update_word_count)

        self.word_count = QLabel("")
        self.word_count.setObjectName("count")

        self.copy_button = QPushButton("Copy")
        self.copy_button.setObjectName("ghost")
        self.copy_button.setCursor(Qt.PointingHandCursor)
        self.copy_button.clicked.connect(self.copy_text)

        self.clear_button = QPushButton("Clear")
        self.clear_button.setObjectName("ghost")
        self.clear_button.setCursor(Qt.PointingHandCursor)
        self.clear_button.clicked.connect(self.text_box.clear)

        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFrameShape(QFrame.HLine)

        card_footer = QHBoxLayout()
        card_footer.setContentsMargins(10, 4, 6, 6)
        card_footer.addWidget(self.word_count)
        card_footer.addStretch()
        card_footer.addWidget(self.copy_button)
        card_footer.addWidget(self.clear_button)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(8, 8, 8, 0)
        card_layout.setSpacing(0)
        card_layout.addWidget(self.text_box)
        card_layout.addWidget(divider)
        card_layout.addLayout(card_footer)

        self.checkbox = ToggleSwitch("Paste into the window I was using")
        self.checkbox.setChecked(settings.get_bool(settings.AUTOPASTE))
        self.checkbox.toggled.connect(
            lambda on: settings.save({settings.AUTOPASTE: "true" if on else "false"}))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 18)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addSpacing(10)
        layout.addWidget(self.record_button, alignment=Qt.AlignHCenter)
        layout.addSpacing(6)
        layout.addWidget(self.status)
        layout.addSpacing(4)
        layout.addWidget(self.hint)
        layout.addSpacing(18)
        layout.addWidget(card, stretch=1)
        layout.addSpacing(12)
        layout.addWidget(self.checkbox)

        self.update_word_count()

    def showEvent(self, event):
        super().showEvent(event)
        theme.apply_title_bar(self)

    def set_hint(self, text, error=False):
        self.hint.setText(text)
        self.hint.setProperty("error", "true" if error else "false")
        self.hint.style().unpolish(self.hint)
        self.hint.style().polish(self.hint)

    def default_hint(self):
        if self.hotkey_registered:
            return f"Press {self.hotkey_label} anywhere, or click the mic"
        return "Click the mic to start"

    def set_state(self, state, status=None, hint=None):
        """Update the button, status text, tray icon and tooltip together."""
        self.record_button.set_state(state)
        self.setWindowIcon(self.icons[state])

        if state == "idle":
            status = status or "Ready"
            hint = hint if hint is not None else self.default_hint()
            tooltip = (f"Maata: press {self.hotkey_label} to dictate"
                       if self.hotkey_registered else "Maata")
        elif state == "recording":
            status = status or "Listening"
            hint = hint if hint is not None else ""
            tooltip = "Maata: recording"
        else:
            status = status or "Transcribing"
            hint = hint if hint is not None else "This takes a few seconds"
            tooltip = "Maata: transcribing"

        self.status.setText(status)
        self.set_hint(hint)
        self.settings_button.setEnabled(state == "idle")
        if self.tray:
            self.tray.setIcon(self.icons[state])
            self.tray.setToolTip(tooltip)
            self.record_action.setText(
                "Stop recording" if state == "recording" else "Start recording")
            self.record_action.setEnabled(state != "processing")

    def update_word_count(self):
        words = len(self.text_box.toPlainText().split())
        self.word_count.setText(f"{words} word{'s' if words != 1 else ''}" if words else "")
        self.copy_button.setEnabled(words > 0)
        self.clear_button.setEnabled(words > 0)

    def copy_text(self):
        QApplication.clipboard().setText(self.text_box.toPlainText())
        self.copy_button.setText("Copied ✓")
        QTimer.singleShot(1500, lambda: self.copy_button.setText("Copy"))

    def set_on_top(self, on):
        settings.save({settings.ON_TOP: "true" if on else "false"})
        # Changing window flags makes Qt recreate the window, and the hotkey
        # belongs to the old one, so release it first and register it again.
        if self.hotkey_registered:
            user32.UnregisterHotKey(int(self.winId()), HOTKEY_ID)
            self.hotkey_registered = False
        visible = self.isVisible()
        self.setWindowFlags(self.window_flags(on))
        if visible:
            self.show()
        problem = self.register_hotkey()
        if problem and self.is_idle():
            self.set_hint(problem, error=True)
        self.update_pin_tooltip()

    def update_pin_tooltip(self):
        on = self.pin_button.isChecked()
        self.pin_button.setIcon(make_pin_icon(COLORS["accent"] if on else COLORS["muted"]))
        self.pin_button.setToolTip(
            "Keeping window on top (click to stop)" if self.pin_button.isChecked()
            else "Keep window on top")

    # ---- Tray -----------------------------------------------------------

    def init_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self.icons["idle"], self)

        menu = QMenu()
        self.record_action = QAction("Start recording", self)
        self.record_action.triggered.connect(self.toggle_recording)
        show_action = QAction("Show window", self)
        show_action.triggered.connect(self.show_window)
        settings_action = QAction("Settings...", self)
        settings_action.triggered.connect(self.open_settings)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.quit_app)
        for action in (self.record_action, show_action, settings_action):
            menu.addAction(action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray_menu = menu  # keep a reference so it isn't garbage-collected

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:  # left click
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.show_window()

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        # Closing the window keeps the app running in the tray.
        if not self.quitting and self.tray:
            event.ignore()
            self.hide()
            if not self.tray_hint_shown:
                self.tray_hint_shown = True
                hint = (f"Still running here. Press {self.hotkey_label} to dictate."
                        if self.hotkey_registered else "Still running here.")
                self.tray.showMessage("Maata", hint, self.icons["idle"], 4000)
            return
        self.shutdown()
        super().closeEvent(event)

    def quit_app(self):
        self.quitting = True
        self.close()
        QApplication.instance().quit()

    def shutdown(self):
        if self.hotkey_registered:
            user32.UnregisterHotKey(int(self.winId()), HOTKEY_ID)
            self.hotkey_registered = False
        if self.is_recording:
            recorder.stop_recording()
        if self.tray:
            self.tray.hide()

    # ---- Global hotkey --------------------------------------------------

    def register_hotkey(self, text=None):
        """Register the hotkey. Returns a message to show, or None if all is well."""
        hwnd = int(self.winId())
        if self.hotkey_registered:
            user32.UnregisterHotKey(hwnd, HOTKEY_ID)
            self.hotkey_registered = False

        candidates, warning = get_hotkey_candidates(text)
        for mods, key, label in candidates:
            if user32.RegisterHotKey(hwnd, HOTKEY_ID, mods, key):
                self.hotkey_registered = True
                self.hotkey_label = label
                return f"{warning} Using {label}." if warning else None
        self.hotkey_label = candidates[0][2]
        return f"{self.hotkey_label} is taken by another app. Choose another in Settings."

    def nativeEvent(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self.toggle_recording()
                return True, 0
        return super().nativeEvent(event_type, message)

    # ---- Settings -------------------------------------------------------

    def open_settings(self):
        if self.is_recording or self.is_processing:
            return
        if not self.isVisible():
            self.show_window()
        dialog = SettingsDialog(self)
        if not dialog.exec_():
            return
        values = dialog.values()
        old_hotkey = settings.get(settings.HOTKEY)
        if values[settings.HOTKEY] != old_hotkey:
            problem = self.register_hotkey(values[settings.HOTKEY])
            if not self.hotkey_registered:
                # Keep the old hotkey working and don't save the new one.
                self.register_hotkey(old_hotkey)
                values[settings.HOTKEY] = old_hotkey
                QMessageBox.warning(self, "Maata", problem)
        settings.save(values)
        self.set_state("idle", "Settings saved")
        QTimer.singleShot(2000, lambda: self.is_idle() and self.set_state("idle"))

    def is_idle(self):
        return not self.is_recording and not self.is_processing

    # ---- Target window tracking -----------------------------------------

    def track_foreground_window(self):
        hwnd = get_foreground_window()
        if is_paste_target(hwnd):
            self.last_external_hwnd = hwnd

    def current_target_window(self):
        hwnd = get_foreground_window()
        return hwnd if is_paste_target(hwnd) else self.last_external_hwnd

    # ---- Recording flow -------------------------------------------------

    def toggle_recording(self):
        if self.is_processing:
            return  # still transcribing the last recording
        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        if not settings.has_api_key():
            self.show_window()
            self.open_settings()
            return
        self.target_hwnd = self.current_target_window()
        self.is_recording = True
        self.elapsed.start()
        self.set_state("recording")
        self.update_recording_status()
        self.record_timer.start(50)
        self.worker = Worker(settings.get(settings.MIC))
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def update_recording_status(self):
        if not self.is_recording:
            return
        seconds = self.elapsed.elapsed() // 1000
        if seconds >= MAX_SECONDS:
            self.stop_recording("Reached the 13-minute limit")
            return
        self.status.setText(f"Listening  {format_time(seconds)}")
        stop = f"Press {self.hotkey_label} or click to stop" if self.hotkey_registered else "Click to stop"
        self.hint.setText(stop)
        if self.tray:
            self.tray.setToolTip(f"Maata: recording {format_time(seconds)}")
        # Loudness on a log scale (-55 dB to -10 dB) so normal speech moves the halo well.
        level = recorder.current_level
        value = 0.0
        if level > 0:
            db = 20 * math.log10(level)
            value = (db + 55) / 45
        self.record_button.set_level(value)

    def stop_recording(self, hint=None):
        self.is_recording = False
        self.is_processing = True
        self.record_timer.stop()
        self.set_state("processing", hint=hint)
        try:
            recorder.stop_recording()
        except Exception:
            pass

    def on_finished(self, text, error):
        self.is_recording = False
        self.is_processing = False

        if error:
            self.set_state("idle", "Something went wrong")
            self.set_hint(error, error=True)
            if not self.isVisible():
                self.show_window()  # make sure the user sees what went wrong
            return

        self.text_box.setPlainText(text)
        self.set_state("idle", "Done")

        if self.checkbox.isChecked():
            self.set_hint("Pasting...")
            self.paste_worker = PasteWorker(text, self.target_hwnd)
            self.paste_worker.done.connect(self.on_pasted)
            self.paste_worker.start()

    def on_pasted(self, message):
        ok = message.startswith("Pasted")
        if ok:
            self.set_state("idle", "Pasted")
        else:
            self.set_hint(message, error=True)


def launch_ui():
    settings.ensure_defaults()
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass
    app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(theme.stylesheet())
    app.setQuitOnLastWindowClosed(False)
    window = MaataUI()
    app.setWindowIcon(window.icons["idle"])
    window.show()
    app.exec_()


if __name__ == "__main__":
    launch_ui()
