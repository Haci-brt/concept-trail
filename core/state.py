"""Shared state bus between the GUI and the HUD.

Everything here runs in-process (single QApplication) — Qt signals only,
nothing leaves the machine.

Assistant activity flows through typed event dicts:
    {"type": "question", "text": ..., "note_name": ..., "timestamp": ..., "note_tab": NoteTab}
    {"type": "edit", "original": ..., "replacement": ..., "reason": ..., ...}
    {"type": "resolved", "text": ..., ...}
"""
from PyQt6.QtCore import QObject, pyqtSignal


class AppState(QObject):
    model_status_changed = pyqtSignal(bool)     # True = server up
    thinking_changed = pyqtSignal(bool)          # True = analysis in flight
    thinking_text_changed = pyqtSignal(str)      # live preview of the model's <think> block
    event_ready = pyqtSignal(dict)               # shown in the HUD, one at a time
    history_entry_added = pyqtSignal(dict)       # every event, logged in the history panel
    flash_message = pyqtSignal(str, str)         # (title, body) brief transient status

    def __init__(self):
        super().__init__()
        self.model_up = False
        self.thinking = False
        self._pending_events: list[dict] = []

    def set_model_up(self, up: bool):
        self.model_up = up
        self.model_status_changed.emit(up)

    def set_thinking(self, thinking: bool):
        self.thinking = thinking
        self.thinking_changed.emit(thinking)
        if not thinking:
            self.thinking_text_changed.emit("")

    def set_thinking_text(self, text: str):
        self.thinking_text_changed.emit(text)

    def show_flash(self, title: str, body: str):
        self.flash_message.emit(title, body)

    def push_event(self, event: dict):
        self.history_entry_added.emit(event)
        if event.get("type") in ("resolved", "checked"):
            return  # logged in history only — nothing to act on in the HUD
        was_empty = not self._pending_events
        self._pending_events.append(event)
        if was_empty:
            self.event_ready.emit(event)

    def next_event(self):
        """Pop the just-shown event and emit the next queued one, if any."""
        if self._pending_events:
            self._pending_events.pop(0)
        if self._pending_events:
            nxt = self._pending_events[0]
            self.event_ready.emit(nxt)
            return nxt
        return None

    def has_more_events(self) -> bool:
        return len(self._pending_events) > 1

    def clear_events(self):
        self._pending_events.clear()


state = AppState()
