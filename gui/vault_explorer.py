"""Left sidebar: Obsidian-style file tree over the notes vault, plus a
tag cloud computed from '#tag' occurrences across all notes."""
import re
from collections import Counter
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeView, QPushButton, QGridLayout
)
from PyQt6.QtGui import QFileSystemModel
from PyQt6.QtCore import pyqtSignal, QDir

TAG_PATTERN = re.compile(r"#([A-Za-zÇĞİÖŞÜçğıöşü0-9_-]{2,})")
MAX_TAGS = 8


class VaultExplorer(QWidget):
    file_opened = pyqtSignal(Path)
    search_requested = pyqtSignal()
    new_note_requested = pyqtSignal()

    def __init__(self, vault_dir: Path):
        super().__init__()
        self.vault_dir = vault_dir
        self.setObjectName("sidebar")
        self.setFixedWidth(230)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(8)

        icon_bar = QWidget()
        icon_bar.setObjectName("iconBar")
        icon_row = QHBoxLayout(icon_bar)
        icon_row.setContentsMargins(0, 0, 0, 0)
        folder_btn = QPushButton("📁")
        folder_btn.setToolTip("Vault'ı yenile")
        folder_btn.clicked.connect(self.refresh)
        search_btn = QPushButton("🔍")
        search_btn.setToolTip("Not ara (Ctrl+P)")
        search_btn.clicked.connect(self.search_requested.emit)
        new_btn = QPushButton("➕")
        new_btn.setToolTip("Yeni not")
        new_btn.clicked.connect(self.new_note_requested.emit)
        for b in (folder_btn, search_btn, new_btn):
            icon_row.addWidget(b)
        icon_row.addStretch(1)
        layout.addWidget(icon_bar)

        title = QLabel("VAULT")
        title.setObjectName("sidebarTitle")
        layout.addWidget(title)

        self.model = QFileSystemModel()
        self.model.setRootPath(str(vault_dir))
        self.model.setNameFilters(["*.md"])
        self.model.setNameFilterDisables(False)
        self.model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)

        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(str(vault_dir)))
        self.tree.setHeaderHidden(True)
        for col in (1, 2, 3):
            self.tree.hideColumn(col)
        self.tree.doubleClicked.connect(self._on_double_click)
        layout.addWidget(self.tree, 1)

        tags_title = QLabel("ETİKETLER")
        tags_title.setObjectName("sidebarTitle")
        layout.addWidget(tags_title)

        self.tags_container = QWidget()
        self.tags_layout = QGridLayout(self.tags_container)
        self.tags_layout.setContentsMargins(0, 0, 0, 0)
        self.tags_layout.setSpacing(4)
        layout.addWidget(self.tags_container)

        brand = QWidget()
        brand.setObjectName("brandCard")
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(10, 8, 10, 8)
        brand_title = QLabel("Fikir Not Defteri")
        brand_title.setObjectName("brandTitle")
        brand_layout.addWidget(brand_title)
        brand_subtitle = QLabel("Yerel. Güvenli. Sadece seninle.")
        brand_subtitle.setObjectName("brandSubtitle")
        brand_subtitle.setWordWrap(True)
        brand_layout.addWidget(brand_subtitle)
        layout.addWidget(brand)

        self.refresh_tags()

    def _on_double_click(self, index):
        path = Path(self.model.filePath(index))
        if path.is_file():
            self.file_opened.emit(path)

    def refresh(self):
        self.model.setRootPath("")
        self.model.setRootPath(str(self.vault_dir))
        self.refresh_tags()

    def refresh_tags(self):
        while self.tags_layout.count():
            item = self.tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        counts = Counter()
        for path in self.vault_dir.rglob("*.md"):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            counts.update(TAG_PATTERN.findall(text))

        row, col = 0, 0
        for tag, count in counts.most_common(MAX_TAGS):
            pill = QPushButton(f"#{tag}  {count}")
            pill.setObjectName("tagPill")
            pill.setFlat(True)
            self.tags_layout.addWidget(pill, row, col)
            col += 1
            if col >= 2:
                col = 0
                row += 1
