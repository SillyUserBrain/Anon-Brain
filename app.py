"""Anon Brain: posts in, videos out.

Start the app with "Anon Brain.bat" (or: py app.py), or the installed Anon Brain.exe.
"""

import getpass
import os
import sys

from anonbrain import appinfo

SERVER = "AnonBrain-" + "".join(c for c in getpass.getuser() if c.isalnum())


def _already_running(app) -> bool:
    """If Anon Brain is already open (maybe in the tray), bring that one forward
    instead of starting a second copy (two copies would both run Automate)."""
    from PySide6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(SERVER)
    if not sock.waitForConnected(400):
        return False
    sock.write(b"show")
    sock.flush()
    sock.waitForBytesWritten(400)
    sock.disconnectFromServer()
    return True


def _listen(app, win):
    """Answer a second start-up by showing this window."""
    from PySide6.QtNetwork import QLocalServer
    server = QLocalServer(app)
    QLocalServer.removeServer(SERVER)          # left over after a crash
    if not server.listen(SERVER):
        return

    def incoming():
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.readyRead.connect(lambda c=conn: (c.readAll(), win.show_from_tray()))
    server.newConnection.connect(incoming)
    app._single_server = server


def _splash():
    """A small "starting" card while the window is being built (a second or two)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
    from PySide6.QtWidgets import QSplashScreen
    pm = QPixmap(380, 150)
    pm.fill(QColor(12, 14, 19))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    icon = appinfo.app_dir() / "assets" / "icon.png"
    for base in (appinfo.app_dir(), *([__import__("pathlib").Path(sys._MEIPASS)]
                                      if getattr(sys, "_MEIPASS", None) else [])):
        if (base / "assets" / "icon.png").exists():
            icon = base / "assets" / "icon.png"
            break
    if icon.exists():
        p.drawPixmap(28, 43, QPixmap(str(icon)).scaled(64, 64, Qt.KeepAspectRatio,
                                                       Qt.SmoothTransformation))
    p.setPen(QColor("#ffffff"))
    f = QFont("Segoe UI", 15)
    f.setWeight(QFont.Black)
    p.setFont(f)
    p.drawText(110, 70, "ANON BRAIN")
    p.setPen(QColor(255, 255, 255, 140))
    f2 = QFont("Segoe UI", 9)
    p.setFont(f2)
    p.drawText(110, 96, f"Starting…   {appinfo.VERSION}")
    p.setPen(QColor(143, 196, 63, 120))
    p.drawRect(0, 0, pm.width() - 1, pm.height() - 1)
    p.end()
    s = QSplashScreen(pm, Qt.WindowStaysOnTopHint)
    s.show()
    return s


def main():
    appinfo.setup_logging()
    appinfo.setup_keyring()
    if "--selftest" in sys.argv:            # Anon Brain.exe --selftest
        print(appinfo.self_test())
        return

    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication(sys.argv)
    app.setApplicationName(appinfo.NAME)
    app.setApplicationVersion(appinfo.VERSION)
    app.setStyle("Fusion")
    if _already_running(app):
        return
    splash = None if "--tray" in sys.argv else _splash()
    app.processEvents()
    from PySide6.QtCore import Qt
    for fx in (Qt.UI_AnimateCombo, Qt.UI_AnimateTooltip, Qt.UI_FadeTooltip, Qt.UI_FadeMenu):
        app.setEffectEnabled(fx, True)
    from anonbrain.ui.theme import build_style
    app.setStyleSheet(build_style())
    try:                # fonts added in the app, and the list of fonts on this PC
        import threading

        from anonbrain import fonts
        fonts.register_app_fonts()
        threading.Thread(target=fonts.index, daemon=True).start()
    except Exception as e:
        appinfo.log_exception("Loading fonts", e)

    from anonbrain.ui.errors import CrashReporter
    holder = {}
    reporter = CrashReporter(lambda: holder.get("win"))
    appinfo.install_hooks(reporter.report)

    if not appinfo.find_tool("ffmpeg"):
        QMessageBox.warning(None, "FFmpeg not found",
                            "Anon Brain needs FFmpeg to make videos.\n\n"
                            "Reinstall Anon Brain, or install FFmpeg by opening Command Prompt "
                            "and running:\n    winget install ffmpeg\n\nThen restart Anon Brain.")

    from anonbrain.ui.main_window import MainWindow
    win = MainWindow()
    holder["win"] = win
    _listen(app, win)
    if "--tray" in sys.argv and win.tray is not None:
        pass                        # started with Windows: stay in the tray
    else:
        win.show()
    if splash is not None:
        splash.finish(win)
    code = app.exec()
    appinfo.log.info("closed")
    sys.exit(_shut_down(code))


def _shut_down(code: int) -> int:
    """Stop renders and let background work wrap up before Python tears Qt down;
    a thread still running at that point takes the whole app down with an error."""
    from anonbrain.engine import stop_renders
    from anonbrain.ui.common import wait_for_tasks
    stop_renders()
    if not wait_for_tasks(5000):
        from anonbrain.settings import flush_all
        flush_all()
        appinfo.log.info("background work still running at exit; leaving now")
        os._exit(code)
    return code


if __name__ == "__main__":
    main()
