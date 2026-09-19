"""One note tab: markdown editor + live preview + background monitoring.

The assistant only looks at the note once you actually pause writing for
IDLE_MS — every keystroke restarts the countdown, so it never reacts to a
sentence still being typed. When it does look, it always gets the whole
note (not just the newest fragment), so it judges the writing as a whole
rather than reacting to isolated snippets. Only the active tab runs this
loop — start_live()/stop_live() are called by the parent window on tab
switch, so we never fire two LLM calls at once.
"""
import json
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTextEdit, QTextBrowser,
    QLabel, QPushButton
)
from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QTextCursor, QTextCharFormat, QColor, QTextDocument, QFont

from core.state import state
from core.workers import AnalyzeWorker
from gui.markdown_highlighter import MarkdownHighlighter
from gui.editor_toolbar import EditorToolbar
from gui.theme import ACCENT

IDLE_MS = 6000
MIN_NEW_CHARS = 40
HIGHLIGHT_MS = 6000
PREVIEW_DEBOUNCE_MS = 400
THINKING_THROTTLE_MS = 500


class NoteTab(QWidget):
    cursor_moved = pyqtSignal(int, int)   # (line, column)
    word_count_changed = pyqtSignal(int)
    saved = pyqtSignal(str)               # human-readable "az önce" style text

    def __init__(self, notes_dir: Path, file_path: Path | None = None, tab_label: str = "Yeni Not"):
        super().__init__()
        self.notes_dir = notes_dir
        self.current_file = file_path
        self._tab_label = tab_label

        self._last_len = 0
        self._analyzing = False
        self._last_shown_question = ""
        self.open_questions: list[str] = []
        self.open_question_ids: list[str] = []
        self._worker: AnalyzeWorker | None = None
        self._chat_dialogs = []  # keep references alive while open
        self._pending_thinking_text: str | None = None

        # growing-tree view: every question/edit/chat message becomes a node,
        # kept here so switching away from this tab and back replays the same
        # tree instead of losing it. self._tree_panel is only set (by the
        # parent window) while this tab is the one currently on screen.
        self.tree_nodes: list[dict] = []
        self._tree_panel = None
        self._node_counter = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 4)
        layout.setSpacing(4)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        # ---- left: toolbar + editor ----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(2)

        self.editor = QTextEdit()
        self.editor.setPlaceholderText(
            "Proje fikrini buraya yaz (markdown desteklenir: # başlık, **kalın**, - liste). "
            "Asistan arka planda sürekli izliyor; yeni bir şey fark ederse HUD'da kısa "
            "bir soru/öneri gösterir."
        )
        self.editor.setFont(self._editor_font())
        self.highlighter = MarkdownHighlighter(self.editor.document())
        self.editor.textChanged.connect(self._on_text_changed)
        self.editor.cursorPositionChanged.connect(self._on_cursor_moved)

        self.toolbar = EditorToolbar(self.editor)
        self.toolbar.ask_now_requested.connect(self._ask_now)
        left_layout.addWidget(self.toolbar)
        left_layout.addWidget(self.editor, 1)
        self.splitter.addWidget(left)

        # ---- right: pane-tab header + preview/source ----
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(2)

        pane_tabs = QHBoxLayout()
        pane_tabs.setContentsMargins(6, 2, 6, 2)
        self.preview_tab_btn = QPushButton("Önizleme")
        self.preview_tab_btn.setObjectName("paneTab")
        self.preview_tab_btn.setCheckable(True)
        self.preview_tab_btn.setChecked(True)
        self.source_tab_btn = QPushButton("Kaynak")
        self.source_tab_btn.setObjectName("paneTab")
        self.source_tab_btn.setCheckable(True)
        self.preview_tab_btn.clicked.connect(lambda: self._set_pane_mode(True))
        self.source_tab_btn.clicked.connect(lambda: self._set_pane_mode(False))
        pane_tabs.addWidget(self.preview_tab_btn)
        pane_tabs.addWidget(self.source_tab_btn)
        pane_tabs.addStretch(1)
        right_layout.addLayout(pane_tabs)

        self.preview = QTextBrowser()
        self.preview.setMinimumWidth(150)
        right_layout.addWidget(self.preview, 1)
        self.editor.setMinimumWidth(150)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)

        layout.addWidget(self.splitter, 1)

        bottom_row = QHBoxLayout()
        self.live_indicator = QLabel("● izleniyor")
        self.live_indicator.setStyleSheet(f"color: {ACCENT}; font-size: 11px;")
        self.live_indicator.hide()
        bottom_row.addStretch(1)
        bottom_row.addWidget(self.live_indicator)
        layout.addLayout(bottom_row)

        self._live_active = False
        self.live_timer = QTimer(self)
        self.live_timer.setSingleShot(True)
        self.live_timer.timeout.connect(self._tick)

        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self._render_preview)

        self.thinking_throttle = QTimer(self)
        self.thinking_throttle.setSingleShot(True)
        self.thinking_throttle.timeout.connect(self._flush_thinking_text)

        if file_path is not None and file_path.exists():
            self.editor.setPlainText(file_path.read_text(encoding="utf-8"))
            self._last_len = len(self.editor.toPlainText())

        self._load_tree_state()
        self._render_preview()
        self._update_word_count()

    @staticmethod
    def _editor_font():
        font = QFont("Segoe UI")
        font.setPointSize(12)
        return font

    # ---- lifecycle ----
    def start_live(self):
        self._live_active = True
        self.live_indicator.show()
        self.live_timer.start(IDLE_MS)

    def stop_live(self):
        self._live_active = False
        self.live_indicator.hide()
        self.live_timer.stop()

    # ---- display ----
    def display_name(self) -> str:
        if self.current_file is not None:
            return self.current_file.stem
        return self._tab_label

    def breadcrumb(self) -> str:
        if self.current_file is not None:
            try:
                rel = self.current_file.relative_to(self.notes_dir)
                return f"Vault / {rel.as_posix()}"
            except ValueError:
                return f"Vault / {self.current_file.name}"
        return f"Vault / {self._tab_label} (kaydedilmedi)"

    def _on_text_changed(self):
        self._update_word_count()
        self.preview_timer.start(PREVIEW_DEBOUNCE_MS)
        if self._live_active:
            self.live_timer.start(IDLE_MS)  # restart the pause countdown on every keystroke

    def _update_word_count(self):
        text = self.editor.toPlainText()
        self.word_count_changed.emit(len(text.split()))

    def _on_cursor_moved(self):
        cursor = self.editor.textCursor()
        self.cursor_moved.emit(cursor.blockNumber() + 1, cursor.columnNumber() + 1)

    # ---- preview / source pane ----
    def _set_pane_mode(self, show_preview: bool):
        self.preview_tab_btn.setChecked(show_preview)
        self.source_tab_btn.setChecked(not show_preview)
        self._render_preview()

    def _render_preview(self):
        if self.preview_tab_btn.isChecked():
            doc = QTextDocument()
            doc.setMarkdown(self.editor.toPlainText())
            self.preview.setHtml(doc.toHtml())
        else:
            self.preview.setPlainText(self.editor.toPlainText())

    # ---- toolbar action ----
    def _ask_now(self):
        self._tick(force=True)

    # ---- file I/O ----
    def save(self, path: Path | None = None) -> Path:
        if path is not None:
            self.current_file = path
        if self.current_file is None:
            self.current_file = self.notes_dir / f"{self._tab_label}.md"
        self.current_file.write_text(self.editor.toPlainText(), encoding="utf-8")
        self._save_tree_state()  # now that current_file exists, the sidecar can too
        self.saved.emit(datetime.now().strftime("%H:%M:%S"))
        return self.current_file

    # ---- live monitoring ----
    def _tick(self, force: bool = False):
        if self._analyzing or not state.model_up:
            return
        text = self.editor.toPlainText()

        if len(text) < self._last_len:
            self._last_len = len(text)  # user deleted text, resync silently
            return

        new_part = text[self._last_len:]
        if not force and len(new_part.strip()) < MIN_NEW_CHARS:
            return
        if force and not new_part.strip():
            new_part = text[-800:]

        start, end = self._last_len, len(text)

        self._analyzing = True
        state.set_thinking(True)
        self._worker = AnalyzeWorker(text, new_part, self.open_questions)
        self._worker.chunk_ready.connect(self._on_chunk)
        self._worker.result_ready.connect(lambda r: self._on_result(r, start, end, text))
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_chunk(self, accumulated: str):
        """Show the model's live progress instead of a dead spinner — first its
        <think> scratchpad, then (once it closes) the actual answer as it's
        being written, so there's never a silent gap. Updates are throttled
        (see _flush_thinking_text) so the label changes a couple of times a
        second instead of once per token, which is unreadable."""
        if "</think>" in accumulated:
            after = accumulated.split("</think>", 1)[1].strip()
            snippet = self._trim_snippet(after)
            self._pending_thinking_text = f"✍️ {snippet}" if snippet else "✍️ Yanıt yazılıyor..."
        else:
            live = accumulated.split("<think>", 1)[-1].strip()
            snippet = self._trim_snippet(live)
            self._pending_thinking_text = f"💭 {snippet}" if snippet else ""

        if not self.thinking_throttle.isActive():
            self.thinking_throttle.start(THINKING_THROTTLE_MS)

    @staticmethod
    def _trim_snippet(text: str, limit: int = 200) -> str:
        snippet = text[-limit:]
        if " " in snippet and len(snippet) == limit:
            snippet = snippet.split(" ", 1)[-1]  # don't start mid-word
        return snippet

    def _flush_thinking_text(self):
        if self._pending_thinking_text is not None:
            state.set_thinking_text(self._pending_thinking_text)

    def _on_result(self, result: dict, start: int, end: int, text_snapshot: str):
        # cancel any queued throttle flush first — otherwise a chunk that
        # arrived just before this result can still fire seconds later and
        # briefly resurrect "yazıyor..." over the final answer
        self.thinking_throttle.stop()
        self._pending_thinking_text = None
        state.set_thinking(False)
        self._analyzing = False
        self._last_len = end

        event_type = result.get("type")
        now = datetime.now().strftime("%H:%M:%S")
        base = {"note_name": self.display_name(), "timestamp": now, "note_tab": self}

        if event_type == "net":
            state.show_flash("İncelendi", "Şu an için eklenecek bir şey bulunamadı.")
            state.push_event({**base, "type": "checked", "text": "Not incelendi, eklenecek bir şey yok."})
            return

        if event_type == "resolved":
            index = result.get("resolved_index")
            if not index or not (1 <= index <= len(self.open_questions)):
                return  # out-of-range reference — ignore rather than guess
            resolved_text = self.open_questions.pop(index - 1)
            resolved_id = self.open_question_ids.pop(index - 1)
            self._mark_node_resolved(resolved_id)
            state.push_event({**base, "type": "resolved", "text": resolved_text})
            return

        if event_type == "question":
            qtext = result.get("text", "").strip()
            if not qtext or qtext == self._last_shown_question:
                return
            self._last_shown_question = qtext
            self.open_questions.append(qtext)
            node_id = self._add_tree_node("root", qtext, "question")
            self.open_question_ids.append(node_id)
            state.push_event({**base, "type": "question", "text": qtext, "node_id": node_id})
            self._highlight_range(start, end)
            return

        if event_type == "edit":
            original = result.get("original", "").strip()
            replacement = result.get("replacement", "").strip()
            if not original or not replacement or original not in text_snapshot:
                return  # can't locate the quoted text — likely hallucinated, skip silently
            label = f'"{original}" → "{replacement}"'
            self._add_tree_node("root", label, "edit")
            state.push_event({
                **base, "type": "edit", "original": original,
                "replacement": replacement, "reason": result.get("reason", ""),
            })
            self._highlight_range(start, end)

    def _on_failed(self, error: str):
        self.thinking_throttle.stop()
        self._pending_thinking_text = None
        state.set_thinking(False)
        self._analyzing = False
        state.set_model_up(False)

    # ---- assistant actions ----
    def apply_edit(self, original: str, replacement: str) -> bool:
        cursor = self.editor.document().find(original)
        if cursor.isNull():
            return False
        cursor.insertText(replacement)
        return True

    def insert_ai_text(self, text: str):
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        current = self.editor.toPlainText()
        if current and not current.endswith("\n\n"):
            cursor.insertText("\n\n" if not current.endswith("\n") else "\n")
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)

    def open_chat(self, seed_question: str, node_id: str | None = None):
        from gui.chat_dialog import ChatDialog
        dialog = ChatDialog(self, seed_question, node_id)
        dialog.finished.connect(lambda _: self._chat_dialogs.remove(dialog) if dialog in self._chat_dialogs else None)
        self._chat_dialogs.append(dialog)
        dialog.show()

    # ---- growing tree view ----
    def _next_node_id(self, prefix: str) -> str:
        self._node_counter += 1
        return f"{prefix}{self._node_counter}"

    def _add_tree_node(self, parent_id: str, label: str, node_type: str) -> str:
        node_id = self._next_node_id(node_type[0])
        node = {"id": node_id, "parentId": parent_id, "label": label[:100], "type": node_type}
        self.tree_nodes.append(node)
        if self._tree_panel is not None:
            self._tree_panel.add_node(node)
        self._save_tree_state()
        return node_id

    def _mark_node_resolved(self, node_id: str):
        for node in self.tree_nodes:
            if node["id"] == node_id:
                node["type"] = "resolved"
                node["resolved"] = True
                break
        if self._tree_panel is not None:
            self._tree_panel.resolve_node(node_id)
        self._save_tree_state()

    def add_chat_node(self, parent_id: str, role: str, text: str):
        node_type = "chat-user" if role == "user" else "chat-assistant"
        self._add_tree_node(parent_id, text, node_type)

    def _tree_sidecar_path(self) -> Path | None:
        if self.current_file is None:
            return None
        return self.current_file.with_suffix(".tree.json")

    def _save_tree_state(self):
        path = self._tree_sidecar_path()
        if path is None:
            return  # unsaved note — nothing stable to attach the sidecar to yet
        data = {
            "open_questions": self.open_questions,
            "open_question_ids": self.open_question_ids,
            "tree_nodes": self.tree_nodes,
            "node_counter": self._node_counter,
        }
        try:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass  # persistence is a nice-to-have, never block on it

    def _load_tree_state(self):
        path = self._tree_sidecar_path()
        if path is None or not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.open_questions = data.get("open_questions", [])
        self.open_question_ids = data.get("open_question_ids", [])
        self.tree_nodes = data.get("tree_nodes", [])
        self._node_counter = data.get("node_counter", len(self.tree_nodes))

    def _highlight_range(self, start: int, end: int):
        cursor = QTextCursor(self.editor.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)

        fmt = QTextCharFormat()
        fmt.setBackground(QColor(137, 92, 245, 55))
        selection = QTextEdit.ExtraSelection()
        selection.cursor = cursor
        selection.format = fmt
        self.editor.setExtraSelections([selection])

        QTimer.singleShot(HIGHLIGHT_MS, lambda: self.editor.setExtraSelections([]))
