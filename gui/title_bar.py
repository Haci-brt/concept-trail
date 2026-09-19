"""Custom frameless title bar: app name, breadcrumb, model status, window controls."""
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt

from gui.theme import TEXT_MUTED, TEXT_100


class TitleBar(QWidget):
    def __init__(self, window):
        super().__init__()
        self._window = window
        self.setObjectName("titleBar")
        self.setFixedHeight(44)
        self._drag_pos = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 8, 0)
        layout.setSpacing(8)

        icon = QLabel("📓")
        icon.setStyleSheet("font-size: 16px;")
        layout.addWidget(icon)

        app_name = QLabel("Fikir Not Defteri")
        app_name.setStyleSheet(f"font-weight: 600; color: {TEXT_100};")
        layout.addWidget(app_name)

        layout.addSpacing(16)

        self.breadcrumb = QLabel("")
        self.breadcrumb.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        layout.addWidget(self.breadcrumb)

        layout.addStretch(1)

        self.model_pill = QLabel("● LLM: kapalı")
        self.model_pill.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        layout.addWidget(self.model_pill)

        layout.addSpacing(14)

        min_btn = QPushButton("—")
        min_btn.setFixedSize(32, 28)
        min_btn.clicked.connect(window.showMinimized)
        layout.addWidget(min_btn)

        self.max_btn = QPushButton("▢")
        self.max_btn.setFixedSize(32, 28)
        self.max_btn.clicked.connect(self._toggle_max)
        layout.addWidget(self.max_btn)

        close_btn = QPushButton("✕")
        close_btn.setObjectName("closeButton")
        close_btn.setFixedSize(32, 28)
        close_btn.clicked.connect(window.close)
        layout.addWidget(close_btn)

    def set_breadcrumb(self, text: str):
        self.breadcrumb.setText(text)

    def set_model_status(self, up: bool):
        self.model_pill.setText("● LLM: localhost:8899" if up else "● LLM: kapalı")
        color = "#3fae5a" if up else TEXT_MUTED
        self.model_pill.setStyleSheet(f"color: {color}; font-size: 12px;")

    def _toggle_max(self):
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def mouseDoubleClickEvent(self, event):
        self._toggle_max()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self._window.pos()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._window.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
