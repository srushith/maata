from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout,
)

import settings
import theme
from hotkey import parse_hotkey
from recorder import list_microphones


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Maata Settings")
        self.setWindowFlags((self.windowFlags() | Qt.WindowStaysOnTopHint)
                            & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(460)

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(14)

        # OpenAI API key
        self.api_key = QLineEdit(settings.get(settings.API_KEY))
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("sk-...")
        form.addRow("OpenAI API key:", self.api_key)
        key_hint = QLabel(
            f'Get one at <a style="color:{theme.COLORS["accent"]}" '
            'href="https://platform.openai.com/api-keys">platform.openai.com/api-keys</a>. '
            "It's stored only on this PC.")
        key_hint.setObjectName("formHint")
        key_hint.setOpenExternalLinks(True)
        key_hint.setWordWrap(True)
        form.addRow("", key_hint)

        # Hotkey
        self.hotkey = QLineEdit(settings.get(settings.HOTKEY))
        self.hotkey.setPlaceholderText("e.g. win+alt+space")
        form.addRow("Hotkey:", self.hotkey)
        hint = QLabel("Modifiers: ctrl, alt, shift, win. Keys: a-z, 0-9, f1-f24, space.")
        hint.setObjectName("formHint")
        form.addRow("", hint)

        # Microphone
        self.mic = QComboBox()
        self.mic.addItem("System default", "")
        current_mic = settings.get(settings.MIC)
        mics = list_microphones()
        if current_mic and current_mic not in mics:
            mics.append(current_mic)  # keep the saved choice even if unplugged
        for name in mics:
            self.mic.addItem(name, name)
        self._select(self.mic, current_mic)
        form.addRow("Microphone:", self.mic)

        # Language
        self.language = QComboBox()
        for code, name in settings.LANGUAGES:
            self.language.addItem(name, code)
        self._select(self.language, settings.get(settings.LANGUAGE))
        form.addRow("Language:", self.language)

        # Model
        self.model = QComboBox()
        for model_id, description in settings.MODELS:
            self.model.addItem(description, model_id)
        self._select(self.model, settings.get(settings.MODEL))
        form.addRow("Model:", self.model)

        # Custom words
        self.vocabulary = QLineEdit(settings.get(settings.VOCABULARY))
        self.vocabulary.setPlaceholderText("e.g. Kubernetes, PyQt, Hyderabad")
        form.addRow("Custom words:", self.vocabulary)
        vocab_hint = QLabel("Names or terms to spell correctly, separated by commas.")
        vocab_hint.setObjectName("formHint")
        form.addRow("", vocab_hint)

        self.error = QLabel("")
        self.error.setObjectName("formError")
        self.error.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.addLayout(form)
        layout.addWidget(self.error)
        layout.addWidget(buttons)

    def showEvent(self, event):
        super().showEvent(event)
        theme.apply_title_bar(self)

    @staticmethod
    def _select(combo, value):
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def validate_and_accept(self):
        key = self.api_key.text().strip()
        if key and not key.startswith("sk-"):
            self.error.setText("That doesn't look like an OpenAI API key. Keys start with \"sk-\".")
            return
        try:
            parse_hotkey(self.hotkey.text())
        except ValueError as e:
            self.error.setText(f"Hotkey: {e}")
            return
        self.accept()

    def values(self):
        return {
            settings.API_KEY: self.api_key.text().strip(),
            settings.HOTKEY: self.hotkey.text().strip().lower(),
            settings.MIC: self.mic.currentData(),
            settings.LANGUAGE: self.language.currentData(),
            settings.MODEL: self.model.currentData(),
            settings.VOCABULARY: self.vocabulary.text().strip(),
        }
