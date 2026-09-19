"""Formatting toolbar above the editor: wraps/inserts markdown syntax around
the current selection, plus a sparkle button to ask the assistant right now."""
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QTextCursor


class EditorToolbar(QWidget):
    ask_now_requested = pyqtSignal()

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setObjectName("editorToolbar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self._add_button(layout, "B", lambda: self._wrap("**", "**"))
        self._add_button(layout, "I", lambda: self._wrap("*", "*"))
        self._add_button(layout, "H1", lambda: self._prefix_line("# "))
        self._add_button(layout, "H2", lambda: self._prefix_line("## "))
        self._add_button(layout, "•", lambda: self._prefix_line("- "))
        self._add_button(layout, "1.", lambda: self._prefix_line("1. "))
        self._add_button(layout, "🔗", lambda: self._wrap("[", "](url)"))
        self._add_button(layout, "`", lambda: self._wrap("`", "`"))
        layout.addStretch(1)

        sparkle = self._add_button(layout, "✨", self.ask_now_requested.emit)
        sparkle.setObjectName("sparkleButton")
        sparkle.setToolTip("Asistana şimdi sor")

    def _add_button(self, layout, label: str, handler) -> QPushButton:
        btn = QPushButton(label)
        btn.clicked.connect(handler)
        layout.addWidget(btn)
        return btn

    def _wrap(self, before: str, after: str):
        cursor = self.editor.textCursor()
        selected = cursor.selectedText()
        cursor.insertText(f"{before}{selected}{after}")
        if not selected:
            cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, len(after))
            self.editor.setTextCursor(cursor)

    def _prefix_line(self, prefix: str):
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
        cursor.insertText(prefix)
