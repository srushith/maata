import ctypes
import ctypes.wintypes
import getpass
import math
import os
import re

from PyQt5.QtWidgets import (
    QAction, QApplication, QFrame, QHBoxLayout, QLabel, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QSystemTrayIcon, QToolButton, QVBoxLayout, QWidget,
)
from PyQt5.QtCore import QElapsedTimer, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtNetwork import QLocalServer, QLocalSocket

import history
import settings
import recorder
import sounds
import theme
import updater
from version import RELEASES_URL, __version__
from theme import COLORS
from history_dialog import HistoryDialog
from hotkey import MOD_NOREPEAT, get_hotkey_candidates
from overlay import RecordingPill
from settings_dialog import SettingsDialog
from transcriber_api import clean_up, transcribe_audio
from typer import get_foreground_window, is_paste_target, paste_text
from widgets import RecordButton, ToggleSwitch, make_history_icon, make_icon, make_pin_icon

APP_ID = "Maata.App"  # lets Windows show our own taskbar icon instead of Python's
HOTKEY_ID = 1
CANCEL_ID = 2  # Esc, only registered while recording
WM_HOTKEY = 0x0312
VK_ESCAPE = 0x1B
MAX_SECONDS = 13 * 60  # OpenAI's 25 MB limit is about 13.5 minutes at 16 kHz
UPDATE_CHECK_MS = 24 * 60 * 60 * 1000  # check GitHub for a new version once a day

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


class UpdateChecker(QThread):
    found = pyqtSignal(str, str)  # (version, url)

    def run(self):
        try:
            version, url = updater.latest_release()
        except Exception:
            return  # offline or GitHub unreachable: try again later
        if updater.is_newer(version):
            self.found.emit(version, url)


class Worker(QThread):
    """Records (unless retrying a saved recording), transcribes and tidies up."""
    stage = pyqtSignal(str)
    finished = pyqtSignal(str, str, bool, str)  # (text, error, can_retry, note)

    def __init__(self, filename, mic_name="", record=True):
        super().__init__()
        self.filename = filename
        self.mic_name = mic_name
        self.record = record
        self.cancelled = False
        self.trimmed = 0.0  # seconds of silence cut out before uploading

    def run(self):
        if self.record:
            try:
                self.trimmed = recorder.record_audio(
                    self.filename, self.mic_name, trim=settings.get_bool(settings.TRIM_SILENCE))
            except Exception as e:
                recorder.delete_recording(self.filename)
                self.finished.emit("", "" if self.cancelled else str(e), False, "")
                return
            if self.cancelled:
                recorder.delete_recording(self.filename)
                self.finished.emit("", "", False, "")
                return

        self.stage.emit("Transcribing")
        try:
            text = (transcribe_audio(self.filename) or "").strip()
        except Exception as e:
            # Keep the recording so the user can try again.
            self.finished.emit("", str(e), True, "")
            return
        if not text:
            recorder.delete_recording(self.filename)
            self.finished.emit("", "No speech was recognised.", False, "")
            return

        note = ""
        if settings.get_bool(settings.CLEANUP):
            self.stage.emit("Cleaning up")
            try:
                text = clean_up(text)
            except Exception as e:
                note = f"AI cleanup skipped ({e}). Showing the plain transcript."
        recorder.delete_recording(self.filename)
        self.finished.emit(text, "", False, note)


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
        self.cancel_key_registered = False
        self.hotkey_label = ""
        self.pending_file = None        # a recording that failed to transcribe
        self.update_checker = None
        self.announced_version = None
        self.done_hint = None
        self.elapsed = QElapsedTimer()

        self.icons = {
            "idle": make_icon(COLORS["accent"]),
            "recording": make_icon(COLORS["recording"]),
            "processing": make_icon(COLORS["processing"]),
        }

        self.init_ui()
        self.init_tray()

        self.pill = RecordingPill()
        self.pill.stop_clicked.connect(self.toggle_recording)
        self.pill.cancel_clicked.connect(self.cancel_recording)
        self.pill.open_clicked.connect(self.show_window)

        # Remember which app the user was in, so clicking our button or the
        # tray still pastes back into that app.
        self.focus_timer = QTimer(self)
        self.focus_timer.timeout.connect(self.track_foreground_window)
        self.focus_timer.start(250)

        # Updates the recording timer and mic level.
        self.record_timer = QTimer(self)
        self.record_timer.timeout.connect(self.update_recording_status)

        # Check GitHub for a newer version shortly after start, then daily.
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.check_for_updates)
        self.update_timer.start(UPDATE_CHECK_MS)
        QTimer.singleShot(8000, self.check_for_updates)

        problem = self.register_hotkey()
        self.set_state("idle")
        if problem:
            self.set_hint(problem, error=True)
        self.recover_unsent_recording()
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
        self.resize(420, 600)
        self.setMinimumSize(360, 500)
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

        self.history_button = QToolButton()
        self.history_button.setObjectName("icon")
        self.history_button.setIcon(make_history_icon(COLORS["muted"]))
        self.history_button.setIconSize(QSize(20, 20))
        self.history_button.setToolTip("History")
        self.history_button.setCursor(Qt.PointingHandCursor)
        self.history_button.clicked.connect(self.open_history)

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
        header.addWidget(self.history_button)
        header.addWidget(self.settings_button)

        # Shown when a newer version is on GitHub.
        self.update_banner = QLabel()
        self.update_banner.setObjectName("banner")
        self.update_banner.setOpenExternalLinks(True)
        self.update_banner.setAlignment(Qt.AlignCenter)
        self.update_banner.setWordWrap(True)
        self.update_banner.hide()

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

        # Shown when a recording couldn't be transcribed, so it isn't lost.
        self.retry_button = QPushButton("Retry")
        self.retry_button.setObjectName("primary")
        self.retry_button.setCursor(Qt.PointingHandCursor)
        self.retry_button.clicked.connect(self.retry_recording)
        self.discard_button = QPushButton("Discard")
        self.discard_button.setObjectName("ghost")
        self.discard_button.setCursor(Qt.PointingHandCursor)
        self.discard_button.clicked.connect(self.discard_recording)
        self.retry_row = QWidget()
        retry_layout = QHBoxLayout(self.retry_row)
        retry_layout.setContentsMargins(0, 8, 0, 0)
        retry_layout.addStretch()
        retry_layout.addWidget(self.retry_button)
        retry_layout.addWidget(self.discard_button)
        retry_layout.addStretch()
        self.retry_row.hide()

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

        self.cleanup_switch = ToggleSwitch("Clean up text with AI")
        self.cleanup_switch.setToolTip(
            "Removes um/uh and repeated words, fixes punctuation and formats lists.\n"
            "Adds well under a cent per recording.")
        self.cleanup_switch.setChecked(settings.get_bool(settings.CLEANUP))
        self.cleanup_switch.toggled.connect(
            lambda on: settings.save({settings.CLEANUP: "true" if on else "false"}))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 18)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addWidget(self.update_banner)
        layout.addSpacing(10)
        layout.addWidget(self.record_button, alignment=Qt.AlignHCenter)
        layout.addSpacing(6)
        layout.addWidget(self.status)
        layout.addSpacing(4)
        layout.addWidget(self.hint)
        layout.addWidget(self.retry_row)
        layout.addSpacing(18)
        layout.addWidget(card, stretch=1)
        layout.addSpacing(12)
        layout.addWidget(self.checkbox)
        layout.addSpacing(4)
        layout.addWidget(self.cleanup_switch)

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
        self.update_retry_controls()
        if self.tray:
            self.tray.setIcon(self.icons[state])
            self.tray.setToolTip(tooltip)
            self.record_action.setText(
                "Stop recording" if state == "recording" else "Start recording")
            self.record_action.setEnabled(state != "processing")

    def update_retry_controls(self):
        has_pending = bool(self.pending_file) and os.path.exists(self.pending_file)
        idle = self.is_idle()
        self.retry_row.setVisible(has_pending)
        self.retry_button.setEnabled(idle)
        self.discard_button.setEnabled(idle)
        if self.tray:
            self.retry_action.setVisible(has_pending)
            self.retry_action.setEnabled(idle)

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
        self.release_cancel_key()
        visible = self.isVisible()
        self.setWindowFlags(self.window_flags(on))
        if visible:
            self.show()
        problem = self.register_hotkey()
        if self.is_recording:
            self.grab_cancel_key()
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
        self.retry_action = QAction("Retry last recording", self)
        self.retry_action.triggered.connect(self.retry_recording)
        self.retry_action.setVisible(False)
        show_action = QAction("Show window", self)
        show_action.triggered.connect(self.show_window)
        settings_action = QAction("Settings...", self)
        settings_action.triggered.connect(self.open_settings)
        history_action = QAction("History...", self)
        history_action.triggered.connect(self.open_history)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.quit_app)
        for action in (self.record_action, self.retry_action, show_action, history_action,
                       settings_action):
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
        self.release_cancel_key()
        if self.is_recording:
            recorder.stop_recording()
        self.pill.hide_pill()
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
            if msg.message == WM_HOTKEY and msg.wParam == CANCEL_ID:
                self.cancel_recording()
                return True, 0
        return super().nativeEvent(event_type, message)

    def grab_cancel_key(self):
        """Make Esc cancel the recording from any app (only while recording)."""
        if not self.cancel_key_registered:
            self.cancel_key_registered = bool(
                user32.RegisterHotKey(int(self.winId()), CANCEL_ID, MOD_NOREPEAT, VK_ESCAPE))

    def release_cancel_key(self):
        if self.cancel_key_registered:
            user32.UnregisterHotKey(int(self.winId()), CANCEL_ID)
            self.cancel_key_registered = False

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.is_recording:
            self.cancel_recording()
            return
        super().keyPressEvent(event)

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
        if not settings.get_bool(settings.HISTORY):
            history.clear()
        if settings.get_bool(settings.CHECK_UPDATES):
            self.check_for_updates()
        else:
            self.update_banner.hide()
        self.set_state("idle", "Settings saved")
        QTimer.singleShot(2000, lambda: self.is_idle() and self.set_state("idle"))

    def is_idle(self):
        return not self.is_recording and not self.is_processing

    def open_history(self):
        if not self.isVisible():
            self.show_window()
        HistoryDialog(self).exec_()

    # ---- Updates and sounds ---------------------------------------------

    def check_for_updates(self):
        if not settings.get_bool(settings.CHECK_UPDATES) or updater.installed_from_store():
            return
        if self.update_checker and self.update_checker.isRunning():
            return
        self.update_checker = UpdateChecker()
        self.update_checker.found.connect(self.on_update_found)
        self.update_checker.start()

    def on_update_found(self, version, url):
        if not url.startswith("https://github.com/"):
            url = RELEASES_URL
        self.update_banner.setText(
            f'Maata {version} is available (you have {__version__}). '
            f'<a style="color:{COLORS["accent"]}" href="{url}">Download</a>')
        self.update_banner.show()
        if self.tray and self.announced_version != version:
            self.announced_version = version
            self.tray.showMessage("Maata update", f"Maata {version} is available. "
                                  "Open Maata to download it.", self.icons["idle"], 6000)

    def play_sound(self, name):
        if settings.get_bool(settings.SOUNDS):
            sounds.play(name)

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
        self.play_sound("start")
        self.is_recording = True
        self.elapsed.start()
        self.set_state("recording")
        self.pill.show_recording()
        self.grab_cancel_key()
        self.update_recording_status()
        self.record_timer.start(50)
        recorder.begin_recording()
        self.start_worker(Worker(recorder.new_recording_path(), settings.get(settings.MIC)))

    def start_worker(self, worker):
        self.worker = worker
        worker.stage.connect(self.on_stage)
        worker.finished.connect(self.on_finished)
        worker.start()

    def update_recording_status(self):
        if not self.is_recording:
            return
        seconds = self.elapsed.elapsed() // 1000
        if seconds >= MAX_SECONDS:
            self.stop_recording("Reached the 13-minute limit")
            return
        self.status.setText(f"Listening  {format_time(seconds)}")
        stop = f"Press {self.hotkey_label} or click to stop" if self.hotkey_registered else "Click to stop"
        self.hint.setText(f"{stop}. Esc cancels.")
        self.pill.set_time(format_time(seconds))
        if self.tray:
            self.tray.setToolTip(f"Maata: recording {format_time(seconds)}")
        # Loudness on a log scale (-55 dB to -10 dB) so normal speech moves the halo well.
        level = recorder.current_level
        value = 0.0
        if level > 0:
            db = 20 * math.log10(level)
            value = (db + 55) / 45
        self.record_button.set_level(value)
        self.pill.set_level(value)

    def stop_recording(self, hint=None):
        self.is_recording = False
        self.is_processing = True
        self.record_timer.stop()
        self.release_cancel_key()
        self.play_sound("stop")
        self.set_state("processing", hint=hint)
        self.pill.show_processing()
        try:
            recorder.stop_recording()
        except Exception:
            pass

    def cancel_recording(self):
        """Throw the recording away without transcribing it (Esc)."""
        if not self.is_recording:
            return
        self.worker.cancelled = True
        self.is_recording = False
        self.record_timer.stop()
        self.release_cancel_key()
        recorder.stop_recording()
        self.worker.wait(3000)  # let the mic close before anything else starts
        self.play_sound("cancel")
        self.pill.hide_pill()
        self.set_state("idle", "Cancelled")
        QTimer.singleShot(1500, lambda: self.is_idle() and self.status.text() == "Cancelled"
                          and self.set_state("idle"))

    def on_stage(self, stage):
        if self.is_processing:
            self.status.setText(stage)
            self.pill.show_processing(stage)

    def on_finished(self, text, error, can_retry, note):
        worker = self.sender()
        if worker is not None and worker.cancelled:
            return
        self.is_recording = False
        self.is_processing = False
        self.record_timer.stop()
        self.release_cancel_key()
        retried = worker is not None and not worker.record

        if error:
            if can_retry:
                if self.pending_file and self.pending_file != worker.filename:
                    recorder.delete_recording(self.pending_file)
                self.pending_file = worker.filename
            self.set_state("idle", "Couldn't transcribe" if can_retry else "Something went wrong")
            self.set_hint(error, error=True)
            self.pill.show_error("Couldn't transcribe. Click for details."
                                 if can_retry else "Something went wrong. Click for details.")
            return

        if retried:
            self.pending_file = None
        if settings.get_bool(settings.HISTORY):
            history.add(text)
        self.text_box.setPlainText(text)
        self.done_hint = (f"Skipped {round(worker.trimmed)} s of pauses, so it cost less."
                          if worker is not None and worker.trimmed >= 2 else None)
        self.set_state("idle", "Done", hint=self.done_hint)
        if note:
            self.set_hint(note, error=True)

        if retried:
            # The original window may be long gone, so copy instead of pasting.
            QApplication.clipboard().setText(text)
            if not note:
                self.set_hint("Copied to the clipboard. Press Ctrl+V where you want it.")
            self.pill.show_done("Copied to clipboard")
        elif self.checkbox.isChecked():
            self.pill.show_processing("Pasting")
            self.paste_worker = PasteWorker(text, self.target_hwnd)
            self.paste_worker.done.connect(lambda message: self.on_pasted(message, note))
            self.paste_worker.start()
        else:
            self.pill.show_done("Done. Text is in Maata")

    def on_pasted(self, message, note=""):
        if message.startswith("Pasted"):
            self.set_state("idle", "Pasted", hint=self.done_hint)
            if note:
                self.set_hint(note, error=True)
            self.pill.show_done("Pasted")
        else:
            self.set_hint(message, error=True)
            self.pill.show_error("Couldn't paste. Press Ctrl+V.")

    # ---- Saved recordings -------------------------------------------------

    def recover_unsent_recording(self):
        """Offer to retry a recording left over from last time (e.g. after a crash)."""
        files = recorder.unsent_recordings()
        for old in files[1:]:
            recorder.delete_recording(old)
        if files:
            self.pending_file = files[0]
            self.set_hint("A recording from last time wasn't transcribed.", error=True)
        self.update_retry_controls()

    def retry_recording(self):
        if not self.is_idle() or not self.pending_file:
            return
        if not os.path.exists(self.pending_file):
            self.pending_file = None
            self.update_retry_controls()
            return
        self.is_processing = True
        self.set_state("processing", hint="Trying again")
        self.pill.show_processing()
        self.start_worker(Worker(self.pending_file, record=False))

    def discard_recording(self):
        if not self.is_idle():
            return
        recorder.delete_recording(self.pending_file)
        self.pending_file = None
        self.set_state("idle", "Recording discarded")


SERVER_NAME = "Maata-" + re.sub(r"[^A-Za-z0-9_-]", "_", getpass.getuser())


def tell_running_copy_to_show():
    """If Maata is already running, ask it to show its window. Returns True if it was."""
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if not socket.waitForConnected(500):
        return False
    socket.write(b"show")
    socket.waitForBytesWritten(500)
    socket.disconnectFromServer()
    return True


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

    # Only one copy runs at a time; opening it again just brings up the window.
    if tell_running_copy_to_show():
        return
    server = QLocalServer()
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)

    window = MaataUI()
    app.setWindowIcon(window.icons["idle"])

    def on_connection():
        connection = server.nextPendingConnection()
        if connection:
            connection.disconnectFromServer()
        window.show_window()

    server.newConnection.connect(on_connection)
    window.show()
    app.exec_()


if __name__ == "__main__":
    launch_ui()
