"""Main window: splash screen, then the 5-step wizard, over an animated background."""

import sys
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from ..cleanup import CleanupTable
from ..history import History
from ..library import GameplayLibrary
from ..ocr import read_post
from ..pipeline import Job, Part, spoken_text
from ..presets import Presets, Values
from ..settings import Settings
from . import anim, theme
from .anim import AnimatedStack
from .background import BackgroundWidget
from .common import StepBar, button, label, run_task
from .history_page import HistoryPage
from .layout_page import LayoutPage
from .pages import GameplayPage, PostPage, RenderPage, VoicePage
from .settings_dialog import SettingsPanel
from .splash import SplashPage

ASSETS = Path(__file__).resolve().parents[2] / "assets"


class Events(QObject):
    queue_changed = Signal()
    history_changed = Signal()
    voices_changed = Signal()       # your own voices added / removed / renamed


class AppState:
    """Everything the pages share."""

    def __init__(self, window):
        self.window = window
        self.events = Events()
        self.settings = Settings()
        self.cleanup = CleanupTable()
        self.library = GameplayLibrary()
        self.history = History()
        self.presets = Presets()
        self.voices: list[dict] = []
        self.post_text = None
        self.narration = None
        self.narration_key = None
        self.queue: list[dict] = []      # batch of posts waiting to be made
        self.preview = None              # (job key, segment) of the last quick preview
        self._reading = False

    # --- narration cache ----------------------------------------------------
    def spoken_text(self) -> str:
        return spoken_text(self.build_job(), self.cleanup)

    def _key(self, voice_id):
        return (self.spoken_text(), voice_id, self.settings["voice_model"],
                self.voice_page.pause_seconds(), self.voice_page.speed())

    def narration_matches(self, voice_id) -> bool:
        return self.narration is not None and self.narration_key == self._key(voice_id)

    def set_narration(self, narration, voice_id):
        self.narration, self.narration_key = narration, self._key(voice_id)

    def job_key(self, job: Job):
        return (job.gameplay_mode, job.gameplay_path, spoken_text(job, self.cleanup),
                job.voice_id, job.voice_model, round(job.line_pause, 2), job.post_image,
                round(job.voice_speed, 2))

    # --- jobs -----------------------------------------------------------------
    def build_job(self, item: dict | None = None) -> Job:
        """The job for the post(s) on screen, or for a batch item. A batch item
        can carry a preset: its look then comes from that preset."""
        g, p, v = self.gameplay_page, self.post_page, self.voice_page
        if item is None:
            item = p.snapshot()
        parts = [Part(q["image"], q["text"], q.get("post_text"), q.get("voice", ""))
                 for q in item.get("parts") or []]
        preset = self.presets.get(item["preset"]) if item.get("preset") else None
        common = dict(
            gameplay_mode=g.mode,
            gameplay_path=g.folder if g.mode == "folder" else g.file,
            post_image=item["image"],
            text=item["text"],
            post_text=item["post_text"],
            voice_model=self.settings["voice_model"],
            output_dir=self.settings["output_dir"],
            encoder=self.settings["encoder"] or "auto",
            hook=item["hook"],
            hook_spoken=item["hook_spoken"],
            hook_color=theme.primary(),
            parts=parts,
        )
        if preset is not None:
            return Job(**common, **self.look_from(Values(self.settings, preset)))
        return Job(
            **common,
            voice_id=v.voice_box.currentData() or "",
            line_pause=v.pause_seconds(),
            voice_speed=v.speed(),
            min_length=float(self.settings["min_length"] or 0),
            voice_volume=v.voice_slider.value(),
            **v.job_music(),
            music_volume=v.music_slider.value(),
            reveal=p.reveal_on(),
            reveal_style=p.reveal_style(),
            post_display=self.settings["post_display"] or "post",
            captions=self.caption_style(self.settings),
            clip_only=bool(self.settings["clip_only"]),
            game_volume=int(self.settings["clip_volume"] if self.settings["clip_only"]
                            else self.settings["game_volume"] or 0),
            skip_boring=bool(self.settings["skip_boring"]),
            reuse_footage=bool(self.settings["reuse_footage"]),
            repeat_songs=bool(self.settings["repeat_songs"]),
            **self.layout_page.job_settings(),
            brand=self._brand(),
        )

    def look_from(self, vals) -> dict:
        """Job fields for a look (settings, or settings with a preset over them)."""
        from pathlib import Path

        from ..layout import FORMATS, RESOLUTIONS, output_size
        from .brand import job_brand
        from .layout_page import theme_colors
        fmt = vals["format"] if vals["format"] in FORMATS else "9:16"
        res = vals["resolution"] if vals["resolution"] in RESOLUTIONS else "1080p"
        color = vals["post_border_color"] or "primary"
        music = vals["last_music"] or ""
        folder = (vals["music_folder"] or "") if vals["music_mode"] == "folder" else ""
        if folder and not Path(folder).is_dir():
            folder = ""
        return dict(
            voice_id=vals["last_voice_id"] or "",
            line_pause=float(vals["line_pause"]),
            voice_speed=float(vals["voice_speed"] or 1.0),
            min_length=float(vals["min_length"] or 0),
            voice_volume=int(vals["voice_volume"]),
            music_path=music if music and Path(music).is_file() and not folder else "",
            music_volume=int(vals["music_volume"]),
            music_start=float(vals["music_start"] or 0) if music and not folder else 0.0,
            music_folder=folder,
            reveal=bool(vals["reveal"]),
            reveal_style=vals["reveal_style"] or "fade",
            post_display=vals["post_display"] or "post",
            captions=self.caption_style(vals),
            skip_boring=bool(vals["skip_boring"]),
            reuse_footage=bool(vals["reuse_footage"]),
            repeat_songs=bool(vals["repeat_songs"]),
            fmt=fmt, resolution=res,
            fps=int(vals["fps"] or 30), mirror=vals["mirror"] or "off",
            fit=vals["fit"] or "fill", game_volume=int(vals["game_volume"] or 0),
            post_box=(vals["layouts"] or {}).get(fmt),
            post_round=(vals["post_round"] or 0) / 100,
            shadow=max(vals["post_shadow_strength"] / 100, 0.02) if vals["post_shadow"] else 0.0,
            border=float(vals["post_border_width"]) if vals["post_border"] else 0.0,
            border_style=vals["post_border_style"] or "solid",
            border_color=theme.COLORS.get(color, color),
            border_colors=theme_colors(),
            brand=job_brand(vals, fmt, output_size(fmt, res)),
        )

    @staticmethod
    def caption_style(vals) -> dict:
        """The saved caption look, with its color turned into a real color."""
        from ..captions import DEFAULT_STYLE
        st = {**DEFAULT_STYLE, "color": "primary", **(vals["captions"] or {})}
        st["color"] = theme.COLORS.get(st["color"], st["color"])
        return st

    def _brand(self):
        from ..layout import output_size
        from .brand import job_brand
        lp = self.layout_page
        return job_brand(self.settings, lp.fmt, output_size(lp.fmt, lp.res))

    # --- batch ----------------------------------------------------------------
    def add_to_queue(self, item: dict):
        self.queue.append(item)
        self.events.queue_changed.emit()

    def read_queue(self):
        """Read the text of screenshots added with 'Add many…', one at a time."""
        if self._reading:
            return
        item = next((it for it in self.queue if it["status"] == "reading"), None)
        if item is None:
            return
        self._reading = True

        def done(post):
            item["post_text"], item["text"] = post, post.text
            item["status"] = "ready" if post.text.strip() else "failed"
            if not post.text.strip():
                item["error"] = "No text found in this screenshot"
            finish()

        def fail(msg, e):
            item["status"], item["error"] = "failed", msg
            finish()

        def finish():
            self._reading = False
            self.events.queue_changed.emit()
            self.read_queue()

        run_task(self.window, lambda emit: read_post(Path(item["image"])), done, fail)

    # --- navigation -------------------------------------------------------------
    def open_settings(self, tab=0):
        self.window.open_settings(tab)

    def open_history(self):
        self.window.open_history()

    def busy(self, on: bool):
        self.window.set_busy(on)


class MainWindow(QMainWindow):
    STEPS = ["Gameplay", "Post", "Layout", "Voice & Music", "Render"]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Anon Brain")
        icon = ASSETS / "icon.png"
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.resize(1040, 760)
        self.setMinimumSize(900, 680)

        self.state = st = AppState(self)
        s = st.settings
        anim.ENABLED = bool(s["ui_animations"])
        theme.apply_colors(QApplication.instance(), s["color_primary"], s["color_secondary"],
                           s["color_tertiary"])

        # Animated background behind everything; screens stack on top of it
        self.bg = BackgroundWidget(s)
        outer = QVBoxLayout(self.bg)
        outer.setContentsMargins(0, 0, 0, 0)
        self.screens = AnimatedStack()
        outer.addWidget(self.screens)

        self.splash = SplashPage()
        self.splash.start.connect(lambda: self.show_screen(self.wizard))
        self.splash.settings.connect(lambda: self.open_settings())
        self.splash.history.connect(lambda: self.open_history())
        self.splash.automate.connect(lambda: self.open_automate())
        self.screens.addWidget(self.splash)

        central = QWidget()
        central.setObjectName("Transparent")
        self.wizard = central
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header: logo + settings
        header = QHBoxLayout()
        header.setContentsMargins(36, 18, 28, 6)
        self.logo = button("", "Link", lambda: self.show_screen(self.splash), "Back to start")
        self.logo.setObjectName("Logo")
        header.addWidget(self.logo)
        header.addStretch()
        self.presets_btn = button("★  Presets", tip="Save your look, or apply a saved one "
                                                    "(Ctrl+S saves)")
        header.addWidget(self.presets_btn)
        header.addSpacing(6)
        self.history_btn = button("🕘  History", on_click=self.open_history)
        header.addWidget(self.history_btn)
        header.addSpacing(6)
        self.automate_btn = button("⚡  Automate", on_click=self.open_automate,
                                   tip="Find posts in subreddits, make videos and post them "
                                       "on a schedule")
        header.addWidget(self.automate_btn)
        header.addSpacing(6)
        self.settings_btn = button("⚙  Settings", on_click=lambda: self.open_settings())
        header.addWidget(self.settings_btn)
        header.addSpacing(6)
        self.keys_btn = button("⌨", tip="Keyboard shortcuts (F1)")
        header.addWidget(self.keys_btn)
        root.addLayout(header)

        # Checklist bar
        bar_row = QHBoxLayout()
        bar_row.setContentsMargins(36, 8, 36, 0)
        self.bar = StepBar(self.STEPS)
        self.bar.jump.connect(self.go)
        bar_row.addWidget(self.bar)
        root.addLayout(bar_row)

        # Pages
        self.stack = AnimatedStack()
        st.gameplay_page = GameplayPage(st)
        st.post_page = PostPage(st)
        st.layout_page = LayoutPage(st)
        st.voice_page = VoicePage(st)
        st.render_page = RenderPage(st)
        self.pages = [st.gameplay_page, st.post_page, st.layout_page, st.voice_page,
                      st.render_page]
        for p in self.pages:
            self.stack.addWidget(p)
            p.changed.connect(self.update_nav)
        from .presets_ui import PresetMenu
        self.preset_menu = PresetMenu(self, self.presets_btn)
        from . import shortcuts
        shortcuts.install(self)
        self.keys_btn.clicked.connect(lambda: shortcuts.CheatSheet(self).exec())
        st.render_page.another.connect(self.make_another)
        root.addWidget(self.stack, 1)

        # Footer
        footer = QHBoxLayout()
        footer.setContentsMargins(36, 10, 36, 22)
        self.back_btn = button("←  Back", on_click=lambda: self.go(self.index - 1))
        self.next_btn = button("Next  →", "Primary", lambda: self.go(self.index + 1))
        self.next_btn.setMinimumWidth(150)
        footer.addWidget(self.back_btn)
        footer.addStretch()
        self.hint = label("", "Hint")
        footer.addWidget(self.hint)
        footer.addSpacing(12)
        footer.addWidget(self.next_btn)
        root.addLayout(footer)

        self.screens.addWidget(central)
        self.history_page = HistoryPage(st)
        self.history_page.closed.connect(self.close_settings)
        self.history_page.reuse.connect(self.reuse_post)
        self.screens.addWidget(self.history_page)
        self.settings_panel = SettingsPanel(st)
        self.settings_panel.closed.connect(self.close_settings)
        self.settings_panel.appearance_changed.connect(self.refresh_theme)
        self.screens.addWidget(self.settings_panel)
        from .automate_page import AutomatePage, AutomationRunner
        self.tray = None
        self._quitting = False
        self._told_tray = False
        self.automation = AutomationRunner(st, self)
        self.automate_page = AutomatePage(st, self.automation)
        self.automate_page.closed.connect(self.close_settings)
        self.screens.addWidget(self.automate_page)
        self.automation.changed.connect(self.update_automate_badge)
        self.update_tray()
        self.update_automate_badge()
        self.setCentralWidget(self.bg)

        self.index = 0
        self.visited = {0}
        self.busy = False
        self.return_to = self.splash
        self.go(0)
        self.refresh_theme()
        self.screens.setCurrentWidget(self.splash)
        self.splash.play_intro()

        from .updates_ui import UpdateChecker
        self.updater = UpdateChecker(self)
        self.updater.start()
        self.tour = None
        self._tour_checked = False

    # --- first-run tour ---------------------------------------------------------------
    def start_tour(self):
        from .tour import Tour
        if self.tour is not None or self.busy:
            return
        if not self.isVisible():
            self.show_from_tray()

        def done():
            self.tour = None
            self.state.settings["tour_done"] = True
            self.state.settings.save()
        self.tour = Tour(self, done)
        self.tour.start()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if getattr(self, "updater", None) is not None:
            self.updater.place()
        if getattr(self, "tour", None) is not None:
            self.tour.resize_to_window()

    def show_screen(self, w, direction=None):
        if self.busy and w is self.splash:
            return
        if direction is None:
            order = [self.splash, self.wizard, self.settings_panel, self.history_page,
                     self.automate_page]
            cur = self.screens.currentWidget()
            direction = 1 if order.index(w) > order.index(cur) else -1
        if w is self.wizard:
            self.pages[self.index].on_enter()
            self.update_nav()
        self.screens.transition_to(w, direction, axis="y", ms=460)
        if getattr(self, "updater", None) is not None:     # keep the update note in its spot
            QTimer.singleShot(500, self.updater.place)

    def refresh_theme(self):
        self.logo.setText("")
        self.logo.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 0;"
            " font-family: 'Segoe UI Black', 'Arial Black', 'Segoe UI'; font-size: 15pt;"
            f" font-weight: 900; letter-spacing: 2px; color: {theme.TEXT}; }}")
        self.logo.setText("ANON BRAIN")
        for page in self.pages:
            if hasattr(page, "refresh_theme"):
                page.refresh_theme()
        self.update_nav()
        self.bg.update()
        if getattr(self, "updater", None) is not None:
            self.updater.pill.restyle()

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_tour_checked", True):
            self._tour_checked = True
            if not self.state.settings["tour_done"]:
                QTimer.singleShot(1800, self.start_tour)     # after the splash plays
        if sys.platform == "win32":   # dark title bar on Windows 10/11
            try:
                import ctypes
                hwnd = int(self.winId())
                val = ctypes.c_int(1)
                for attr in (20, 19):
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val),
                                                               ctypes.sizeof(val))
            except Exception:
                pass

    def reload_from_settings(self):
        """A preset was applied: every page re-reads its controls."""
        st = self.state
        for page in (st.gameplay_page, st.post_page, st.layout_page, st.voice_page):
            if hasattr(page, "reload"):
                page.reload()
        st.render_page.reload_min()
        self.update_nav()

    def layout_page_settle(self):
        """Make sure in-progress layout tweaks are saved before a preset is saved."""
        lp = self.state.layout_page
        lp.canvas.settle()
        lp._save_round()

    HINTS = ["Choose a gameplay folder or video", "Add a screenshot and its text", "", "", ""]

    def go(self, i: int):
        if i < 0 and not self.busy:
            self.show_screen(self.splash)
            return
        if self.busy or not 0 <= i < len(self.pages):
            return
        if i > self.index and not all(p.is_complete() for p in self.pages[:i]):
            return
        self.pages[self.index].on_leave()
        self.index = i
        self.visited.add(i)
        direction = 1 if i > self.stack.currentIndex() else -1
        self.stack.transition_to(i, direction)
        self.pages[i].on_enter()
        self.update_nav()

    def update_nav(self):
        done = [p.is_complete() and i in self.visited for i, p in enumerate(self.pages)]
        done[-1] = False
        self.bar.update_state(self.index, done)
        last = self.index == len(self.pages) - 1
        self.back_btn.setText("←  Back" if self.index > 0 else "←  Start screen")
        self.next_btn.setVisible(not last)
        ok = self.pages[self.index].is_complete()
        self.next_btn.setEnabled(ok and not self.busy)
        self.hint.setText("" if ok or last else self.HINTS[self.index])

    def set_busy(self, on: bool):
        self.busy = on
        self.bg.set_busy(on or getattr(self.automation, "running", False))
        self.back_btn.setEnabled(not on)
        self.bar.setEnabled(not on)
        self.settings_btn.setEnabled(not on)
        self.update_nav()

    def make_another(self):
        """Keep gameplay, voice and music; start over at the post."""
        self.state.post_page.reset()
        self.state.render_page.reset()
        self.state.narration = None
        self.go(1)

    def open_settings(self, tab=0):
        if self.screens.currentWidget() is not self.settings_panel:
            self.return_to = self.screens.currentWidget()
        self.settings_panel.open_tab(tab)
        self.show_screen(self.settings_panel, 1)

    def open_history(self):
        if self.screens.currentWidget() not in (self.settings_panel, self.history_page):
            self.return_to = self.screens.currentWidget()
        self.show_screen(self.history_page, 1)

    def open_automate(self):
        if self.screens.currentWidget() not in (self.settings_panel, self.history_page,
                                                self.automate_page):
            self.return_to = self.screens.currentWidget()
        self.automate_page.on_show()
        self.show_screen(self.automate_page, 1)

    def update_automate_badge(self):
        if not hasattr(self, "automate_page"):
            return
        n = len(self.automation.store.waiting())
        run = self.automation.running
        self.bg.set_busy(getattr(self, "busy", False) or bool(run))
        text = "⚡  Automate" + (" …" if run else f" ({n})" if n else "")
        self.automate_btn.setText(text)
        self.splash.automate_btn.setText(text)
        self.update_tray()

    # --- tray --------------------------------------------------------------------
    def tray_wanted(self) -> bool:
        cfg = self.automation.cfg()
        return bool(cfg["enabled"] and cfg["tray"]) and QSystemTrayIcon.isSystemTrayAvailable()

    def update_tray(self):
        if not hasattr(self, "automation"):
            return
        want = self.tray_wanted()
        if want and self.tray is None:
            self.tray = QSystemTrayIcon(self.windowIcon(), self)
            menu = QMenu()
            self._tray_open = QAction("Open Anon Brain", self, triggered=self.show_from_tray)
            self._tray_review = QAction("Review videos", self, triggered=self.review_from_tray)
            self._tray_run = QAction("Run now", self, triggered=lambda: self.automation.start())
            self._tray_pause = QAction("Pause automation", self, triggered=self.pause_automation)
            self._tray_quit = QAction("Quit", self, triggered=self.quit_app)
            for a in (self._tray_open, self._tray_review, self._tray_run, self._tray_pause):
                menu.addAction(a)
            menu.addSeparator()
            menu.addAction(self._tray_quit)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda r: self.show_from_tray()
                                        if r in (QSystemTrayIcon.Trigger,
                                                 QSystemTrayIcon.DoubleClick) else None)
            self.tray.messageClicked.connect(self.review_from_tray)
            self.tray.show()
        elif not want and self.tray is not None:
            self.tray.hide()
            self.tray.deleteLater()
            self.tray = None
        QApplication.instance().setQuitOnLastWindowClosed(not want)
        if self.tray is not None:
            n = len(self.automation.store.waiting())
            self.tray.setToolTip("Anon Brain" + (" · making a video…" if self.automation.running
                                                 else f" · {n} waiting for you" if n else ""))
            self._tray_run.setEnabled(not self.automation.running)

    def tray_message(self, title, text):
        if self.tray is not None:
            self.tray.showMessage(title, text, QSystemTrayIcon.Information, 8000)

    def show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def review_from_tray(self):
        self.show_from_tray()
        if not self.busy:
            self.open_automate()
            self.automate_page.tabs.setCurrentIndex(0)

    def pause_automation(self):
        cfg = self.automation.cfg()
        cfg["enabled"] = False
        self.automation.save_cfg(cfg)
        self.automate_page.load()
        self.update_tray()

    def quit_app(self):
        self._quitting = True
        self.close()
        QApplication.instance().quit()

    def reuse_post(self, entry):
        """Load a post from History into step 2."""
        if self.busy:
            return
        self.state.post_page.load_post(entry.get("image", ""), entry.get("text", ""),
                                       entry.get("hook", ""))
        self.state.render_page.reset()
        self.return_to = self.wizard
        self.show_screen(self.wizard, -1)
        if self.state.gameplay_page.is_complete():
            self.go(1)
        else:
            self.go(0)

    def close_settings(self):
        self.state.settings.save()
        self.show_screen(self.return_to, -1)

    def closeEvent(self, e):
        if not self._quitting and self.tray is not None and self.tray_wanted():
            e.ignore()
            self.hide()
            self.state.voice_page.on_leave()
            if not self._told_tray:
                self._told_tray = True
                self.tray_message("Anon Brain is still running",
                                  "Automation keeps going in the tray. Right-click the icon "
                                  "to quit.")
            return
        self.state.voice_page.on_leave()
        self.state.settings.save()
        super().closeEvent(e)
