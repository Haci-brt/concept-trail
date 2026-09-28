"""Desktop shell around the web app.

A frameless QtWebEngine window shows the app (the page draws its own title
bar), and a second frameless, always-on-top HUD window shows the assistant's
suggestion card over whatever else is on screen — the same floating HUD the
old PyQt app had. The HUD never takes keyboard focus, so it can pop up while
you type. Pages talk back through a QWebChannel
object exposed as window.desktop (see web/js/desktop.js).
"""
import ctypes
import sys
from pathlib import Path

from PyQt6.QtCore import (QEvent, QFile, QIODevice, QObject, QPoint, QPointF, QRect, QRectF, QSettings, Qt, QTimer, QUrl,
                          pyqtSignal, pyqtSlot)
from PyQt6.QtGui import QColor, QCursor, QDesktopServices, QGuiApplication, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineScript, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget

APP_NAME = "Concept Trail"
# where Qt kept window and HUD positions while the app was "Fikir Not Defteri"
OLD_SETTINGS = ("FikirNotDefteri", "Fikir Not Defteri")
HUD_WIDTH = 380
HUD_MARGIN = 18
HUD_TOP_OFFSET = 58  # clear a maximized main window's title bar

_EDGES = {
    "left": Qt.Edge.LeftEdge, "right": Qt.Edge.RightEdge,
    "top": Qt.Edge.TopEdge, "bottom": Qt.Edge.BottomEdge,
}


def _bridge_script() -> QWebEngineScript:
    resource = QFile(":/qtwebchannel/qwebchannel.js")
    resource.open(QIODevice.OpenModeFlag.ReadOnly)
    source = bytes(resource.readAll()).decode("utf-8")
    source += """
;(function connect() {
  if (typeof qt === "undefined" || !qt.webChannelTransport) { setTimeout(connect, 25); return; }
  new QWebChannel(qt.webChannelTransport, function (channel) {
    window.desktop = channel.objects.desktop;
    window.dispatchEvent(new Event("desktop-ready"));
  });
})();"""
    script = QWebEngineScript()
    script.setName("desktop-bridge")
    script.setSourceCode(source)
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(False)
    return script


ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "icon"


def _app_icon() -> QIcon:
    """The app icon (assets/icon, drawn by build_icons.py) at every size the
    OS asks for — title bar, taskbar, Alt+Tab. Without the files (a trimmed
    copy of the app) the old gem mark is painted instead."""
    icon = QIcon()
    for png in sorted((ICON_DIR / "png").glob("concept-trail-*.png")):
        icon.addFile(str(png))
    if not icon.isNull():
        return icon
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = size / 32
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#147b70"))
        painter.drawRoundedRect(QRectF(.5 * s, .5 * s, 31 * s, 31 * s), 9 * s, 9 * s)
        polygon = lambda points: QPolygonF([QPointF(x * s, y * s) for x, y in points])
        painter.setBrush(QColor("#effff8"))
        painter.drawPolygon(polygon([(16, 4.75), (26.25, 13.25), (16, 27.5), (5.75, 13.25)]))
        painter.setBrush(QColor("#bfeedd"))
        painter.drawPolygon(polygon([(16, 4.75), (12.25, 13.25), (19.75, 13.25)]))
        painter.setBrush(QColor("#d8f8ed"))
        painter.drawPolygon(polygon([(5.75, 13.25), (26.25, 13.25), (16, 27.5)]))
        pen = QPen(QColor("#147b70"), max(.7, 1.1 * s))
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(QPointF(5.75 * s, 13.25 * s), QPointF(26.25 * s, 13.25 * s))
        painter.drawPolyline(polygon([(16, 4.75), (12.25, 13.25), (16, 27.5), (19.75, 13.25)]))
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def _left_button_down() -> bool:
    if sys.platform == "win32":
        return bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
    return bool(QGuiApplication.mouseButtons() & Qt.MouseButton.LeftButton)


def _track_mouse(window: QWidget, apply) -> None:
    """Fallback when the platform refuses a native move/resize loop."""
    start_cursor = QCursor.pos()
    start_geometry = window.geometry()
    timer = QTimer(window)
    timer.setInterval(10)

    def tick():
        if not _left_button_down():
            timer.stop()
            timer.deleteLater()
            return
        apply(start_geometry, QCursor.pos() - start_cursor)

    timer.timeout.connect(tick)
    timer.start()


def start_move(window: QWidget) -> None:
    handle = window.windowHandle()
    if handle is not None and handle.startSystemMove():
        return
    _track_mouse(window, lambda geo, delta: window.move(geo.topLeft() + delta))


def start_resize(window: QWidget, edge_name: str) -> None:
    edges = Qt.Edge(0)
    for part in edge_name.split("-"):
        if part in _EDGES:
            edges |= _EDGES[part]
    if not edges:
        return
    handle = window.windowHandle()
    if handle is not None and handle.startSystemResize(edges):
        return

    minimum = window.minimumSize()

    def apply(geo: QRect, delta: QPoint):
        rect = QRect(geo)
        if edges & Qt.Edge.LeftEdge:
            rect.setLeft(min(geo.left() + delta.x(), geo.right() - minimum.width()))
        if edges & Qt.Edge.RightEdge:
            rect.setRight(max(geo.right() + delta.x(), geo.left() + minimum.width()))
        if edges & Qt.Edge.TopEdge:
            rect.setTop(min(geo.top() + delta.y(), geo.bottom() - minimum.height()))
        if edges & Qt.Edge.BottomEdge:
            rect.setBottom(max(geo.bottom() + delta.y(), geo.top() + minimum.height()))
        window.setGeometry(rect)

    _track_mouse(window, apply)


def _round_corners(window: QWidget) -> None:
    """Windows 11 draws rounded corners and a shadow only if asked for frameless windows."""
    if sys.platform != "win32":
        return
    try:
        preference = ctypes.c_int(2)  # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(int(window.winId()), 33, ctypes.byref(preference),
                                                   ctypes.sizeof(preference))
    except (AttributeError, OSError):
        pass


class AppPage(QWebEnginePage):
    """Keeps navigation inside the local app; everything else opens in the system browser."""

    def __init__(self, origin: QUrl, parent=None):
        super().__init__(parent)
        self._origin = origin

    def _is_local(self, url: QUrl) -> bool:
        return url.host() == self._origin.host() and url.port() == self._origin.port()

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if self._is_local(url) or url.scheme() in ("data", "blob", "about"):
            return True
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)
        return False

    def createWindow(self, _type):
        return _ExternalOpener(self)


class _ExternalOpener(QWebEnginePage):
    """target=_blank links land here; hand them to the system browser."""

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)
        self.deleteLater()
        return False


class Bridge(QObject):
    maximizedChanged = pyqtSignal(bool)

    def __init__(self, window: QWidget, shell: "DesktopShell"):
        super().__init__(window)
        self._window = window
        self._shell = shell

    @pyqtSlot()
    def minimize(self):
        self._window.showMinimized()

    @pyqtSlot()
    def toggleMaximize(self):
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    @pyqtSlot(result=bool)
    def isMaximized(self):
        return self._window.isMaximized()

    @pyqtSlot()
    def closeNow(self):
        self._shell.quit()

    @pyqtSlot()
    def startMove(self):
        start_move(self._window)

    @pyqtSlot(str)
    def startResize(self, edge: str):
        if not self._window.isMaximized():
            start_resize(self._window, edge)

    @pyqtSlot(str)
    def openExternal(self, url: str):
        target = QUrl(url)
        if target.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(target)

    @pyqtSlot()
    def focusMain(self):
        self._shell.focus_main()

    @pyqtSlot(bool, int)
    def setHudState(self, visible: bool, height: int):
        self._shell.set_hud_state(visible, height)


def _make_view(owner: QWidget, url: str, shell: "DesktopShell", background: QColor) -> tuple[QWebEngineView, Bridge]:
    view = QWebEngineView(owner)
    page = AppPage(QUrl(url), view)
    page.setBackgroundColor(background)
    bridge = Bridge(owner, shell)
    channel = QWebChannel(page)
    channel.registerObject("desktop", bridge)
    page.setWebChannel(channel)
    page.scripts().insert(_bridge_script())
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, True)
    view.setPage(page)
    view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
    return view, bridge


class MainWindow(QWidget):
    def __init__(self, url: str, shell: "DesktopShell"):
        super().__init__()
        self._shell = shell
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowSystemMenuHint | Qt.WindowType.WindowMinMaxButtonsHint)
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QApplication.instance().windowIcon())
        self.setMinimumSize(860, 540)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view, self.bridge = _make_view(self, url, shell, QColor("#0e0c14"))
        layout.addWidget(self.view)
        self.view.setUrl(QUrl(url))

        settings = QSettings()
        geometry = settings.value("main/geometry")
        if geometry is None or not self.restoreGeometry(geometry):
            screen = QGuiApplication.primaryScreen().availableGeometry()
            width, height = min(1480, screen.width() - 80), min(920, screen.height() - 80)
            self.setGeometry(screen.x() + (screen.width() - width) // 2,
                             screen.y() + (screen.height() - height) // 2, width, height)
        self._maximize_on_show = settings.value("main/maximized", "false") == "true"

    def show_initial(self):
        if self._maximize_on_show:
            self.showMaximized()
        else:
            self.show()
        _round_corners(self)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange:
            self.bridge.maximizedChanged.emit(self.isMaximized())
        super().changeEvent(event)

    def closeEvent(self, event):
        if self._shell.quitting:
            settings = QSettings()
            settings.setValue("main/maximized", "true" if self.isMaximized() else "false")
            if not self.isMaximized():
                settings.setValue("main/geometry", self.saveGeometry())
            event.accept()
            return
        # let the page flush unsaved edits first; it calls desktop.closeNow() when done
        event.ignore()
        self.view.page().runJavaScript(
            "window.__requestClose ? window.__requestClose() : (window.desktop && window.desktop.closeNow())")
        QTimer.singleShot(3000, self._shell.quit)


class HudWindow(QWidget):
    def __init__(self, url: str, shell: "DesktopShell"):
        super().__init__()
        self._shell = shell
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle(f"{APP_NAME} HUD")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view, self.bridge = _make_view(self, url, shell, QColor(0, 0, 0, 0))
        layout.addWidget(self.view)
        self.setFixedWidth(HUD_WIDTH)
        self.resize(HUD_WIDTH, 160)
        self.view.setUrl(QUrl(url))

        self._placing = False
        saved = QSettings().value("hud/pos")
        self._user_pos: QPoint | None = saved if isinstance(saved, QPoint) else None

    def apply_state(self, visible: bool, height: int):
        if not visible or height <= 0:
            self.hide()
            return
        self.setFixedHeight(max(40, min(height, 640)))
        self._place()
        if not self.isVisible():
            self.show()
        self.raise_()

    def _place(self):
        self._placing = True
        try:
            if self._user_pos is not None and QGuiApplication.screenAt(self._user_pos) is not None:
                self.move(self._user_pos)
                return
            main = self._shell.main
            anchor = main.geometry().center()
            screen = (QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()).availableGeometry()
            if main.isVisible() and not main.isMinimized():
                # just under the app's own title bar, over the history panel — never on the window controls
                frame = main.frameGeometry()
                x = min(frame.right(), screen.right()) - self.width() - 6
                y = max(frame.top(), screen.top()) + HUD_TOP_OFFSET
            else:
                x = screen.right() - self.width() - HUD_MARGIN + 1
                y = screen.top() + HUD_MARGIN
            self.move(max(screen.left(), x), min(y, screen.bottom() - self.height()))
        finally:
            self._placing = False

    def moveEvent(self, event):
        super().moveEvent(event)
        if not self._placing and self.isVisible():
            self._user_pos = self.pos()
            QSettings().setValue("hud/pos", self._user_pos)


class DesktopShell:
    def __init__(self, url: str, hud: bool):
        self.quitting = False
        page_url = f"{url}?desktop=1" + ("" if hud else "&hud=0")
        self.main = MainWindow(page_url, self)
        self.hud = HudWindow(f"{url}hud?desktop=1", self) if hud else None

    def start(self):
        self.main.show_initial()

    def focus_main(self):
        if self.main.isMinimized():
            self.main.showNormal()
        self.main.raise_()
        self.main.activateWindow()

    def set_hud_state(self, visible: bool, height: int):
        if self.hud is not None:
            self.hud.apply_state(visible, height)

    def quit(self):
        if self.quitting:
            return
        self.quitting = True
        self.main.close()
        if self.hud is not None:
            self.hud.close()
        QApplication.quit()


def run_desktop(url: str, hud: bool = True) -> int:
    if sys.platform == "win32":
        try:  # own taskbar entry and icon instead of python.exe's
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ConceptTrail.App")
        except (AttributeError, OSError):
            pass
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("ConceptTrail")
    settings = QSettings()
    if not settings.allKeys():
        # a new name is a new settings key: bring the remembered positions along
        old = QSettings(*OLD_SETTINGS)
        for key in old.allKeys():
            settings.setValue(key, old.value(key))
    app.setWindowIcon(_app_icon())
    app.setQuitOnLastWindowClosed(False)
    shell = DesktopShell(url, hud)
    shell.start()
    return app.exec()
