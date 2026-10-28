from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

import history
import theme

PREVIEW_CHARS = 220


class HistoryDialog(QDialog):
    """The last 10 transcripts, with a Copy button for each."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Maata History")
        self.setWindowFlags((self.windowFlags() | Qt.WindowStaysOnTopHint)
                            & ~Qt.WindowContextHelpButtonHint)
        self.resize(440, 520)

        self.list = QVBoxLayout()
        self.list.setSpacing(8)
        holder = QWidget()
        holder.setObjectName("historyList")
        holder.setLayout(self.list)
        scroll = QScrollArea()
        scroll.setObjectName("historyScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(holder)

        note = QLabel(f"Your last {history.MAX_ITEMS} transcripts, saved only on this PC.")
        note.setObjectName("formHint")

        self.clear_button = QPushButton("Clear history")
        self.clear_button.setObjectName("ghost")
        self.clear_button.setCursor(Qt.PointingHandCursor)
        self.clear_button.clicked.connect(self.clear)
        close_button = QPushButton("Close")
        close_button.setObjectName("primary")
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.clicked.connect(self.accept)

        footer = QHBoxLayout()
        footer.addWidget(self.clear_button)
        footer.addStretch()
        footer.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.addWidget(note)
        layout.addSpacing(6)
        layout.addWidget(scroll, stretch=1)
        layout.addSpacing(8)
        layout.addLayout(footer)
        self.fill()

    def showEvent(self, event):
        super().showEvent(event)
        theme.apply_title_bar(self)

    def fill(self):
        while self.list.count():
            item = self.list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        items = history.load()
        if not items:
            empty = QLabel("Nothing here yet. Your transcripts will appear here.")
            empty.setObjectName("hint")
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            self.list.addSpacing(40)
            self.list.addWidget(empty)
        for entry in items:
            self.list.addWidget(self.make_card(entry))
        self.list.addStretch()
        self.clear_button.setEnabled(bool(items))

    def make_card(self, entry):
        card = QFrame()
        card.setObjectName("card")
        text = entry["text"]
        preview = text if len(text) <= PREVIEW_CHARS else text[:PREVIEW_CHARS].rstrip() + "…"

        when = QLabel(entry.get("time", ""))
        when.setObjectName("count")
        words = len(text.split())
        count = QLabel(f"{words} word{'s' if words != 1 else ''}")
        count.setObjectName("count")
        body = QLabel(preview)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setToolTip(text if len(text) > PREVIEW_CHARS else "")

        copy = QPushButton("Copy")
        copy.setObjectName("ghost")
        copy.setCursor(Qt.PointingHandCursor)
        copy.clicked.connect(lambda: self.copy(text, copy))

        top = QHBoxLayout()
        top.addWidget(when)
        top.addStretch()
        top.addWidget(count)
        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(copy)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 8, 4)
        layout.setSpacing(4)
        layout.addLayout(top)
        layout.addWidget(body)
        layout.addLayout(bottom)
        return card

    def copy(self, text, button):
        QApplication.clipboard().setText(text)
        button.setText("Copied ✓")
        QTimer.singleShot(1500, lambda: button.setText("Copy"))

    def clear(self):
        history.clear()
        self.fill()
