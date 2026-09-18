"""Ctrl+P style quick switcher: type to filter notes, Enter to open."""
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QLabel, QWidget
)
from PyQt6.QtCore import Qt, QSize


class QuickSwitcher(QDialog):
    def __init__(self, vault_dir: Path, parent=None):
        super().__init__(parent)
        self.vault_dir = vault_dir
        self.setWindowTitle("Not ara")
        self.setFixedSize(460, 400)
        self.setWindowFlags(Qt.WindowType.Popup)

        self._all_files = sorted(vault_dir.rglob("*.md"))
        self.chosen: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 0)
        layout.setSpacing(6)

        search_row = QHBoxLayout()
        search_icon = QLabel("🔍")
        search_row.addWidget(search_icon)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Not ara... (Ctrl+P)")
        self.search_box.textChanged.connect(self._filter)
        search_row.addWidget(self.search_box, 1)
        layout.addLayout(search_row)

        self.list_widget = QListWidget()
        self.list_widget.itemActivated.connect(self._choose)
        layout.addWidget(self.list_widget, 1)

        footer = QWidget()
        footer.setObjectName("switcherFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(8, 4, 8, 4)
        for hint in ("↑↓ Gezin", "Enter Aç", "Esc Kapat"):
            lbl = QLabel(hint)
            lbl.setObjectName("switcherHint")
            footer_layout.addWidget(lbl)
        footer_layout.addStretch(1)
        layout.addWidget(footer)

        self._filter("")
        self.search_box.setFocus()

    def _filter(self, text: str):
        self.list_widget.clear()
        needle = text.lower()
        for path in self._all_files:
            if needle in path.stem.lower():
                self._add_item(path)
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def _add_item(self, path: Path):
        try:
            rel_folder = path.relative_to(self.vault_dir).parent.as_posix()
        except ValueError:
            rel_folder = ""
        subtitle = f"{rel_folder} / {path.name}" if rel_folder not in ("", ".") else path.name

        card = QWidget()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(6, 4, 6, 4)
        card_layout.setSpacing(0)
        name_label = QLabel(path.stem)
        name_label.setObjectName("historyTitle")
        card_layout.addWidget(name_label)
        path_label = QLabel(subtitle)
        path_label.setObjectName("historySubtitle")
        card_layout.addWidget(path_label)

        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setSizeHint(card.sizeHint() + QSize(0, 4))
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, card)

    def _choose(self, item: QListWidgetItem):
        self.chosen = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Return and self.list_widget.currentItem():
            self._choose(self.list_widget.currentItem())
        elif event.key() == Qt.Key.Key_Escape:
            self.reject()
        elif event.key() == Qt.Key.Key_Down:
            self.list_widget.setCurrentRow(min(self.list_widget.currentRow() + 1, self.list_widget.count() - 1))
        elif event.key() == Qt.Key.Key_Up:
            self.list_widget.setCurrentRow(max(self.list_widget.currentRow() - 1, 0))
        else:
            super().keyPressEvent(event)
