"""Concept Trail — entry point.

Starts the local web server (127.0.0.1 only) and opens the app:
    python main.py              desktop window + always-on-top HUD (PyQt6 WebEngine)
    python main.py --no-hud     desktop window, suggestions shown inside the app
    python main.py --browser    open in the default browser instead
    python main.py --server     only run the server (e.g. to open it yourself)

If the app is already running, a second launch reuses that server.
"""
import argparse
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import requests
import uvicorn

from server.settings import APP_ID, DEFAULT_PORT, DEFAULT_VAULT, Settings


class ServerThread(threading.Thread):
    def __init__(self, settings: Settings):
        super().__init__(name="fikir-server", daemon=True)
        from server.app import create_app

        config = uvicorn.Config(
            create_app(settings), host=settings.host, port=settings.port,
            log_level="warning", access_log=False, timeout_graceful_shutdown=1,
        )
        self.server = uvicorn.Server(config)

    def run(self):
        self.server.run()

    def wait_ready(self, timeout: float = 15.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.server.started:
                return True
            if not self.is_alive():
                return False
            time.sleep(0.05)
        return False

    def stop(self):
        self.server.should_exit = True
        self.join(timeout=3)


def existing_instance(port: int) -> bool:
    try:
        r = requests.get(f"http://127.0.0.1:{port}/api/state", timeout=0.6)
        return r.ok and r.json().get("app") == APP_ID
    except (requests.RequestException, ValueError):
        return False


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


LOG_LIMIT = 1_000_000


def attach_log_when_windowless(path: Path) -> None:
    """pythonw.exe starts with sys.stdout and sys.stderr set to None, and
    uvicorn's log formatter asks sys.stdout.isatty() while it is configured —
    so a launch without a console died before the server came up, silently.
    The streams go to a log file instead: nothing breaks, and an error is kept."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size > LOG_LIMIT:
            path.unlink()
        stream = open(path, "a", encoding="utf-8", buffering=1)
    except OSError:
        import os
        stream = open(os.devnull, "w", encoding="utf-8")
    sys.stdout = sys.stdout or stream
    sys.stderr = sys.stderr or stream


def parse_args():
    parser = argparse.ArgumentParser(description="Concept Trail")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--browser", action="store_true", help="open in the default web browser")
    mode.add_argument("--server", action="store_true", help="only run the local server")
    parser.add_argument("--no-hud", action="store_true", help="no separate always-on-top HUD window")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"server port (default {DEFAULT_PORT})")
    parser.add_argument("--vault", type=Path, default=DEFAULT_VAULT, help="notes folder (default ./notes)")
    return parser.parse_args()


def main():
    from server.providers import config_dir

    attach_log_when_windowless(config_dir() / "concept-trail.log")
    args = parse_args()
    server = None
    port = args.port

    if existing_instance(port):
        print(f"Concept Trail zaten çalışıyor: http://127.0.0.1:{port}/")
    else:
        if not port_free(port):
            port = free_port()
        server = ServerThread(Settings(vault=args.vault.expanduser(), port=port))
        server.start()
        if not server.wait_ready():
            sys.exit("Sunucu başlatılamadı.")

    url = f"http://127.0.0.1:{port}/"

    if args.browser or args.server:
        if args.browser:
            webbrowser.open(url)
        print(f"Concept Trail: {url}  (durdurmak için Ctrl+C)")
        if server is None:
            return
        try:
            while server.is_alive():
                server.join(0.5)
        except KeyboardInterrupt:
            server.stop()
        return

    from desktop.shell import run_desktop

    code = run_desktop(url, hud=not args.no_hud)
    if server is not None:
        server.stop()
    sys.exit(code)


if __name__ == "__main__":
    main()
