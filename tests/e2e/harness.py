"""The pieces the end-to-end tests share: a running app and a page on it."""
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from testkit.fake_model import FakeModel  # noqa: E402
from testkit.seed import bind_fake_model, seed_vault  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class App:
    """One running Concept Trail: its address, vault and a small API client."""

    def __init__(self, root: Path, model: FakeModel | None):
        self.vault = root / "kasa"
        self.config = root / "ayar"
        seed_vault(self.vault)
        if model is not None:
            bind_fake_model(self.config, model.base_url)
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}/"
        env = {**os.environ, "FIKIR_CONFIG_DIR": str(self.config), "PYTHONIOENCODING": "utf-8"}
        self.log = (root / "sunucu.log").open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [sys.executable, str(ROOT / "main.py"), "--server", "--port", str(self.port), "--vault", str(self.vault)],
            cwd=ROOT, env=env, stdout=self.log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.api = httpx.Client(base_url=self.url, headers={"X-Fikir": "1"}, timeout=30)
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            try:
                if self.api.get("/api/state").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            if self.process.poll() is not None:
                break
            time.sleep(0.3)
        self.stop()
        raise RuntimeError(f"Uygulama başlamadı; günlük: {root / 'sunucu.log'}")

    def note(self, text: str, name: str | None = None) -> str:
        """A note of this test's own; returns its name as the sidebar shows it."""
        name = name or f"Test {uuid.uuid4().hex[:6]}"
        rel = self.api.post("/api/notes/create", json={"dir": "", "name": name, "content": text}).json()
        return rel["path"] if isinstance(rel, dict) and "path" in rel else f"{name}.md"

    def stop(self) -> None:
        self.api.close()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(10)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.log.close()


class Page:
    """A page on the app, with the page's own errors collected."""

    def __init__(self, page, app: App):
        self.page, self.app, self.errors = page, app, []
        page.on("pageerror", lambda error: self.errors.append(str(error)))

    def open(self) -> "Page":
        self.app.api.put("/api/session", json={})            # no tabs, switches at their defaults
        self.page.goto(self.app.url)
        self.page.wait_for_selector(".sidebar .name", state="attached", timeout=15000)
        return self

    def open_note(self, name: str) -> None:
        shown = name.removesuffix(".md")
        self.page.wait_for_function(
            "(n) => [...document.querySelectorAll('.sidebar .name')].some((e) => e.textContent.trim().replace(/\\.md$/, '') === n)",
            arg=shown, timeout=15000)
        self.page.evaluate(
            "(n) => [...document.querySelectorAll('.sidebar .name')].find((e) => e.textContent.trim().replace(/\\.md$/, '') === n).click()",
            shown)
        self.page.wait_for_selector(".md-editor.active .md-input, .md-editor .md-input", timeout=10000)
        self.editor().click()
        self.page.keyboard.press("Control+End")

    def editor(self):
        return self.page.locator(".md-editor").filter(has=self.page.locator(".md-input:visible")).locator(".md-input").first

    def value(self) -> str:
        return self.editor().input_value()

    def ghost(self):
        return self.page.evaluate("document.querySelector('.md-mirror .ghost')?.textContent ?? null")
