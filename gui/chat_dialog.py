"""Non-modal chat window to work through one of the assistant's questions,
then write the outcome directly into the note it came from."""
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit, QPushButton, QLabel

from core.workers import ChatWorker, SummarizeWorker


class ChatDialog(QDialog):
    def __init__(self, note_tab, seed_question: str, node_id: str | None = None, parent=None):
        super().__init__(parent)
        self.note_tab = note_tab
        self.node_id = node_id  # the tree-view node this conversation branches off of
        self.setWindowTitle("Asistanla Sohbet")
        self.resize(420, 520)
        self.history: list[dict] = [{"role": "assistant", "content": seed_question}]
        self._worker = None

        layout = QVBoxLayout(self)

        self.thread_view = QTextEdit()
        self.thread_view.setReadOnly(True)
        layout.addWidget(self.thread_view, 1)
        self._append_bubble("Asistan", seed_question)

        input_row = QHBoxLayout()
        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("Cevabını yaz...")
        self.input_box.returnPressed.connect(self._send)
        input_row.addWidget(self.input_box, 1)
        send_btn = QPushButton("Gönder")
        send_btn.clicked.connect(self._send)
        input_row.addWidget(send_btn)
        layout.addLayout(input_row)

        bottom_row = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #8a8a8a; font-size: 11px;")
        bottom_row.addWidget(self.status_label, 1)
        write_btn = QPushButton("📝 Nota Yaz")
        write_btn.setObjectName("accentButton")
        write_btn.clicked.connect(self._write_to_note)
        bottom_row.addWidget(write_btn)
        layout.addLayout(bottom_row)

        self.input_box.setFocus()

    def _append_bubble(self, who: str, text: str):
        safe = text.replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        self.thread_view.append(f"<b>{who}:</b> {safe}<br>")

    def _send(self):
        text = self.input_box.text().strip()
        if not text or self._worker is not None:
            return
        self.input_box.clear()
        self._append_bubble("Sen", text)
        self.history.append({"role": "user", "content": text})
        if self.node_id:
            self.note_tab.add_chat_node(self.node_id, "user", text)
        self.status_label.setText("Asistan yazıyor...")
        self._worker = ChatWorker(list(self.history), self.note_tab.editor.toPlainText())
        self._worker.reply_ready.connect(self._on_reply)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_reply(self, reply: str):
        self.status_label.setText("")
        self._worker = None
        self.history.append({"role": "assistant", "content": reply})
        if self.node_id:
            self.note_tab.add_chat_node(self.node_id, "assistant", reply)
        self._append_bubble("Asistan", reply)

    def _on_failed(self, error: str):
        self.status_label.setText("Model yanıt vermedi, model çalışıyor mu kontrol et.")
        self._worker = None

    def _write_to_note(self):
        if self._worker is not None:
            return
        self.status_label.setText("Not için yazılıyor...")
        self._worker = SummarizeWorker(list(self.history))
        self._worker.text_ready.connect(self._on_summary_ready)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_summary_ready(self, text: str):
        self.status_label.setText("")
        self._worker = None
        self.note_tab.insert_ai_text(text)
        self._append_bubble("Sistem", "✅ Nota eklendi.")
