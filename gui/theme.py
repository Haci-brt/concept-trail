"""Obsidian-inspired dark palette and stylesheet.

Colors lifted from Obsidian's actual default dark theme CSS variables
(--color-base-00..100, accent hsl(258, 88%, 66%) ≈ #895cf5) so the app
reads as a real "vault" rather than a generic dark-mode form.
"""

BG_0 = "#1c1c1c"     # app background / sidebars
BG_05 = "#202020"
BG_10 = "#232323"    # editor surface
BG_20 = "#282828"    # hover
BG_30 = "#333333"    # subtle separators only
TEXT_100 = "#dcdcdc"
TEXT_MUTED = "#8a8a8a"
ACCENT = "#895cf5"
ACCENT_HOVER = "#7a49f2"
ACCENT_SOFT = "rgba(137, 92, 245, 45)"

APP_STYLESHEET = f"""
QWidget {{
    background-color: {BG_0};
    color: {TEXT_100};
    font-family: "Segoe UI";
    font-size: 13px;
}}

QWidget#sidebar {{
    background-color: {BG_0};
}}

QLabel#sidebarTitle {{
    color: {TEXT_MUTED};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    padding: 4px 2px;
}}

QTextEdit {{
    background-color: {BG_10};
    border: none;
    border-radius: 6px;
    padding: 14px 18px;
    selection-background-color: {ACCENT_SOFT};
}}

QTextBrowser {{
    background-color: {BG_10};
    border: none;
    border-radius: 6px;
    padding: 14px 18px;
}}

QTreeView {{
    background-color: {BG_0};
    border: none;
    outline: none;
}}
QTreeView::item {{
    padding: 3px 4px;
    border-radius: 4px;
}}
QTreeView::item:hover {{
    background-color: {BG_20};
}}
QTreeView::item:selected {{
    background-color: {ACCENT_SOFT};
    color: {TEXT_100};
}}

QListWidget {{
    background-color: {BG_0};
    border: none;
}}
QListWidget::item {{
    padding: 6px 6px;
    border-radius: 4px;
    margin: 1px 0;
}}
QListWidget::item:hover {{
    background-color: {BG_20};
}}
QListWidget::item:selected {{
    background-color: {ACCENT_SOFT};
}}

QTabWidget::pane {{
    border: none;
    background-color: {BG_0};
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_MUTED};
    padding: 6px 16px;
    margin: 4px 2px 0 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}}
QTabBar::tab:hover {{
    background: {BG_20};
    color: {TEXT_100};
}}
QTabBar::tab:selected {{
    background: {BG_10};
    color: {TEXT_100};
    border-bottom: 2px solid {ACCENT};
}}

QPushButton {{
    background-color: {BG_20};
    color: {TEXT_100};
    border: none;
    border-radius: 5px;
    padding: 6px 12px;
}}
QPushButton:hover {{
    background-color: {BG_30};
}}
QPushButton:checked {{
    background-color: {ACCENT};
    color: white;
}}

QPushButton#accentButton {{
    background-color: {ACCENT};
    color: white;
    font-weight: 600;
}}
QPushButton#accentButton:hover {{
    background-color: {ACCENT_HOVER};
}}

QComboBox {{
    background-color: {BG_20};
    border: none;
    border-radius: 5px;
    padding: 5px 8px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_10};
    selection-background-color: {ACCENT_SOFT};
    border: none;
}}

QLineEdit {{
    background-color: {BG_20};
    border: none;
    border-radius: 5px;
    padding: 7px 10px;
    color: {TEXT_100};
}}
QLineEdit:focus {{
    background-color: {BG_30};
}}

QSplitter::handle {{
    background-color: {BG_0};
    width: 3px;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: {BG_30};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QWidget#mainRoot {{
    background: qlineargradient(x1:0, y1:0, x2:0.3, y2:1,
        stop:0 #201c2e, stop:0.5 #19161f, stop:1 #151318);
}}

QWidget#titleBar {{
    background-color: {BG_05};
    border-bottom: 1px solid {BG_30};
}}
QWidget#titleBar QLabel {{
    background: transparent;
}}
QWidget#titleBar QPushButton {{
    background-color: transparent;
    border-radius: 4px;
    padding: 0;
}}
QWidget#titleBar QPushButton:hover {{
    background-color: {BG_20};
}}
QPushButton#closeButton:hover {{
    background-color: #e5484d;
    color: white;
}}

QWidget#statusBar {{
    background-color: {BG_05};
    border-top: 1px solid {BG_30};
}}
QLabel#statusBarLabel {{
    color: {TEXT_MUTED};
    font-size: 11px;
    background: transparent;
}}

QWidget#editorToolbar {{
    background: transparent;
}}
QWidget#editorToolbar QPushButton {{
    background: transparent;
    padding: 4px 8px;
    border-radius: 4px;
    min-width: 22px;
    font-weight: 600;
}}
QWidget#editorToolbar QPushButton:hover {{
    background-color: {BG_20};
}}
QPushButton#sparkleButton {{
    color: {ACCENT};
}}

QPushButton#paneTab {{
    background: transparent;
    border-radius: 0;
    padding: 4px 2px;
    color: {TEXT_MUTED};
    font-weight: 500;
}}
QPushButton#paneTab:checked {{
    color: {ACCENT};
    font-weight: 600;
    border-bottom: 2px solid {ACCENT};
}}
QPushButton#paneTab:hover {{
    background: transparent;
    color: {TEXT_100};
}}

QWidget#brandCard {{
    background-color: {BG_10};
    border-radius: 8px;
}}
QLabel#brandTitle {{
    color: {TEXT_100};
    font-weight: 600;
    font-size: 12px;
    background: transparent;
}}
QLabel#brandSubtitle {{
    color: {TEXT_MUTED};
    font-size: 11px;
    background: transparent;
}}

QPushButton#tagPill {{
    background-color: {BG_10};
    border-radius: 10px;
    padding: 3px 10px;
    font-size: 11px;
    color: {TEXT_MUTED};
    text-align: left;
}}
QPushButton#tagPill:hover {{
    background-color: {BG_20};
    color: {TEXT_100};
}}

QWidget#iconBar QPushButton {{
    background: transparent;
    border-radius: 5px;
    padding: 5px 8px;
}}
QWidget#iconBar QPushButton:hover {{
    background-color: {BG_20};
}}

QWidget#historyCard {{
    background: transparent;
}}
QLabel#historyTitle {{
    color: {TEXT_100};
    font-size: 12px;
    font-weight: 600;
    background: transparent;
}}
QLabel#historySubtitle {{
    color: {TEXT_MUTED};
    font-size: 11px;
    background: transparent;
}}
QLabel#historyTime {{
    color: {TEXT_MUTED};
    font-size: 10px;
    background: transparent;
}}

QWidget#hudCard {{
    background-color: rgba(28, 24, 38, 235);
    border-radius: 10px;
    border: 1px solid {BG_30};
}}
QLabel#hudTitle {{
    color: {ACCENT};
    font-weight: 700;
    font-size: 13px;
    background: transparent;
}}
QLabel#hudBody {{
    color: {TEXT_100};
    font-size: 13px;
    background: transparent;
}}

QWidget#switcherFooter {{
    background-color: {BG_05};
    border-top: 1px solid {BG_30};
}}
QLabel#switcherHint {{
    color: {TEXT_MUTED};
    font-size: 10px;
    background: transparent;
}}
"""
