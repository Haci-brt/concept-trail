"""Bottom status bar: cursor position, word count, save state, model status."""
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QSizeGrip


class StatusBar(QWidget):
    def __init__(self, version: str = "v0.1.0"):
        super().__init__()
        self.setObjectName("statusBar")
        self.setFixedHeight(28)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)

        self.position_label = self._label("Satır 1, Sütun 1")
        layout.addWidget(self.position_label)

        self.word_count_label = self._label("0 kelime")
        layout.addWidget(self.word_count_label)

        self.format_label = self._label("Markdown")
        layout.addWidget(self.format_label)

        layout.addStretch(1)

        self.saved_label = self._label("")
        layout.addWidget(self.saved_label)

        layout.addStretch(1)

        self.model_label = self._label("Model kapalı")
        layout.addWidget(self.model_label)

        self.version_label = self._label(version)
        layout.addWidget(self.version_label)

        layout.addWidget(QSizeGrip(self))

    def _label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("statusBarLabel")
        return label

    def set_cursor(self, line: int, col: int):
        self.position_label.setText(f"Satır {line}, Sütun {col}")

    def set_word_count(self, words: int):
        self.word_count_label.setText(f"{words} kelime")

    def set_saved(self, text: str):
        self.saved_label.setText(text)

    def set_model_status(self, up: bool):
        self.model_label.setText("● Model hazır" if up else "Model kapalı")
        self.model_label.setStyleSheet(
            f"color: {'#3fae5a' if up else '#8a8a8a'}; font-size: 11px; background: transparent;"
        )
