"""Background QThread workers so network calls to the local model never
block the UI thread."""
from PyQt6.QtCore import QThread, pyqtSignal

from core.llm_client import ask_about_note, chat_reply, summarize_for_note, is_server_up


class AnalyzeWorker(QThread):
    chunk_ready = pyqtSignal(str)   # accumulated raw text so far (may include <think>)
    result_ready = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, full_text: str, new_part: str, open_questions: list[str]):
        super().__init__()
        self.full_text = full_text
        self.new_part = new_part
        self.open_questions = list(open_questions)

    def run(self):
        try:
            result = ask_about_note(
                self.full_text, self.new_part, self.open_questions,
                on_chunk=lambda text: self.chunk_ready.emit(text),
            )
            self.result_ready.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class ChatWorker(QThread):
    reply_ready = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, history: list[dict], note_excerpt: str):
        super().__init__()
        self.history = history
        self.note_excerpt = note_excerpt

    def run(self):
        try:
            reply = chat_reply(self.history, self.note_excerpt)
            self.reply_ready.emit(reply)
        except Exception as exc:
            self.failed.emit(str(exc))


class SummarizeWorker(QThread):
    text_ready = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, history: list[dict]):
        super().__init__()
        self.history = history

    def run(self):
        try:
            text = summarize_for_note(self.history)
            self.text_ready.emit(text)
        except Exception as exc:
            self.failed.emit(str(exc))


class HealthCheckWorker(QThread):
    status_ready = pyqtSignal(bool)

    def run(self):
        self.status_ready.emit(is_server_up())
