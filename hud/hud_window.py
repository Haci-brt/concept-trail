"""Always-on-top, frameless HUD overlay.

Shows nothing most of the time. When the assistant has a question or an
edit suggestion, a small card fades in here so it doesn't interrupt typing
in the notebook window. Questions can be discussed in a chat window; edits
need an explicit approval before they touch the note.
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, QTimer

from core.state import state
from gui.theme import TEXT_MUTED


class HudWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(300)
        self._current_event: dict | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.card = QWidget()
        self.card.setObjectName("hudCard")
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        outer.addWidget(self.card)

        self.status_label = QLabel("Model: kapalı")
        self.status_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; background: transparent;")
        layout.addWidget(self.status_label)

        self.thinking_label = QLabel("")
        self.thinking_label.setWordWrap(True)
        self.thinking_label.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 11px; font-style: italic; background: transparent;"
        )
        self.thinking_label.hide()
        layout.addWidget(self.thinking_label)

        self.title_label = QLabel("")
        self.title_label.setObjectName("hudTitle")
        self.title_label.hide()
        layout.addWidget(self.title_label)

        self.body_label = QLabel("")
        self.body_label.setObjectName("hudBody")
        self.body_label.setWordWrap(True)
        self.body_label.hide()
        layout.addWidget(self.body_label)

        self.button_row = QHBoxLayout()
        layout.addLayout(self.button_row)

        state.model_status_changed.connect(self._on_model_status)
        state.thinking_changed.connect(self._on_thinking)
        state.thinking_text_changed.connect(self._on_thinking_text)
        state.event_ready.connect(self._on_event)
        state.flash_message.connect(self._on_flash)

        self._drag_pos = None
        self.adjustSize()
        self._move_to_corner()

    def _move_to_corner(self):
        screen = self.screen().availableGeometry()
        self.move(screen.right() - self.width() - 20, screen.top() + 130)

    def _on_model_status(self, up: bool):
        self.status_label.setText("Model: çalışıyor ✓" if up else "Model: kapalı")

    def _on_thinking(self, thinking: bool):
        if thinking:
            self.status_label.setText("Model: düşünüyor...")
            self.show()
            self.raise_()
        else:
            self.status_label.setText("Model: çalışıyor ✓" if state.model_up else "Model: kapalı")

    def _on_thinking_text(self, text: str):
        if text:
            self.thinking_label.setText(text)
            self.thinking_label.show()
        else:
            self.thinking_label.hide()
        self.adjustSize()
        self._move_to_corner()

    def _on_flash(self, title: str, body: str):
        # only takes over the card if nothing else is currently being shown —
        # a real question/edit event always wins
        if self._current_event is not None:
            return
        self.title_label.setText(f"👁️ {title}")
        self.title_label.show()
        self.body_label.setText(body)
        self.body_label.show()
        self._clear_buttons()
        self.adjustSize()
        self._move_to_corner()
        self.show()
        self.raise_()
        QTimer.singleShot(4000, self._clear_flash)

    def _clear_flash(self):
        if self._current_event is not None:
            return  # a real event took over in the meantime, leave it showing
        self.title_label.hide()
        self.body_label.hide()
        self.adjustSize()
        self._move_to_corner()

    def _clear_buttons(self):
        while self.button_row.count():
            item = self.button_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _on_event(self, event: dict):
        self._current_event = event
        self._clear_buttons()
        event_type = event.get("type")

        if event_type == "question":
            self.title_label.setText("✨ Küçük bir soru ✨")
            self.body_label.setText(event["text"])
            chat_btn = QPushButton("💬 Sohbet Et")
            chat_btn.clicked.connect(self._open_chat)
            self.button_row.addWidget(chat_btn)
            self.button_row.addStretch(1)
            if state.has_more_events():
                next_btn = QPushButton("Sonrakini Göster")
                next_btn.clicked.connect(self._show_next)
                self.button_row.addWidget(next_btn)
            dismiss_btn = QPushButton("Kapat")
            dismiss_btn.clicked.connect(self._dismiss)
            self.button_row.addWidget(dismiss_btn)

        elif event_type == "edit":
            self.title_label.setText("✏️ Düzenleme Önerisi")
            reason = f"\n{event['reason']}" if event.get("reason") else ""
            self.body_label.setText(f'"{event["original"]}"  →  "{event["replacement"]}"{reason}')
            approve_btn = QPushButton("Onayla")
            approve_btn.setObjectName("accentButton")
            approve_btn.clicked.connect(self._approve_edit)
            self.button_row.addWidget(approve_btn)
            self.button_row.addStretch(1)
            if state.has_more_events():
                next_btn = QPushButton("Sonrakini Göster")
                next_btn.clicked.connect(self._show_next)
                self.button_row.addWidget(next_btn)
            reject_btn = QPushButton("Reddet")
            reject_btn.clicked.connect(self._reject_edit)
            self.button_row.addWidget(reject_btn)

        self.title_label.show()
        self.body_label.show()
        self.adjustSize()
        self._move_to_corner()
        self.show()
        self.raise_()

    def _open_chat(self):
        if self._current_event:
            self._current_event["note_tab"].open_chat(
                self._current_event["text"], self._current_event.get("node_id")
            )
        self._advance()

    def _approve_edit(self):
        event = self._current_event
        if event:
            event["note_tab"].apply_edit(event["original"], event["replacement"])
        self._advance()

    def _reject_edit(self):
        self._advance()

    def _show_next(self):
        state.next_event()

    def _advance(self):
        """Consume the current event and either show the next queued one or hide."""
        if state.has_more_events():
            state.next_event()
        else:
            self._dismiss()

    def _dismiss(self):
        state.clear_events()
        self._current_event = None
        self.title_label.hide()
        self.body_label.hide()
        self._clear_buttons()
        self.adjustSize()
        self._move_to_corner()

    # Allow dragging the frameless window with the mouse.
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
