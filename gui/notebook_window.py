"""Main window: Obsidian-style vault explorer + multi-tab notebook + local
model live assistant, wrapped in a custom frameless title bar.

Each tab is a NoteTab (its own editor + file). Only the currently active
tab runs the live-monitoring loop against the local model. A shared
history panel on the right logs every suggestion across all notes.
"""
import subprocess
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QTabBar, QPushButton,
    QComboBox, QMessageBox, QInputDialog
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QShortcut, QKeySequence

from core.state import state
from core.workers import HealthCheckWorker
from gui.note_tab import NoteTab
from gui.history_panel import HistoryPanel
from gui.vault_explorer import VaultExplorer
from gui.quick_switcher import QuickSwitcher
from gui.title_bar import TitleBar
from gui.status_bar import StatusBar
from gui.tree_view import TreeViewPanel

NOTES_DIR = Path.home() / "project-assistant" / "notes"

LAUNCH_SCRIPTS = {
    # "Qwen3.8 dense" removed 2026-09-17: its binary AND model file are both
    # gone from disk (see project_qwen38_opt memory) — it was a dead button
    # that only errored on click. Re-add once it points at a real model.
    "Qwen3.8 Flash-Next (~19-23 tok/s)": Path.home() / "qwen38-opt" / "run_flashnext.sh",
}


class NotebookWindow(QWidget):
    def __init__(self, hud):
        super().__init__()
        self.hud = hud
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setObjectName("mainRoot")
        self.setMinimumSize(860, 540)
        self.resize(1280, 720)
        self._center_on_screen()

        NOTES_DIR.mkdir(parents=True, exist_ok=True)
        self._health_worker: HealthCheckWorker | None = None
        self._new_note_count = 0
        self.tree_panel = None  # created below, after the first note tab exists

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.title_bar = TitleBar(self)
        outer.addWidget(self.title_bar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)

        # ---- far left: vault explorer ----
        self.vault_explorer = VaultExplorer(NOTES_DIR)
        self.vault_explorer.file_opened.connect(self._open_path)
        self.vault_explorer.search_requested.connect(self._show_quick_switcher)
        self.vault_explorer.new_note_requested.connect(self._new_note)
        body.addWidget(self.vault_explorer)

        # ---- center: model bar + tabs ----
        center = QVBoxLayout()
        center.setContentsMargins(8, 6, 8, 0)

        model_row = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.addItems(LAUNCH_SCRIPTS.keys())
        model_row.addWidget(self.model_combo)
        launch_btn = QPushButton("Modeli Başlat")
        launch_btn.clicked.connect(self._launch_model)
        model_row.addWidget(launch_btn)
        model_row.addStretch(1)
        save_btn = QPushButton("Kaydet  (Ctrl+S)")
        save_btn.clicked.connect(self._save_current)
        model_row.addWidget(save_btn)
        center.addLayout(model_row)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._on_current_changed)
        center.addWidget(self.tabs, 1)

        body.addLayout(center, 1)

        # ---- right: history panel ----
        self.history_panel = HistoryPanel()
        body.addWidget(self.history_panel)

        self.status_bar = StatusBar()
        outer.addWidget(self.status_bar)

        QShortcut(QKeySequence("Ctrl+P"), self, self._show_quick_switcher)
        QShortcut(QKeySequence("Ctrl+S"), self, self._save_current)
        QShortcut(QKeySequence("Ctrl+N"), self, self._new_note)

        # ---- periodic health check ----
        self.health_timer = QTimer(self)
        self.health_timer.timeout.connect(self._check_health)
        self.health_timer.start(15000)
        self._check_health()

        self._add_tab()

        self.tree_panel = TreeViewPanel()
        tree_index = self.tabs.addTab(self.tree_panel, "🌳 Ağaç Görünümü")
        self.tabs.tabBar().setTabButton(tree_index, QTabBar.ButtonPosition.RightSide, None)
        self._on_current_changed(self.tabs.currentIndex())  # bind the tree panel now that it exists

    def _center_on_screen(self):
        screen = self.screen().availableGeometry()
        w = min(self.width(), screen.width() - 40)
        h = min(self.height(), screen.height() - 40)
        if (w, h) != (self.width(), self.height()):
            self.resize(w, h)
        self.move(screen.x() + 20, screen.y() + 20)

    # ---- tabs ----
    def _add_tab(self, file_path: Path | None = None):
        if file_path is not None:
            existing = self._find_open_tab(file_path)
            if existing is not None:
                self.tabs.setCurrentWidget(existing)
                return existing

        self._new_note_count += 1
        label = file_path.stem if file_path else f"Not {self._new_note_count}"
        tab = NoteTab(NOTES_DIR, file_path=file_path, tab_label=label)
        tab.word_count_changed.connect(self.status_bar.set_word_count)
        tab.cursor_moved.connect(self.status_bar.set_cursor)
        tab.saved.connect(lambda ts: self.status_bar.set_saved(f"Son kaydedilme: {ts}"))
        index = self.tabs.addTab(tab, label)
        self.tabs.setCurrentIndex(index)
        return tab

    def _find_open_tab(self, file_path: Path) -> NoteTab | None:
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, NoteTab) and w.current_file == file_path:
                return w
        return None

    def _close_tab(self, index: int):
        widget = self.tabs.widget(index)
        if widget is self.tree_panel:
            return  # the tree view tab has no close button, but guard anyway
        if isinstance(widget, NoteTab):
            widget.stop_live()
        self.tabs.removeTab(index)
        remaining_notes = any(isinstance(self.tabs.widget(i), NoteTab) for i in range(self.tabs.count()))
        if not remaining_notes:
            self._add_tab()

    def _on_current_changed(self, index: int):
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, NoteTab):
                w.stop_live()
                w._tree_panel = None
        current = self.tabs.widget(index)
        if isinstance(current, NoteTab):
            current.start_live()
            self.title_bar.set_breadcrumb(current.breadcrumb())
            self.status_bar.set_word_count(len(current.editor.toPlainText().split()))
            if self.tree_panel is not None:
                current._tree_panel = self.tree_panel
                self.tree_panel.reset_and_load(current.display_name(), current.tree_nodes)

    def _current_tab(self) -> NoteTab | None:
        w = self.tabs.currentWidget()
        return w if isinstance(w, NoteTab) else None

    # ---- model server ----
    def _launch_model(self):
        script = LAUNCH_SCRIPTS[self.model_combo.currentText()]
        if not script.exists():
            QMessageBox.warning(self, "Bulunamadı", f"Script yok: {script}")
            return
        subprocess.Popen(
            ["bash", str(script)],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        QTimer.singleShot(3000, self._check_health)

    def _check_health(self):
        self._health_worker = HealthCheckWorker()
        self._health_worker.status_ready.connect(self._on_health_result)
        self._health_worker.start()

    def _on_health_result(self, up: bool):
        state.set_model_up(up)
        self.title_bar.set_model_status(up)
        self.status_bar.set_model_status(up)

    # ---- note files ----
    def _open_path(self, path: Path):
        self._add_tab(file_path=path)

    def _new_note(self):
        name, ok = QInputDialog.getText(self, "Yeni not", "Not adı:")
        if not ok or not name.strip():
            return
        path = NOTES_DIR / f"{name.strip()}.md"
        if path.exists():
            QMessageBox.warning(self, "Zaten var", f"'{name}' zaten mevcut.")
            self._add_tab(file_path=path)
            return
        path.write_text("", encoding="utf-8")
        self.vault_explorer.refresh()
        self._add_tab(file_path=path)

    def _show_quick_switcher(self):
        switcher = QuickSwitcher(NOTES_DIR, self)
        if switcher.exec() and switcher.chosen is not None:
            self._add_tab(file_path=switcher.chosen)

    def _save_current(self):
        tab = self._current_tab()
        if tab is None:
            return
        if tab.current_file is None:
            name, ok = QInputDialog.getText(self, "Notu kaydet", "Dosya adı:")
            if not ok or not name.strip():
                return
            path = NOTES_DIR / f"{name.strip()}.md"
            saved = tab.save(path)
        else:
            saved = tab.save()
        self.tabs.setTabText(self.tabs.currentIndex(), saved.stem)
        self.title_bar.set_breadcrumb(tab.breadcrumb())
        self.vault_explorer.refresh()
