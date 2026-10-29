"""Automate: subreddit in, videos out, posted on a schedule.

AutomationRunner keeps time (checks every 30 s), runs a round in the
background, and tells you in the tray. AutomatePage is the screen where you
set it up and review the videos it made.
"""

import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QTime, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from .. import automation as A
from .. import reddit_source as rs
from ..posting import NAMES, ORDER, module
from . import theme
from .background import GlassFrame
from .common import button, cover_thumb, label, run_task

STATE_TEXT = {"waiting": ("Waiting for you", "wait"), "queued": ("Posting soon", "wait"),
              "posting": ("Posting…", "wait"), "posted": ("Posted", "ok"),
              "inbox": ("In your TikTok inbox", "ok"), "private": ("Posted (private)", "ok"),
              "processing": ("Processing", "wait"), "failed": ("Failed", "bad"),
              "skipped": ("Skipped", "off")}
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
AGES = [(0, "Any age"), (24, "Last 24 hours"), (72, "Last 3 days"), (168, "Last week"),
        (720, "Last month")]


def chip(text: str, kind: str) -> QLabel:
    c = label(text)
    from PySide6.QtWidgets import QSizePolicy
    c.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    colors = {"ok": theme.primary(), "wait": "#e8b04a", "bad": "#ff6b6b", "off": theme.MUTED}
    col = colors.get(kind, theme.MUTED)
    c.setStyleSheet(f"QLabel {{ color: {col}; border: 1px solid {col}; border-radius: 9px;"
                    " padding: 1px 8px; font-size: 8.5pt; background: transparent; }")
    return c


def short(n: int) -> str:
    return f"{n / 1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


# --- the clock ----------------------------------------------------------------------
class AutomationRunner(QObject):
    """Checks the schedule, runs rounds in the background, keeps the tray up to date."""
    changed = Signal()                 # queue / status changed: refresh the screen
    progress = Signal(str, float)
    finished = Signal(dict)

    def __init__(self, state, window):
        super().__init__(window)
        self.state, self.window = state, window
        self.store = A.Store()
        self.running = False
        self.posting = False
        self.stop_flag = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(30_000)
        QTimer.singleShot(4000, self.tick)

    def cfg(self) -> dict:
        return A.config(self.state.settings)

    def save_cfg(self, cfg: dict):
        self.state.settings["automation"] = cfg

    def tick(self):
        cfg = self.cfg()
        slot = A.due(cfg, self.store)
        if slot and not self.running and not self.window.busy:
            self.start(slot)

    def problems(self, cfg=None) -> list[str]:
        cfg = cfg or self.cfg()
        out = []
        subs = [s for s in cfg["subs"] if rs.clean_sub(s)]
        if not subs:
            out.append("Add at least one subreddit (Find posts).")
        if not cfg["gameplay"] or not Path(cfg["gameplay"]).is_dir():
            out.append("Choose a gameplay folder (Video).")
        if cfg["preset"] and self.state.presets.get(cfg["preset"]) is None:
            out.append(f"The preset “{cfg['preset']}” was deleted. Pick another (Video).")
        return out

    def job_parts(self, cfg):
        """The look (from the preset) and the rest of the Job, built here on the UI thread."""
        from ..presets import Values
        st = self.state
        preset = st.presets.get(cfg["preset"]) if cfg["preset"] else None
        look = st.look_from(Values(st.settings, preset))
        look["min_length"] = float(cfg["min_length"] or 0)
        base = dict(gameplay_mode="folder", gameplay_path=cfg["gameplay"],
                    voice_model=st.settings["voice_model"],
                    output_dir=str(Path(st.settings["output_dir"]) / "Automate"),
                    encoder=st.settings["encoder"] or "auto", hook_color=theme.primary())
        Path(base["output_dir"]).mkdir(parents=True, exist_ok=True)
        return look, base

    def start(self, slot: str = "") -> str:
        """Run a round now. Returns '' or why it can't."""
        if self.running:
            return "Already running."
        if self.window.busy:
            return "Wait until the video you're making in the wizard is done."
        cfg = self.cfg()
        bad = self.problems(cfg)
        if bad:
            if slot:
                self.store.runs[slot] = time.time()
                self.store.note("Skipped a scheduled run: " + " ".join(bad))
                self.changed.emit()
            return " ".join(bad)
        look, base = self.job_parts(cfg)
        st = self.state
        self.running, self.stop_flag = True, False
        self.changed.emit()

        def work(emit):
            return A.run(cfg, look, base, self.store, st.cleanup, st.library, st.history,
                         emit, lambda: self.stop_flag, slot)

        def done(res):
            self.running = False
            st.events.history_changed.emit()
            self.changed.emit()
            self.finished.emit(res)
            self.notify(res)

        def fail(msg, e):
            self.running = False
            self.store.note(f"Run failed: {msg}")
            self.changed.emit()
            self.finished.emit({"made": [], "errors": [msg], "posted": []})
            self.notify({"made": [], "errors": [msg], "posted": []})

        run_task(self.window, work, done, fail, lambda m, f: self.progress.emit(m, f))
        return ""

    def post(self, item: dict, key: str = ""):
        """Approve (all apps, or one) and post in the background."""
        A.approve(item, key)
        self.store.save()
        self.changed.emit()
        cfg = self.cfg()

        def work(emit):
            return A.post_item(item, cfg, self.store, lambda m: emit(m, 0.5))

        def done(msgs):
            self.changed.emit()
            if msgs:
                self.window.tray_message("Anon Brain", "\n".join(msgs))

        run_task(self.window, work, done, lambda m, e: (self.store.note(m), self.changed.emit()),
                 lambda m, f: self.progress.emit(m, f))

    def notify(self, res):
        made, errors, posted = res["made"], res["errors"], res["posted"]
        waiting = len(self.store.waiting())
        if made:
            text = f"Made {len(made)} video{'s' * (len(made) != 1)}."
            if posted:
                text += " " + "; ".join(posted)
            if waiting:
                text += f" {waiting} waiting for your OK."
        else:
            text = errors[0] if errors else "Nothing new to make."
        self.window.tray_message("Anon Brain automation", text)


# --- one video in the queue ----------------------------------------------------------
class ItemRow(GlassFrame):
    def __init__(self, item: dict, page):
        super().__init__(radius=16, clickable=False)
        self.item, self.page = item, page
        from PySide6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(12)
        thumb = QLabel()
        thumb.setFixedSize(QSize(64, 112))
        pix = cover_thumb(item.get("thumb", ""), 64, 112)
        if pix is not None:
            thumb.setPixmap(pix)
        thumb.setStyleSheet("QLabel { border-radius: 8px; background: rgba(0,0,0,0.35); }")
        row.addWidget(thumb, 0, Qt.AlignTop)
        mid = QVBoxLayout()
        mid.setSpacing(4)
        t = label(item["title"][:110] + ("…" if len(item["title"]) > 110 else ""), "Section",
                  wrap=True)
        t.setStyleSheet("font-size: 10.5pt;")
        mid.addWidget(t)
        secs = int(item.get("length", 0))
        when = time.strftime("%b %d, %I:%M %p", time.localtime(item["created"]))
        mid.addWidget(label(f"r/{item['sub']}  ·  ▲ {short(item['score'])}  ·  💬 "
                            f"{short(item['comments'])}  ·  {secs // 60}:{secs % 60:02d}  ·  "
                            f"{when}", "Hint"))
        chips = QHBoxLayout()
        chips.setSpacing(6)
        for key in ORDER:
            tg = item["targets"].get(key)
            if not tg:
                continue
            text, kind = STATE_TEXT.get(tg["state"], (tg["state"], "off"))
            c = chip(f"{NAMES[key].split()[0]}: {text}", kind)
            tip = tg.get("error") or tg.get("note") or tg.get("url") or ""
            c.setToolTip(tip)
            if tg.get("url"):
                c.setCursor(Qt.PointingHandCursor)
                c.mousePressEvent = lambda e, u=tg["url"]: QDesktopServices.openUrl(QUrl(u))
            chips.addWidget(c)
        if not item["targets"]:
            chips.addWidget(chip("Not set to post anywhere", "off"))
        chips.addStretch()
        mid.addLayout(chips)
        err = next((tg["error"] for tg in item["targets"].values()
                    if tg["state"] == "failed" and tg.get("error")), "")
        if err:
            e = label(err, "Error", wrap=True)
            mid.addWidget(e)
        mid.addStretch()
        row.addLayout(mid, 1)

        btns = QVBoxLayout()
        btns.setSpacing(6)
        exists = Path(item["video"]).is_file()
        play = button("▶ Watch", on_click=lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(item["video"])))
        play.setEnabled(exists)
        btns.addWidget(play)
        states = [tg["state"] for tg in item["targets"].values()]
        if "waiting" in states:
            b = button("✓ Approve && post", "Primary", lambda: page.approve(item),
                       "Post it to every app that's waiting")
            b.setEnabled(exists)
            btns.addWidget(b)
        elif "failed" in states:
            b = button("Try again", "Primary", lambda: page.approve(item))
            b.setEnabled(exists)
            btns.addWidget(b)
        links = QHBoxLayout()
        links.addWidget(button("Caption", "Link", lambda: page.edit_caption(item),
                               "Change the caption before it's posted"))
        if "waiting" in states:
            links.addWidget(button("Skip", "Link", lambda: page.skip(item),
                                   "Don't post this one"))
        links.addWidget(button("Remove", "Link", lambda: page.remove(item)))
        btns.addLayout(links)
        btns.addStretch()
        row.addLayout(btns)


# --- the screen --------------------------------------------------------------------
class AutomatePage(QWidget):
    closed = Signal()

    def __init__(self, state, runner: AutomationRunner):
        super().__init__()
        self.setObjectName("Transparent")
        self.state, self.runner = state, runner
        self.cfg = runner.cfg()
        self._loading = True
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 24, 36, 20)
        root.setSpacing(12)

        head = QHBoxLayout()
        head.addWidget(label("Automate", "Title"))
        head.addSpacing(16)
        self.on_box = QCheckBox("Automation on")
        self.on_box.setToolTip("Run on your schedule. Anon Brain keeps going in the tray "
                               "when you close the window.")
        self.on_box.toggled.connect(self._toggle_on)
        head.addWidget(self.on_box)
        head.addSpacing(10)
        self.next_label = label("", "Hint")
        head.addWidget(self.next_label)
        head.addStretch()
        self.run_btn = button("▶  Run now", on_click=self.run_now,
                              tip="Find posts and make videos right now")
        head.addWidget(self.run_btn)
        self.stop_btn = button("Stop after this one", on_click=self.stop)
        self.stop_btn.setVisible(False)
        head.addWidget(self.stop_btn)
        head.addSpacing(6)
        head.addWidget(button("Done", "Primary", self.finish))
        root.addLayout(head)

        prog = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setFixedHeight(10)
        self.progress.setVisible(False)
        prog.addWidget(self.progress, 1)
        self.status = label("", "Hint")
        prog.addWidget(self.status, 2)
        from .errors import attach_copy_link
        attach_copy_link(self.status)
        root.addLayout(prog)

        card = GlassFrame(radius=22)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(18, 14, 18, 14)
        self.tabs = QTabWidget()
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.addTab(self._queue_tab(), "Review")
        self.tabs.addTab(self._scroll(self._find_tab()), "Find posts")
        self.tabs.addTab(self._scroll(self._video_tab()), "Video")
        self.tabs.addTab(self._scroll(self._post_tab()), "Post to")
        self.tabs.addTab(self._scroll(self._schedule_tab()), "Schedule")
        self.tabs.addTab(self._log_tab(), "Log")
        self.tabs.currentChanged.connect(lambda i: self.refresh_log() if i == 5 else None)
        inner.addWidget(self.tabs)
        root.addWidget(card, 1)

        runner.changed.connect(self.refresh)
        runner.progress.connect(self._progress)
        runner.finished.connect(self._finished)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(400)
        self.save_timer.timeout.connect(self.save)
        self.load()
        self._loading = False
        self.refresh()

    # --- helpers --------------------------------------------------------------------
    def _scroll(self, w):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        w.setObjectName("Transparent")
        area.setWidget(w)
        area.viewport().setAutoFillBackground(False)
        return area

    def _page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)
        return w, lay

    def _changed(self, *_):
        if not self._loading:
            self.save_timer.start()

    def _spin(self, lo, hi, step=1, suffix=""):
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setSingleStep(step)
        if suffix:
            s.setSuffix(suffix)
        s.valueChanged.connect(self._changed)
        s.setMinimumWidth(110)
        return s

    def _words_box(self, empty):
        from PySide6.QtGui import QIntValidator
        e = QLineEdit()
        e.setValidator(QIntValidator(0, 100000))
        e.setPlaceholderText(empty)
        e.setFixedWidth(150)
        e.setToolTip("Leave empty for no limit")
        e.textChanged.connect(self._changed)
        return e

    @staticmethod
    def _words(edit) -> int:
        try:
            return max(0, int(edit.text().strip()))
        except ValueError:
            return 0

    def _combo(self, items):
        c = QComboBox()
        for data, text in items:
            c.addItem(text, data)
        c.currentIndexChanged.connect(self._changed)
        return c

    def _check(self, text, tip=""):
        c = QCheckBox(text)
        if tip:
            c.setToolTip(tip)
        c.toggled.connect(self._changed)
        return c

    @staticmethod
    def _set(combo, data):
        i = combo.findData(data)
        combo.setCurrentIndex(max(0, i))

    # --- Review ------------------------------------------------------------------
    def _queue_tab(self):
        w, lay = self._page()
        top = QHBoxLayout()
        self.queue_title = label("", "Section")
        top.addWidget(self.queue_title)
        top.addStretch()
        self.show_box = QComboBox()
        self.show_box.addItem("Waiting for you", "waiting")
        self.show_box.addItem("Everything", "all")
        self.show_box.currentIndexChanged.connect(lambda _: self.refresh())
        top.addWidget(self.show_box)
        self.approve_all_btn = button("✓ Approve all", on_click=self.approve_all)
        top.addWidget(self.approve_all_btn)
        lay.addLayout(top)
        self.list_area = QScrollArea()
        self.list_area.setWidgetResizable(True)
        self.list_area.setFrameShape(QFrame.NoFrame)
        self.list_host = QWidget()
        self.list_host.setObjectName("Transparent")
        self.list_lay = QVBoxLayout(self.list_host)
        self.list_lay.setContentsMargins(0, 0, 6, 0)
        self.list_lay.setSpacing(8)
        self.list_area.setWidget(self.list_host)
        lay.addWidget(self.list_area, 1)
        return w

    def refresh(self):
        self._busy_ui()
        items = self.runner.store.items
        waiting = self.runner.store.waiting()
        show = self.show_box.currentData()
        rows = waiting if show == "waiting" else items[:60]
        self.tabs.setTabText(0, f"Review ({len(waiting)})" if waiting else "Review")
        self.queue_title.setText(f"{len(waiting)} waiting for your OK" if show == "waiting"
                                 else f"Last {len(rows)} videos")
        self.approve_all_btn.setVisible(len(waiting) > 1)
        while self.list_lay.count():
            it = self.list_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if not rows:
            msg = ("Nothing waiting. Videos set to wait for your review show up here."
                   if show == "waiting" else
                   "No videos yet. Set things up in the other tabs, then click Run now.")
            e = label(msg, "Muted", wrap=True)
            e.setAlignment(Qt.AlignCenter)
            self.list_lay.addSpacing(30)
            self.list_lay.addWidget(e)
        for item in rows:
            self.list_lay.addWidget(ItemRow(item, self))
        self.list_lay.addStretch()
        self._next_text()
        if hasattr(self.state.window, "update_automate_badge"):
            self.state.window.update_automate_badge()

    def approve(self, item):
        self.runner.post(item)

    def approve_all(self):
        for item in list(self.runner.store.waiting()):
            A.approve(item)
        self.runner.store.save()
        for item in [i for i in self.runner.store.items
                     if any(t["state"] == "queued" for t in i["targets"].values())]:
            self.runner.post(item)

    def skip(self, item):
        for t in item["targets"].values():
            if t["state"] == "waiting":
                t["state"] = "skipped"
        self.runner.store.save()
        self.refresh()

    def remove(self, item):
        box = QMessageBox(self)
        box.setWindowTitle("Remove")
        box.setText("Remove this video from the list?")
        keep = box.addButton("Remove, keep the file", QMessageBox.AcceptRole)
        delete = box.addButton("Remove and delete the video", QMessageBox.DestructiveRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() in (keep, delete):
            self.runner.store.remove(item["id"], delete_video=box.clickedButton() is delete)
            self.refresh()

    def edit_caption(self, item):
        from PySide6.QtWidgets import QDialog
        d = QDialog(self)
        d.setWindowTitle("Caption")
        d.setMinimumWidth(480)
        lay = QVBoxLayout(d)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.addWidget(label("Caption", "Title"))
        lay.addWidget(label("Used on every app. YouTube uses the post's title as the video "
                            "title and this as the description.", "Hint", wrap=True))
        ed = QPlainTextEdit(item["caption"])
        ed.setMinimumHeight(140)
        lay.addWidget(ed)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button("Cancel", on_click=d.reject))
        row.addWidget(button("Save", "Primary", d.accept))
        lay.addLayout(row)
        if d.exec():
            item["caption"] = ed.toPlainText().strip()
            self.runner.store.save()

    # --- Find posts -------------------------------------------------------------------
    def _find_tab(self):
        w, lay = self._page()
        lay.addWidget(label("Subreddits", "Section"))
        lay.addWidget(label("One or more, separated by commas. Story subs work best: "
                            "AskReddit, tifu, AmItheAsshole, MaliciousCompliance, "
                            "pettyrevenge, confession.", "Hint", wrap=True))
        self.subs_edit = QLineEdit()
        self.subs_edit.setPlaceholderText("AskReddit, tifu")
        self.subs_edit.textChanged.connect(self._changed)
        lay.addWidget(self.subs_edit)

        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(8)
        self.sort_box = self._combo(rs.SORTS)
        self.period_box = self._combo(rs.PERIODS)
        self.sort_box.currentIndexChanged.connect(
            lambda _: self.period_box.setEnabled(self.sort_box.currentData() == "top"))
        self.rank_box = self._combo([("both", "Upvotes and comments"), ("upvotes", "Upvotes"),
                                     ("comments", "Comments")])
        self.age_box = self._combo(AGES)
        self.min_score = self._spin(0, 1_000_000, 100, " upvotes")
        self.min_comments = self._spin(0, 100_000, 10, " comments")
        self.min_words = self._words_box("any length")
        self.max_words = self._words_box("no limit")
        rows = [("Look at", self.sort_box, "From", self.period_box),
                ("At least", self.min_score, "and", self.min_comments),
                ("Posted", self.age_box, "Pick the best by", self.rank_box),
                ("Words: at least", self.min_words, "at most", self.max_words)]
        for r, (a, wa, b, wb) in enumerate(rows):
            g.addWidget(label(a), r, 0)
            g.addWidget(wa, r, 1)
            g.addWidget(label(b), r, 2)
            g.addWidget(wb, r, 3)
        g.setColumnStretch(4, 1)
        lay.addLayout(g)
        self.len_hint = label("", "Hint", wrap=True)
        lay.addWidget(self.len_hint)

        self.text_only = self._check("Only text posts (skip pictures and links)")
        self.nsfw = self._check("Allow NSFW posts")
        lay.addWidget(self.text_only)
        lay.addWidget(self.nsfw)
        g2 = QGridLayout()
        g2.setHorizontalSpacing(14)
        self.skip_words = QLineEdit()
        self.skip_words.setPlaceholderText("e.g. update, removed, mod post")
        self.skip_words.textChanged.connect(self._changed)
        self.need_words = QLineEdit()
        self.need_words.setPlaceholderText("leave empty for any")
        self.need_words.textChanged.connect(self._changed)
        g2.addWidget(label("Skip posts with"), 0, 0)
        g2.addWidget(self.skip_words, 0, 1)
        g2.addWidget(label("Only posts with"), 1, 0)
        g2.addWidget(self.need_words, 1, 1)
        lay.addLayout(g2)
        cr = QHBoxLayout()
        self.comments_box = self._check("Also read the top comment",
                                        "Read the most-upvoted comment after the post, "
                                        "like a thread")
        cr.addWidget(self.comments_box)
        cr.addWidget(label("read after the post, like a thread", "Hint"))
        cr.addStretch()
        lay.addLayout(cr)

        row = QHBoxLayout()
        self.check_btn = button("🔍  See what it would pick now", on_click=self.check_now)
        row.addWidget(self.check_btn)
        row.addStretch()
        self.reddit_btn = button("Reddit key…", "Link", lambda: self.connect("reddit"),
                                 "Only needed if Reddit stops letting Anon Brain in")
        row.addWidget(self.reddit_btn)
        lay.addLayout(row)
        from PySide6.QtWidgets import QTreeWidget
        self.check_list = QTreeWidget()
        self.check_list.setHeaderLabels(["", "Upvotes", "Comments", "Words", "Post"])
        self.check_list.setRootIsDecorated(False)
        self.check_list.setColumnWidth(0, 190)
        self.check_list.setColumnWidth(1, 80)
        self.check_list.setColumnWidth(2, 90)
        self.check_list.setColumnWidth(3, 70)
        self.check_list.setMinimumHeight(240)
        self.check_list.setVisible(False)
        self.check_list.setStyleSheet(
            "QTreeWidget { background: rgba(0,0,0,0.25); border: 1px solid "
            "rgba(255,255,255,0.1); border-radius: 12px; padding: 4px; }"
            "QTreeWidget::item { padding: 3px 0; }"
            "QHeaderView { background: transparent; border: none; }"
            "QHeaderView::section { background: transparent; color: rgba(255,255,255,0.55);"
            " border: none; border-bottom: 1px solid rgba(255,255,255,0.1); padding: 5px; }")
        self.check_list.itemDoubleClicked.connect(
            lambda it, _c: it.data(0, Qt.UserRole) and
            QDesktopServices.openUrl(QUrl(it.data(0, Qt.UserRole))))
        lay.addWidget(self.check_list)
        lay.addStretch()
        return w

    def check_now(self):
        self.save()
        cfg = self.runner.cfg()
        if not [s for s in cfg["subs"] if rs.clean_sub(s)]:
            self._say("Type a subreddit first.", True)
            return
        look, _ = self.runner.job_parts(cfg)
        self.check_btn.setEnabled(False)
        from PySide6.QtWidgets import QTreeWidgetItem
        self.check_list.clear()
        self.check_list.setVisible(True)
        self.check_list.addTopLevelItem(QTreeWidgetItem(["Looking…"]))
        st = self.state

        def done(res):
            chosen, looked, errors = res
            self.check_btn.setEnabled(True)
            self.check_list.clear()
            ids = {c.id for c in chosen}
            for e in errors:
                self.check_list.addTopLevelItem(QTreeWidgetItem(["⚠  " + e]))
            for c, why in looked[:150]:
                mark = "★ picks this" if c.id in ids else ("✓ fits" if not why else "✕ " + why)
                it = QTreeWidgetItem([mark, short(c.score), short(c.comments), str(c.words),
                                      f"r/{c.sub}: {c.title}"])
                it.setData(0, Qt.UserRole, c.url)
                it.setToolTip(4, "Double-click to open on Reddit")
                for col in (1, 2, 3):
                    it.setTextAlignment(col, Qt.AlignRight | Qt.AlignVCenter)
                if c.id in ids:
                    it.setForeground(0, QColor(theme.primary()))
                elif why:
                    for col in range(5):
                        it.setForeground(col, QColor(140, 146, 154))
                self.check_list.addTopLevelItem(it)
            if not looked and not errors:
                self.check_list.addTopLevelItem(QTreeWidgetItem(["Reddit sent no posts."]))
            n_ok = sum(1 for _, why in looked if not why)
            self._say(f"{n_ok} of {len(looked)} posts fit your filters. ★ = what the next "
                      f"run makes.")

        def fail(msg, e):
            self.check_btn.setEnabled(True)
            self.check_list.clear()
            self.check_list.addTopLevelItem(QTreeWidgetItem(["⚠  " + msg]))

        run_task(self, lambda emit: A.candidates(cfg, look, self.runner.store, st.history),
                 done, fail)

    # --- Video ------------------------------------------------------------------------
    def _video_tab(self):
        w, lay = self._page()
        lay.addWidget(label("Look", "Section"))
        lay.addWidget(label("Voice, music, layout, rounding, border, reveal and your "
                            "watermark all come from a preset. Make one with ★ Presets in "
                            "the wizard.", "Hint", wrap=True))
        row = QHBoxLayout()
        self.preset_box = QComboBox()
        self.preset_box.setMinimumWidth(260)
        self.preset_box.currentIndexChanged.connect(self._changed)
        row.addWidget(label("Preset"))
        row.addWidget(self.preset_box)
        row.addStretch()
        lay.addLayout(row)
        self.theme_box = self._combo([("dark", "Reddit dark"), ("light", "Reddit light")])
        row = QHBoxLayout()
        row.addWidget(label("Post cards"))
        row.addWidget(self.theme_box)
        row.addStretch()
        lay.addLayout(row)
        self.hook_box = self._check("Also show the title big at the start (hook)")
        lay.addWidget(self.hook_box)
        row = QHBoxLayout()
        row.addWidget(label("Always at least"))
        from .pages import MIN_LENGTHS
        self.min_box = self._combo(MIN_LENGTHS)
        row.addWidget(self.min_box)
        row.addWidget(label("short stories keep going with gameplay and music (the voice "
                            "isn't slowed)", "Hint"))
        row.addStretch()
        lay.addLayout(row)
        lay.addWidget(label("Long posts are split into several cards that each fit on the "
                            "screen, read one after another.", "Hint", wrap=True))
        lay.addSpacing(6)
        lay.addWidget(label("Gameplay", "Section"))
        row = QHBoxLayout()
        self.game_label = label("", "Muted")
        row.addWidget(self.game_label, 1)
        row.addWidget(button("Choose folder…", on_click=self.choose_gameplay))
        lay.addLayout(row)
        lay.addWidget(label("Every video uses a fresh, unused slice of your recordings "
                            "(the same library as the wizard).", "Hint", wrap=True))
        lay.addStretch()
        return w

    def fill_presets(self):
        self.preset_box.blockSignals(True)
        self.preset_box.clear()
        self.preset_box.addItem("Your current settings", "")
        for n in self.state.presets.names():
            self.preset_box.addItem(n, n)
        self._set(self.preset_box, self.cfg["preset"])
        self.preset_box.blockSignals(False)

    def choose_gameplay(self):
        d = QFileDialog.getExistingDirectory(self, "Gameplay folder", self.cfg["gameplay"] or
                                             self.state.settings["last_gameplay_folder"] or "")
        if d:
            self.cfg["gameplay"] = d
            self.game_label.setText(d)
            self._changed()

    # --- Post to ----------------------------------------------------------------------
    def _post_tab(self):
        w, lay = self._page()
        self.plat = {}
        for key in ORDER:
            box = GlassFrame(radius=16, clickable=False)
            b = QVBoxLayout(box)
            b.setContentsMargins(16, 12, 16, 12)
            b.setSpacing(6)
            top = QHBoxLayout()
            on = QCheckBox(NAMES[key])
            on.setStyleSheet("font-weight: 700; font-size: 11pt;")
            on.toggled.connect(self._changed)
            top.addWidget(on)
            top.addSpacing(10)
            acct = label("", "Hint")
            top.addWidget(acct)
            top.addStretch()
            conn = button("Connect…", on_click=lambda _=False, k=key: self.connect(k))
            top.addWidget(conn)
            disc = button("Disconnect", "Link", lambda _=False, k=key: self.disconnect(k))
            top.addWidget(disc)
            b.addLayout(top)
            opts = QHBoxLayout()
            auto = QCheckBox("Auto-post (no review)")
            auto.setToolTip("On: posts as soon as the video is made.\n"
                            "Off: waits in Review until you approve it.")
            auto.toggled.connect(self._changed)
            opts.addWidget(auto)
            opts.addSpacing(16)
            extra = None
            if key == "tiktok":
                extra = self._combo([("inbox", "Send to my TikTok inbox (tap Post in the app)"),
                                     ("direct", "Post directly (needs TikTok's approval)")])
            elif key == "youtube":
                extra = self._combo([("public", "Public"), ("unlisted", "Unlisted"),
                                     ("private", "Private")])
            if extra:
                opts.addWidget(extra)
            opts.addStretch()
            b.addLayout(opts)
            hint = label("", "Hint", wrap=True)
            b.addWidget(hint)
            lay.addWidget(box)
            self.plat[key] = dict(on=on, acct=acct, conn=conn, disc=disc, auto=auto,
                                  extra=extra, hint=hint)
        lay.addSpacing(4)
        lay.addWidget(label("Caption", "Section"))
        lay.addWidget(label("{title}, {subreddit}, {sub} (as a hashtag), {author}, {upvotes} "
                            "and {comments} are filled in. You can change any video's caption "
                            "in Review.", "Hint", wrap=True))
        self.caption_edit = QPlainTextEdit()
        self.caption_edit.setFixedHeight(90)
        self.caption_edit.textChanged.connect(self._changed)
        lay.addWidget(self.caption_edit)
        lay.addWidget(label("Reposting other people's posts: credit the subreddit, and know "
                            "that TikTok and YouTube may limit reach on videos they see as "
                            "unoriginal.", "Hint", wrap=True))
        lay.addStretch()
        return w

    def refresh_accounts(self):
        for key, w in self.plat.items():
            mod = module(key)
            ok = mod.connected()
            name = mod.account()
            w["acct"].setText(("Connected" + (f" as {name}" if name else "") + " ✓") if ok
                              else "Not connected")
            w["conn"].setText("Reconnect…" if ok else "Connect…")
            w["disc"].setVisible(ok)
            mode = w["extra"].currentData() if w["extra"] else ""
            hints = {
                "tiktok": ("Lands in your TikTok inbox: you get a notification, tap it, and "
                           "post." if mode == "inbox" else
                           "Until TikTok reviews your app, this only works with a private "
                           "account and posts as “only me”."),
                "youtube": "Shorts can be up to 3 minutes. Google keeps uploads private until "
                           "it reviews your project.",
                "instagram": "Posts as a Reel (also shown in your grid). Needs a Professional "
                             "account linked to a Facebook Page.",
            }
            w["hint"].setText(hints[key])

    def connect(self, key):
        from .accounts_ui import ConnectDialog
        ConnectDialog(key, self).exec()
        self.refresh_accounts()

    def disconnect(self, key):
        if QMessageBox.question(self, "Disconnect", f"Disconnect {NAMES[key]}?") == \
                QMessageBox.Yes:
            module(key).disconnect()
            self.refresh_accounts()

    # --- Schedule ----------------------------------------------------------------------
    def _schedule_tab(self):
        w, lay = self._page()
        lay.addWidget(label("Each time it runs", "Section"))
        row = QHBoxLayout()
        row.addWidget(label("Make"))
        self.per_run = self._spin(1, 10, 1)
        self.per_run.setSuffix(" video(s)")
        row.addWidget(self.per_run)
        row.addWidget(label("from the best new posts it finds", "Muted"))
        row.addStretch()
        lay.addLayout(row)
        lay.addSpacing(4)
        lay.addWidget(label("Times", "Section"))
        lay.addWidget(label("Evenings usually do best on short-video apps.", "Hint", wrap=True))
        row = QHBoxLayout()
        self.times_list = QListWidget()
        self.times_list.setFixedSize(180, 150)
        row.addWidget(self.times_list)
        col = QVBoxLayout()
        self.time_edit = QTimeEdit(QTime(18, 0))
        self.time_edit.setDisplayFormat("h:mm AP")
        col.addWidget(self.time_edit)
        col.addWidget(button("＋ Add time", on_click=self.add_time))
        col.addWidget(button("Remove", "Link", self.remove_time))
        col.addStretch()
        row.addLayout(col)
        row.addStretch()
        lay.addLayout(row)
        lay.addWidget(label("Days", "Section"))
        drow = QHBoxLayout()
        self.day_boxes = []
        for i, d in enumerate(DAYS):
            c = self._check(d)
            self.day_boxes.append(c)
            drow.addWidget(c)
        drow.addStretch()
        lay.addLayout(drow)
        lay.addSpacing(4)
        lay.addWidget(label("While you're away", "Section"))
        self.catch_box = self._check("If my PC was asleep at a time, run when it wakes up "
                                     "(up to 3 hours late)")
        self.tray_box = self._check("Keep running in the tray when I close the window")
        self.startup_box = QCheckBox("Start Anon Brain in the tray when Windows starts")
        self.startup_box.toggled.connect(self._startup)
        lay.addWidget(self.catch_box)
        lay.addWidget(self.tray_box)
        lay.addWidget(self.startup_box)
        lay.addWidget(label("Your PC has to be on (asleep is fine with the box above) for "
                            "automation to run.", "Hint", wrap=True))
        lay.addStretch()
        return w

    def _times(self) -> list[str]:
        return [self.times_list.item(i).data(Qt.UserRole) for i in range(self.times_list.count())]

    def _fill_times(self, times):
        self.times_list.clear()
        for t in sorted(set(times), key=lambda t: A.parse_time(t) or (99, 0)):
            hm = A.parse_time(t)
            if not hm:
                continue
            it = QListWidgetItem(QTime(*hm).toString("h:mm AP"))
            it.setData(Qt.UserRole, f"{hm[0]:02d}:{hm[1]:02d}")
            self.times_list.addItem(it)

    def add_time(self):
        t = self.time_edit.time()
        self._fill_times(self._times() + [f"{t.hour():02d}:{t.minute():02d}"])
        self._changed()

    def remove_time(self):
        for it in self.times_list.selectedItems():
            self.times_list.takeItem(self.times_list.row(it))
        self._changed()

    def _startup(self, on):
        if self._loading:
            return
        ok = set_startup(on)
        if not ok:
            self.startup_box.blockSignals(True)
            self.startup_box.setChecked(startup_enabled())
            self.startup_box.blockSignals(False)

    # --- Log ------------------------------------------------------------------------------
    def _log_tab(self):
        w, lay = self._page()
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        lay.addWidget(self.log_view)
        return w

    def refresh_log(self):
        self.log_view.setPlainText("\n".join(reversed(self.runner.store.log)) or
                                   "Nothing yet.")

    # --- load / save ------------------------------------------------------------------
    def load(self):
        self._loading = True
        c = self.cfg = self.runner.cfg()
        f = c["filters"]
        self.on_box.setChecked(bool(c["enabled"]))
        self.subs_edit.setText(", ".join(c["subs"]))
        self._set(self.sort_box, c["sort"])
        self._set(self.period_box, c["period"])
        self.period_box.setEnabled(c["sort"] == "top")
        self._set(self.rank_box, f["rank"])
        self._set(self.age_box, int(f["max_age_hours"]))
        self.min_score.setValue(int(f["min_score"]))
        self.min_comments.setValue(int(f["min_comments"]))
        self.min_words.setText(str(int(f["min_words"])) if int(f["min_words"] or 0) else "")
        self.max_words.setText(str(int(f["max_words"])) if int(f["max_words"] or 0) else "")
        self.text_only.setChecked(bool(f["text_only"]))
        self.nsfw.setChecked(bool(f["nsfw"]))
        self.skip_words.setText(f["skip_words"])
        self.need_words.setText(f["need_words"])
        self.comments_box.setChecked(int(c["comments"] or 0) > 0)
        self.fill_presets()
        self._set(self.theme_box, c["reddit_theme"])
        self.hook_box.setChecked(bool(c["hook_title"]))
        self._set(self.min_box, int(c["min_length"] or 0))
        if not c["gameplay"] and self.state.settings["last_gameplay_folder"]:
            c["gameplay"] = self.state.settings["last_gameplay_folder"]
        self.game_label.setText(c["gameplay"] or "No folder chosen")
        self.per_run.setValue(int(c["per_run"]))
        for key, w in self.plat.items():
            p = c["platforms"][key]
            w["on"].setChecked(bool(p["on"]))
            w["auto"].setChecked(bool(p["auto"]))
            if key == "tiktok":
                self._set(w["extra"], p.get("mode", "inbox"))
            elif key == "youtube":
                self._set(w["extra"], p.get("privacy", "public"))
        self.caption_edit.setPlainText(c["caption"])
        self._fill_times(c["times"])
        for i, b in enumerate(self.day_boxes):
            b.setChecked(i in c["days"])
        self.catch_box.setChecked(bool(c["catch_up"]))
        self.tray_box.setChecked(bool(c["tray"]))
        self.startup_box.setChecked(startup_enabled())
        self.startup_box.setVisible(sys.platform == "win32")
        self.refresh_accounts()
        self._len_hint()
        self._loading = False

    def save(self):
        c = self.cfg
        c["subs"] = [rs.clean_sub(s) for s in self.subs_edit.text().split(",") if rs.clean_sub(s)]
        c["sort"] = self.sort_box.currentData()
        c["period"] = self.period_box.currentData()
        c["filters"].update(
            rank=self.rank_box.currentData(), max_age_hours=self.age_box.currentData(),
            min_score=self.min_score.value(), min_comments=self.min_comments.value(),
            min_words=self._words(self.min_words), max_words=self._words(self.max_words),
            text_only=self.text_only.isChecked(), nsfw=self.nsfw.isChecked(),
            skip_words=self.skip_words.text(), need_words=self.need_words.text())
        c["comments"] = 1 if self.comments_box.isChecked() else 0
        c["preset"] = self.preset_box.currentData() or ""
        c["reddit_theme"] = self.theme_box.currentData()
        c["hook_title"] = self.hook_box.isChecked()
        c["min_length"] = int(self.min_box.currentData() or 0)
        c["per_run"] = self.per_run.value()
        for key, w in self.plat.items():
            p = c["platforms"][key]
            p["on"], p["auto"] = w["on"].isChecked(), w["auto"].isChecked()
            w["auto"].setEnabled(p["on"])
            if w["extra"]:
                w["extra"].setEnabled(p["on"])
                p["mode" if key == "tiktok" else "privacy"] = w["extra"].currentData()
        c["caption"] = self.caption_edit.toPlainText()
        c["times"] = self._times()
        c["days"] = [i for i, b in enumerate(self.day_boxes) if b.isChecked()]
        c["catch_up"] = self.catch_box.isChecked()
        c["tray"] = self.tray_box.isChecked()
        c["enabled"] = self.on_box.isChecked()
        self.runner.save_cfg(c)
        self.refresh_accounts()
        self._len_hint()
        self._next_text()

    def _len_hint(self):
        keys = [k for k, w in self.plat.items() if w["on"].isChecked()]
        if not keys:
            self.len_hint.setText("Posts too long for the apps you post to are skipped.")
            return
        limit = min(A.PLATFORM_LIMIT[k] for k in keys)
        strict = [NAMES[k] for k in keys if A.PLATFORM_LIMIT[k] == limit]
        self.len_hint.setText(f"Posts that would make a video longer than {int(limit // 60)}:"
                              f"{int(limit % 60):02d} ({' and '.join(strict)}'s limit) are "
                              "skipped. About 150 words is a minute.")

    def _toggle_on(self, on):
        if self._loading:
            return
        if on:
            bad = self.runner.problems(self._preview_cfg())
            if bad:
                self._say(" ".join(bad), True)
        self._changed()
        self.save()
        self.state.window.update_tray()

    def _preview_cfg(self):
        self.save()
        return self.runner.cfg()

    def _next_text(self):
        c = self.runner.cfg()
        if self.runner.running:
            self.next_label.setText("Running…")
        elif not c["enabled"]:
            self.next_label.setText("Off: only runs when you click Run now")
        else:
            nxt = A.next_run(c)
            self.next_label.setText(("Next run: " + nxt.strftime("%a %I:%M %p").replace(" 0", " "))
                                    if nxt else "No times set (Schedule)")

    # --- running -------------------------------------------------------------------------
    def run_now(self):
        self.save()
        why = self.runner.start()
        if why:
            self._say(why, True)

    def stop(self):
        self.runner.stop_flag = True
        self.stop_btn.setEnabled(False)
        self.stop_btn.setText("Stopping after this one…")

    def _busy_ui(self):
        r = self.runner.running
        self.run_btn.setVisible(not r)
        self.stop_btn.setVisible(r)
        if not r:
            self.stop_btn.setEnabled(True)
            self.stop_btn.setText("Stop after this one")
        self.progress.setVisible(r)

    def _progress(self, msg, frac):
        self.progress.setVisible(True)
        self.progress.setValue(int(frac * 1000))
        self.status.setObjectName("Hint")
        self.status.setStyleSheet("")
        self.status.setText(msg)

    def _finished(self, res):
        self.progress.setVisible(False)
        made, errors, posted = res["made"], res["errors"], res["posted"]
        if made:
            text = f"Made {len(made)} video{'s' * (len(made) != 1)}."
            if posted:
                text += "  " + "; ".join(posted)
            self._say(text + (f"  ({len(errors)} problem{'s' * (len(errors) != 1)}, see Log)"
                              if errors else ""))
            if self.runner.store.waiting():
                self.show_box.setCurrentIndex(0)
            else:
                self.show_box.setCurrentIndex(1)
            self.tabs.setCurrentIndex(0)
        else:
            self._say(errors[0] if errors else "Nothing new to make.", True)
        self.refresh()

    def _say(self, text, bad=False):
        from .errors import COPY_LINK
        self.status.setText(text + (f" &nbsp; {COPY_LINK}" if bad else ""))
        self.status.setStyleSheet("color: #ff6b6b;" if bad else f"color: {theme.primary()};")

    def on_show(self):
        self.load()
        self.refresh()

    def finish(self):
        self.save()
        self.closed.emit()


# --- start with Windows -------------------------------------------------------------
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _command() -> str:
    from ..appinfo import frozen
    if frozen():                                    # the installed Anon Brain.exe
        return f'"{Path(sys.executable).resolve()}" --tray'
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe" and (exe.parent / "pythonw.exe").exists():
        exe = exe.parent / "pythonw.exe"
    app = Path(__file__).resolve().parents[2] / "app.py"
    return f'"{exe}" "{app}" --tray'


def startup_enabled() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "Anon Brain")
            return True
    except OSError:
        return False


def set_startup(on: bool) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, "Anon Brain", 0, winreg.REG_SZ, _command())
            else:
                try:
                    winreg.DeleteValue(k, "Anon Brain")
                except OSError:
                    pass
        return True
    except OSError:
        return False
