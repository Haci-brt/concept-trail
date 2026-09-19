"""Side panel listing every assistant event — questions, edit suggestions,
and resolutions — including ones already dismissed in the HUD."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QComboBox
)
from PyQt6.QtCore import QSize

from core.state import state
from core.categorize import icon_and_label

ALL_LABEL = "Tümü"


def _subtitle_for(event: dict) -> str:
    if event.get("type") == "edit":
        return f'"{event["original"]}" → "{event["replacement"]}"'
    return event.get("text", "")


class HistoryPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("sidebar")
        self.setFixedWidth(260)
        self._entries = []  # (icon, label, event)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 8)

        header = QHBoxLayout()
        title = QLabel("ÖNERİ GEÇMİŞİ")
        title.setObjectName("sidebarTitle")
        header.addWidget(title)
        header.addStretch(1)

        self.filter_combo = QComboBox()
        self.filter_combo.addItem(ALL_LABEL)
        self.filter_combo.currentTextChanged.connect(self._refresh_list)
        header.addWidget(self.filter_combo)
        layout.addLayout(header)

        self.list_widget = QListWidget()
        self.list_widget.setSpacing(2)
        layout.addWidget(self.list_widget, 1)

        state.history_entry_added.connect(self._on_entry)

    def _on_entry(self, event: dict):
        icon, label = icon_and_label(event)
        self._entries.insert(0, (icon, label, event))

        if self.filter_combo.findText(label) == -1:
            self.filter_combo.addItem(label)

        self._refresh_list()

    def _refresh_list(self, *_):
        selected = self.filter_combo.currentText() or ALL_LABEL
        self.list_widget.clear()
        for icon, label, event in self._entries:
            if selected != ALL_LABEL and selected != label:
                continue
            self._add_item(icon, label, event)

    def _add_item(self, icon: str, label: str, event: dict):
        card = QWidget()
        card.setObjectName("historyCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(6, 6, 6, 6)
        card_layout.setSpacing(2)

        top_row = QHBoxLayout()
        icon_label = QLabel(icon)
        icon_label.setStyleSheet("background: transparent; font-size: 14px;")
        top_row.addWidget(icon_label)

        title_label = QLabel(label)
        title_label.setObjectName("historyTitle")
        top_row.addWidget(title_label)
        top_row.addStretch(1)

        time_label = QLabel(event.get("timestamp", ""))
        time_label.setObjectName("historyTime")
        top_row.addWidget(time_label)
        card_layout.addLayout(top_row)

        text = _subtitle_for(event)
        subtitle = QLabel(text if len(text) <= 90 else text[:87] + "...")
        subtitle.setObjectName("historySubtitle")
        subtitle.setWordWrap(True)
        card_layout.addWidget(subtitle)

        item = QListWidgetItem()
        item.setSizeHint(card.sizeHint() + QSize(0, 6))
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, card)
