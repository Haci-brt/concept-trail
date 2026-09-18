"""Legacy PyQt6 entry point (the pre-web UI). Kept until the web app has fully
replaced it — run `python main.py` for the current app."""
import sys
from PyQt6.QtWidgets import QApplication

from hud.hud_window import HudWindow
from gui.notebook_window import NotebookWindow
from gui.theme import APP_STYLESHEET


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLESHEET)

    hud = HudWindow()
    hud.show()

    window = NotebookWindow(hud)
    window.showMaximized()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
