"""Panel embedding the growing-tree visualization (tree_view.html) via a
local QWebEngineView. Python pushes new nodes as the assistant raises
questions, suggests edits, resolves things, or chats — the JS side owns
layout, physics and rendering."""
import json
from pathlib import Path

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl

HTML_PATH = Path(__file__).parent / "tree_view.html"


class TreeViewPanel(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.view = QWebEngineView()
        self._ready = False
        self.view.loadFinished.connect(self._on_load_finished)
        self.view.setUrl(QUrl.fromLocalFile(str(HTML_PATH)))
        layout.addWidget(self.view)

        self._pending = []  # calls queued before the page finished loading

    def _on_load_finished(self, ok: bool):
        self._ready = ok
        # mark as embedded so the HTML's standalone demo bootstrap doesn't run
        self._run_js("window.__EMBEDDED__ = true;")
        for call in self._pending:
            self._run_js(call)
        self._pending.clear()

    def _run_js(self, script: str):
        if self._ready:
            self.view.page().runJavaScript(script)
        else:
            self._pending.append(script)

    def reset_and_load(self, root_label: str, nodes: list[dict]):
        self._run_js(f"window.resetTree({json.dumps(root_label)});")
        for node in nodes:
            self._run_js(f"window.addNode({json.dumps(node)});")
            if node.get("resolved"):
                self._run_js(f"window.resolveNode({json.dumps(node['id'])});")

    def add_node(self, node: dict):
        self._run_js(f"window.addNode({json.dumps(node)});")

    def resolve_node(self, node_id: str):
        self._run_js(f"window.resolveNode({json.dumps(node_id)});")
