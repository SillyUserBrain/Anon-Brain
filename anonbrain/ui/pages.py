"""Wizard screens: Gameplay, Post, Voice & Music, Render (Layout is in layout_page.py)."""

import time
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import free_tts
from ..library import LibraryExhausted, find_videos
from ..ocr import read_post
from ..pipeline import gameplay_videos, make_video, spoken_text
from ..settings import cache_dir
from ..voice import MODELS, NO_VOICE, get_key, is_free, narrate
from . import theme
from .anim import animate_value, fade_in
from .background import GlassFrame
from .common import Card, button, fmt_time, label, page_header, run_task
from .post_tools import (
    PostPicker,
    PostTabs,
    clipboard_content,
    clipboard_content_peek,
    draw_posts,
)

VIDEO_FILTER = "Videos (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.wmv *.flv)"
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
AUDIO_FILTER = "Audio (*.mp3 *.wav *.m4a *.ogg *.flac *.aac)"



ADD_VOICE = "__add_voice__"


def vid_is_elevenlabs(vid: str) -> bool:
    if vid.startswith("custom:"):
        from ..custom_voices import get
        v = get(vid)
        return bool(v and v["kind"] == "elevenlabs")
    return not is_free(vid) and vid != NO_VOICE



class WizardPage(QWidget):
    changed = Signal()   # completeness may have changed

    def __init__(self, state):
        super().__init__()
        self.setObjectName("Page")
        self.state = state
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(36, 26, 36, 10)
        self.root.setSpacing(18)

    def is_complete(self) -> bool:
        return True

    def on_enter(self):
        pass

    def on_leave(self):
        pass


# ----------------------------------------------------------------------------
class GameplayPage(WizardPage):
    def __init__(self, state):
        super().__init__(state)
        s = state.settings
        self.mode = s["gameplay_mode"]
        self.folder = s["last_gameplay_folder"]
        self.file = s["last_gameplay_file"]

        self.root.addLayout(page_header(
            "Pick your gameplay",
            "Use a folder of recordings and every video gets a fresh slice, or pick one clip."))

        cards = QHBoxLayout()
        cards.setSpacing(16)

        # Library card
        self.lib_card = Card(clickable=True)
        self.lib_card.clicked.connect(lambda: self.set_mode("folder"))
        self.lib_card.body.addWidget(label("Gameplay library", "Section"))
        self.lib_text = label("", "Muted", wrap=True)
        self.lib_card.body.addWidget(self.lib_text)
        self.folder_label = label("", "Hint", wrap=True)
        self.lib_stats = label("", wrap=True)
        self.lib_card.body.addWidget(self.folder_label)
        self.lib_card.body.addWidget(self.lib_stats)
        self.lib_card.body.addStretch()
        row = QHBoxLayout()
        row.addWidget(button("Choose folder…", on_click=self.choose_folder))
        self.reset_btn = button("Reset used footage", "Link", self.reset_footage,
                                "Forget which parts were used so they can be used again")
        row.addWidget(self.reset_btn)
        row.addStretch()
        self.lib_card.body.addLayout(row)

        # Single clip card
        self.file_card = Card(clickable=True)
        self.file_card.clicked.connect(lambda: self.set_mode("file"))
        self.file_card.body.addWidget(label("Single clip", "Section"))
        self.file_card.body.addWidget(label(
            "Use one video. Long clips still get a random spot each time; short clips loop.",
            "Muted", wrap=True))
        self.file_label = label("", "Hint", wrap=True)
        self.file_card.body.addWidget(self.file_label)
        self.file_card.body.addStretch()
        row = QHBoxLayout()
        row.addWidget(button("Choose video…", on_click=self.choose_file))
        row.addStretch()
        self.file_card.body.addLayout(row)

        cards.addWidget(self.lib_card, 1)
        cards.addWidget(self.file_card, 1)
        self.root.addLayout(cards)
        self.skip = QCheckBox("Skip menus, loading screens and black screens in the footage")
        self.skip.setChecked(bool(s["skip_boring"]))
        self.skip.toggled.connect(lambda v: state.settings.__setitem__("skip_boring", v))
        self.root.addWidget(self.skip)
        self.root.addWidget(label("Each pick is checked in about a second; slices where nothing "
                                  "moves are skipped and never picked again.", "Hint"))
        self.reuse = QCheckBox("Allow repeats: pick from anywhere in the footage, even parts "
                               "already used")
        self.reuse.setToolTip("Off: every video gets footage no other video has used. On: any "
                              "part can come up again, so the folder never runs out.")
        self.reuse.setChecked(bool(s["reuse_footage"]))
        self.reuse.toggled.connect(self._reuse_toggled)
        self.root.addWidget(self.reuse)
        self._reuse_text()
        self.root.addStretch()
        self.set_mode(self.mode, save=False)
        self.refresh()

    def set_mode(self, mode, save=True):
        self.mode = mode
        self.lib_card.set_selected(mode == "folder")
        self.file_card.set_selected(mode == "file")
        if save:
            self.state.settings["gameplay_mode"] = mode
        self.changed.emit()

    def choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Choose your gameplay folder", self.folder or "")
        if d:
            self.folder = d
            self.state.settings["last_gameplay_folder"] = d
            self.set_mode("folder")
            self.refresh()

    def choose_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Choose a gameplay video",
                                           str(Path(self.file).parent) if self.file else "",
                                           VIDEO_FILTER)
        if f:
            self.file = f
            self.state.settings["last_gameplay_file"] = f
            self.set_mode("file")
            self.refresh()

    def refresh(self):
        self.folder_label.setText(self.folder or "No folder chosen yet")
        self.file_label.setText(Path(self.file).name if self.file else "No video chosen yet")
        self.lib_stats.setText("")
        self.reset_btn.setVisible(False)
        if self.folder:
            self.lib_stats.setText("Counting footage…")
            folder = self.folder
            run_task(self, lambda emit: self.state.library.stats(find_videos(Path(folder))),
                     self._show_stats, lambda msg, e: self.lib_stats.setText(f"⚠ {msg}"))
        self.changed.emit()

    def _show_stats(self, st):
        if not st["count"]:
            self.lib_stats.setText("⚠ No videos in this folder")
        else:
            used = st["total"] - st["unused"]
            self.lib_stats.setText(
                f"<b>{st['count']}</b> video{'s' * (st['count'] != 1)} · "
                f"{fmt_time(st['total'])} total · "
                f"<span style='color:{theme.primary()}'>{fmt_time(st['unused'])} unused</span>")
            self.reset_btn.setVisible(used > 1)
        self.changed.emit()

    def reset_footage(self):
        if QMessageBox.question(self, "Reset used footage",
                                "Let Anon Brain reuse every part of the videos in this folder?"
                                ) == QMessageBox.Yes:
            self.state.library.reset(find_videos(Path(self.folder)))
            self.refresh()

    def _reuse_toggled(self, on):
        self.state.settings["reuse_footage"] = on
        self._reuse_text()

    def _reuse_text(self):
        self.lib_text.setText(
            "Pick a folder of recordings, even hour-long ones. Each video uses a random part"
            + (" (repeats allowed)." if self.reuse.isChecked() else " you haven't used before."))

    def reload(self):
        self.skip.setChecked(bool(self.state.settings["skip_boring"]))
        self.reuse.setChecked(bool(self.state.settings["reuse_footage"]))
        self._reuse_text()

    def is_complete(self):
        if self.mode == "folder":
            return bool(self.folder) and Path(self.folder).is_dir()
        return bool(self.file) and Path(self.file).is_file()

    def summary(self) -> str:
        return (f"Library: {Path(self.folder).name}" if self.mode == "folder"
                else f"Clip: {Path(self.file).name}")


# ----------------------------------------------------------------------------
class ImageDrop(QLabel):
    """Shows the post screenshot. Click or drag an image (or a post link) onto it."""
    picked = Signal(str)
    link_dropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(QSize(340, 360))
        self.setCursor(Qt.PointingHandCursor)
        self.setWordWrap(True)
        self.setStyleSheet("QLabel { border: 2px dashed rgba(255,255,255,0.22); border-radius: 18px;"
                           " color: rgba(235,240,235,0.62); background: rgba(8,10,14,0.30); }")
        self.path = ""
        self.clear_image()

    def clear_image(self):
        self.path = ""
        self.setPixmap(QPixmap())
        self.setText("Drop a screenshot here\nor click to choose one\n\n"
                     "or paste one (Ctrl+V), or paste a Reddit / 4chan link")

    def set_image(self, path: str):
        self.path = path
        pix = QPixmap(path)
        if pix.isNull():
            self.clear_image()
            return
        self.setPixmap(pix.scaled(self.width() - 20, self.height() - 20,
                                  Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, e):
        if self.path:
            self.set_image(self.path)
        super().resizeEvent(e)

    def mousePressEvent(self, e):
        f, _ = QFileDialog.getOpenFileName(self, "Choose the post screenshot", "", IMAGE_FILTER)
        if f:
            self.picked.emit(f)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasText():
            e.acceptProposedAction()

    def dropEvent(self, e):
        from ..links import looks_like_link
        urls = e.mimeData().urls()
        if urls and urls[0].isLocalFile():
            self.picked.emit(urls[0].toLocalFile())
            return
        text = urls[0].toString() if urls else e.mimeData().text().strip()
        if looks_like_link(text):
            self.link_dropped.emit(text)


class PostPage(WizardPage):
    def __init__(self, state):
        super().__init__(state)
        self.root.addLayout(page_header(
            "Add the post",
            "Drop in a screenshot, paste one (Ctrl+V), or paste a Reddit / 4chan link. "
            "Add more posts to make a thread."))
        self.clip_box = QCheckBox("No post: just the video  (for movie clips)")
        self.clip_box.setToolTip("No screenshot, no text and no voice: the video from step 1 "
                                 "is used as it is, with its own sound. You can still add "
                                 "a hook, music and your handle.")
        self.clip_box.setChecked(bool(state.settings["clip_only"]))
        self.clip_box.toggled.connect(self._clip_toggled)
        self.root.addWidget(self.clip_box)

        # every post in this video; the editor below shows posts[cur]
        self.posts = [self._blank()]
        self.cur = 0

        row = QHBoxLayout()
        row.setSpacing(20)
        left = QVBoxLayout()
        self.tabs = PostTabs()
        self.tabs.picked.connect(self.show_post)
        self.tabs.add.connect(self.add_post)
        self.tabs.remove.connect(self.remove_post)
        left.addWidget(self.tabs)
        self.drop = ImageDrop()
        self.drop.picked.connect(self.load_image)
        self.drop.link_dropped.connect(self.import_link)
        left.addWidget(self.drop, 1)
        brow = QHBoxLayout()
        brow.addWidget(button("📋  Paste", on_click=self.paste,
                              tip="Paste a screenshot, or a Reddit / 4chan link (Ctrl+V)"))
        self.add_batch_btn = button("＋ Add to batch", on_click=self.add_to_batch,
                                    tip="Save this post to the batch and start the next one")
        brow.addWidget(self.add_batch_btn)
        brow.addWidget(button("Add many screenshots…", on_click=self.add_many,
                              tip="Pick several screenshots at once; each becomes a video"))
        brow.addStretch()
        left.addLayout(brow)
        self.batch_label = label("", "Hint", wrap=True)
        left.addWidget(self.batch_label)
        row.addLayout(left, 5)

        right = QVBoxLayout()
        head = QHBoxLayout()
        self.text_title = label("Text to read", "Section")
        head.addWidget(self.text_title)
        self.read_status = label("", "Muted")
        head.addWidget(self.read_status)
        head.addStretch()
        self.reread_btn = button("Re-read text", "Link", self.read_text)
        head.addWidget(self.reread_btn)
        right.addLayout(head)
        self.dupe = label("", wrap=True)
        self.dupe.setVisible(False)
        self.dupe.linkActivated.connect(lambda _: state.open_history())
        right.addWidget(self.dupe)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("The post's text shows up here. You can also type it in.")
        self.text.textChanged.connect(self._text_changed)
        self.text.installEventFilter(self)
        right.addWidget(self.text, 1)
        right.addWidget(label("Each line is read in order. The > arrows aren't read out loud, "
                              "and shorthand like “tfw” is expanded (edit the list in Settings).",
                              "Hint", wrap=True))
        hook_row = QHBoxLayout()
        self.hook = QLineEdit()
        self.hook.setPlaceholderText("Hook (optional): big text for the first seconds, "
                                     "like “This anon has NO chill”")
        self.hook.textChanged.connect(lambda _: self.changed.emit())
        hook_row.addWidget(self.hook, 1)
        self.hook_spoken = QCheckBox("Read it aloud")
        self.hook_spoken.setChecked(bool(state.settings["hook_spoken"]))
        self.hook_spoken.toggled.connect(lambda v: state.settings.__setitem__("hook_spoken", v))
        hook_row.addWidget(self.hook_spoken)
        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(button("What will the voice say?", "Link", self.show_spoken))
        right.addLayout(bottom)
        row.addLayout(right, 6)
        self.post_area = QWidget()
        self.post_area.setObjectName("Transparent")
        row.setContentsMargins(0, 0, 0, 0)
        self.post_area.setLayout(row)
        self.root.addWidget(self.post_area, 1)
        self.clip_info = GlassFrame(radius=16)
        cl = QVBoxLayout(self.clip_info)
        cl.setContentsMargins(22, 18, 22, 18)
        cl.addWidget(label("Just the video", "Section"))
        cl.addWidget(label(
            "The video you picked in step 1 is used as it is, from start to finish, with its "
            "own sound (set how loud on Voice & Music). No post and no narration.<br><br>"
            "For wide movie clips, try <b>Layout → Fit → Whole video, blurred behind</b> and "
            "<b>24 fps</b>. You can also add a hook below, music, and your handle.",
            "Muted", wrap=True))
        self.root.addWidget(self.clip_info)
        self.clip_spacer = QWidget()
        self.clip_spacer.setObjectName("Transparent")
        self.root.addWidget(self.clip_spacer, 1)
        self.root.addLayout(hook_row)
        self.reread_btn.setVisible(False)
        self.made_key = None          # set once the post on screen has been made
        self._show_clip_mode()

        from PySide6.QtGui import QKeySequence, QShortcut
        sc = QShortcut(QKeySequence.Paste, self)
        sc.setContext(Qt.WidgetWithChildrenShortcut)
        sc.activated.connect(self.paste)

        self._dupe_timer = QTimer(self)
        self._dupe_timer.setSingleShot(True)
        self._dupe_timer.setInterval(500)
        self._dupe_timer.timeout.connect(self._check_dupe)
        state.events.queue_changed.connect(self.refresh_batch)
        self.refresh_batch()

    # --- just the video (movie clips) ------------------------------------------
    def clip_mode(self) -> bool:
        return bool(self.state.settings["clip_only"])

    def _clip_toggled(self, on):
        st = self.state.settings
        st["clip_only"] = on
        self._show_clip_mode()
        self.changed.emit()

    def _show_clip_mode(self):
        on = self.clip_mode()
        self.post_area.setVisible(not on)
        self.clip_info.setVisible(on)
        self.clip_spacer.setVisible(on)
        self.hook_spoken.setVisible(not on)
        self.hook.setPlaceholderText(
            "Hook (optional): big text for the first seconds, like “Wait for it…”" if on else
            "Hook (optional): big text for the first seconds, like “This anon has NO chill”")

    # --- the posts in this video ----------------------------------------------
    @staticmethod
    def _blank() -> dict:
        return {"image": "", "text": "", "post_text": None, "voice": "", "status": ""}

    def _store(self):
        """Editor -> posts[cur]."""
        p = self.posts[self.cur]
        p["image"] = self.drop.path
        p["text"] = self.text.toPlainText()
        p["status"] = self.read_status.text()
        self.state.post_text = self.posts[0]["post_text"]

    def show_post(self, i: int, store: bool = True):
        if store:
            self._store()
        self.cur = max(0, min(i, len(self.posts) - 1))
        p = self.posts[self.cur]
        self.text.blockSignals(True)
        if p["image"] and Path(p["image"]).is_file():
            self.drop.set_image(p["image"])
        else:
            self.drop.clear_image()
        self.text.setPlainText(p["text"])
        self.text.blockSignals(False)
        self.read_status.setText(p.get("status", ""))
        self.reread_btn.setVisible(bool(p["image"]))
        n = len(self.posts)
        self.text_title.setText("Text to read" if n == 1 else f"Post {self.cur + 1}: text to read")
        self.tabs.set_count(n, self.cur)
        fade_in(self.drop, 220)
        self.changed.emit()

    def add_post(self):
        self._store()
        self.posts.append(self._blank())
        self.show_post(len(self.posts) - 1)

    def remove_post(self):
        if len(self.posts) < 2:
            return
        self.posts.pop(self.cur)
        self.cur = min(self.cur, len(self.posts) - 1)
        self.state.post_text = self.posts[0]["post_text"]
        self.show_post(self.cur, store=False)

    def _set_post_text(self, image: str, post):
        """OCR finished for `image` (maybe not the post on screen any more)."""
        for i, p in enumerate(self.posts):
            if p["image"] == image:
                p["post_text"] = post
                p["text"] = post.text
                p["status"] = "· done" if post.text else "· no text found, type it in"
                if i == self.cur:
                    self.text.setPlainText(post.text)
                    self.read_status.setText(p["status"])
        self.state.post_text = self.posts[0]["post_text"]

    # --- loading -------------------------------------------------------------
    def load_image(self, path: str):
        if not Path(path).is_file():
            return
        self.drop.set_image(path)
        p = self.posts[self.cur]
        p["image"], p["post_text"] = path, None
        if self.cur == 0:
            self.state.post_text = None
        self.reread_btn.setVisible(True)
        self.read_text()
        self.changed.emit()

    def load_post(self, image: str, text: str, hook: str = "", hook_spoken=None, post_text=None,
                  parts=None):
        """Fill the page from history or the batch, without losing the text."""
        self.reset()
        self.posts = [{"image": image if image and Path(image).is_file() else "", "text": text,
                       "post_text": post_text, "voice": "", "status": ""}]
        for part in parts or []:
            self.posts.append({"image": part.get("image", ""), "text": part.get("text", ""),
                               "post_text": part.get("post_text"),
                               "voice": part.get("voice", ""), "status": ""})
        self.cur = 0
        self.hook.setText(hook or "")
        if hook_spoken is not None:
            self.hook_spoken.setChecked(bool(hook_spoken))
        self.state.post_text = post_text
        self.show_post(0, store=False)
        for p in self.posts:                    # positions for the reveal
            if p["post_text"] is None and p["image"]:
                path = p["image"]

                def done(post, path=path):
                    for q in self.posts:
                        if q["image"] == path and q["post_text"] is None:
                            q["post_text"] = post
                    self.state.post_text = self.posts[0]["post_text"]
                run_task(self, lambda emit, path=path: read_post(Path(path)), done)
        self.changed.emit()

    def read_text(self):
        path = self.drop.path
        if not path:
            return
        self.read_status.setText("· reading…")
        self.reread_btn.setEnabled(False)

        def done(post):
            self._set_post_text(path, post)
            self.reread_btn.setEnabled(True)

        def fail(msg, e):
            if path == self.drop.path:
                self.read_status.setText("· couldn't read it, type it in")
            self.reread_btn.setEnabled(True)

        run_task(self, lambda emit: read_post(Path(path)), done, fail)

    # --- paste and links -------------------------------------------------------
    def eventFilter(self, obj, e):
        # Ctrl+V in the text box pastes text as usual, but a picture becomes the post
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeySequence
        if obj is self.text and e.type() == QEvent.KeyPress and e.matches(QKeySequence.Paste):
            kind, _ = clipboard_content_peek()
            if kind in ("image", "file"):
                self.paste()
                return True
        return super().eventFilter(obj, e)

    def paste(self):
        kind, value = clipboard_content()
        if kind in ("image", "file"):
            self.load_image(value)
        elif kind == "link":
            self.import_link(value)
        elif kind == "text" and value and not self.text.toPlainText().strip():
            self.text.setPlainText(value)
        else:
            self.read_status.setText("· copy a screenshot or a Reddit / 4chan link first")

    def import_link(self, url: str):
        from ..links import fetch
        self.read_status.setText("· getting the post…")

        def got(fetched):
            if len(fetched.posts) > 1:
                dlg = PostPicker(fetched, self.state.settings, self)
                if not dlg.exec():
                    self.read_status.setText("")
                    return
                posts, theme_ = dlg.chosen()
            else:
                posts, theme_ = fetched.posts, self.state.settings["reddit_theme"]
            run_task(self, lambda emit: draw_posts(posts, theme_, emit), self._use_cards,
                     lambda msg, e: self.read_status.setText(f"· ⚠ {msg}"),
                     lambda m, f: self.read_status.setText(f"· {m}"))

        run_task(self, lambda emit: fetch(url, lambda m: emit(m, 0)), got,
                 lambda msg, e: self.read_status.setText(f"· ⚠ {msg}"),
                 lambda m, f: self.read_status.setText(f"· {m}"))

    def _use_cards(self, cards):
        """Drawn posts replace the post on screen (more become the next posts)."""
        if not cards:
            return
        self._store()
        new = [{"image": png, "text": pt.text, "post_text": pt, "voice": "",
                "status": "· from the link"} for png, pt in cards]
        self.posts[self.cur:self.cur + 1] = new
        self.state.post_text = self.posts[0]["post_text"]
        self.show_post(self.cur, store=False)

    # --- duplicate warning --------------------------------------------------
    def _text_changed(self):
        self.changed.emit()
        self._dupe_timer.start()

    def _check_dupe(self):
        e = self.state.history.find_similar(self.text.toPlainText())
        if e:
            when = time.strftime("%b %d", time.localtime(e["created"]))
            self.dupe.setText(f"<span style='color:#ffcf5c'>⚠ You already made a video from "
                              f"this post on {when}.</span>  <a style='color:{theme.primary()}' "
                              f"href='h'>Open History</a>")
            self.dupe.setVisible(True)
            fade_in(self.dupe, 300)
        else:
            self.dupe.setVisible(False)

    # --- batch ---------------------------------------------------------------
    def snapshot(self) -> dict:
        self._store()
        first = self.posts[0]
        return {"image": first["image"], "text": first["text"],
                "post_text": first["post_text"], "hook": self.hook.text().strip(),
                "hook_spoken": self.hook_spoken.isChecked(), "status": "ready",
                "result": "", "error": "",
                "parts": [{"image": p["image"], "text": p["text"], "post_text": p["post_text"],
                           "voice": p["voice"]} for p in self.posts[1:]
                          if p["image"] and p["text"].strip()]}

    def add_to_batch(self):
        if not self.current_complete():
            self.batch_label.setText("Add a screenshot and its text first.")
            return
        self.state.add_to_queue(self.snapshot())
        self.reset()
        fade_in(self.drop, 350)

    def add_many(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Pick post screenshots", "", IMAGE_FILTER)
        for f in files:
            self.state.add_to_queue({"image": f, "text": "", "post_text": None, "hook": "",
                                     "hook_spoken": self.hook_spoken.isChecked(),
                                     "status": "reading", "result": "", "error": ""})
        self.state.read_queue()

    def refresh_batch(self):
        n = len(self.state.queue)
        reading = sum(1 for q in self.state.queue if q["status"] == "reading")
        if n:
            extra = f" ({reading} still being read)" if reading else ""
            self.batch_label.setText(f"<b>{n}</b> post{'s' * (n != 1)} in the batch{extra}. "
                                     "Review them on the Render step.")
        else:
            self.batch_label.setText("Making several videos? Add each post to the batch.")
        self.add_batch_btn.setText(f"＋ Add to batch ({n})" if n else "＋ Add to batch")
        self.changed.emit()

    # --- misc ----------------------------------------------------------------
    def reveal_on(self) -> bool:
        return bool(self.state.settings["reveal"])

    def reveal_style(self) -> str:
        return self.state.settings["reveal_style"] or "fade"

    def show_spoken(self):
        job = self.state.build_job()
        spoken = spoken_text(job, self.state.cleanup)
        for i, part in enumerate(job.parts):
            spoken += f"\n\n— Post {i + 2} —\n" + self.state.cleanup.apply(part.text)
        QMessageBox.information(self, "What the voice will say", spoken or "(nothing yet)")

    def reset(self):
        self.posts = [self._blank()]
        self.cur = 0
        self.drop.clear_image()
        self.text.clear()
        self.hook.clear()
        self.read_status.setText("")
        self.reread_btn.setVisible(False)
        self.dupe.setVisible(False)
        self.state.post_text = None
        self.made_key = None
        self.tabs.set_count(1, 0)
        self.text_title.setText("Text to read")

    def reload(self):
        st = self.state.settings
        self.hook_spoken.setChecked(bool(st["hook_spoken"]))
        self.clip_box.blockSignals(True)
        self.clip_box.setChecked(bool(st["clip_only"]))
        self.clip_box.blockSignals(False)
        self._show_clip_mode()

    def thread_size(self) -> int:
        return len(self.posts)

    def current_complete(self):
        if self.clip_mode():
            return True
        self._store()
        first = self.posts[0]
        return bool(first["image"]) and bool(first["text"].strip())

    def current_key(self):
        self._store()
        return tuple((p["image"], p["text"], p["voice"]) for p in self.posts) + \
            (self.hook.text().strip(),)

    def is_complete(self):
        return self.current_complete() or bool(self.state.queue)


# ----------------------------------------------------------------------------
class VoicePage(WizardPage):
    def __init__(self, state):
        super().__init__(state)
        s = state.settings
        self.music = s["last_music"] if Path(s["last_music"] or "").is_file() else ""
        self.music_folder = s["music_folder"] or ""
        self.music_mode = "folder" if s["music_mode"] == "folder" and self.music_folder else "song"
        self._sample_song = None      # folder mode: the random pick the preview plays
        self.root.addLayout(page_header(
            "Voice & music", "Pick a narrator, add music, and balance them while you listen."))

        # banner shown when there's no API key
        self.banner = GlassFrame(radius=16)
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(18, 10, 12, 10)
        bl.addWidget(label("Free voices run right on your PC, no account needed. Want "
                           "premium voices? Add an ElevenLabs key in Settings.", wrap=True), 1)
        self.banner_btn = button("Add ElevenLabs key", on_click=lambda: state.open_settings("Voices"))
        bl.addWidget(self.banner_btn)
        self.root.addWidget(self.banner)

        # Narrator card: who reads, how fast, how long between lines
        narr = self.narr_card = Card()
        narr.body.addWidget(label("Narrator", "Section"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        grid.addWidget(label("Voice"), 0, 0)
        self.voice_box = QComboBox()
        self.voice_box.setMinimumWidth(320)
        self.voice_box.currentIndexChanged.connect(self._voice_changed)
        grid.addWidget(self.voice_box, 0, 1)
        self.sample_btn = button("▶ Sample", on_click=self.play_sample,
                                 tip="Hear what this voice sounds like (free)")
        grid.addWidget(self.sample_btn, 0, 2)
        self.voice_status = label("", "Hint", wrap=True)
        grid.addWidget(self.voice_status, 1, 1, 1, 2)
        _set = self.voice_status.setText

        def _status(text, _set=_set, w=self.voice_status):     # no gap when empty
            _set(text)
            w.setVisible(bool(text))
        self.voice_status.setText = _status
        self.voice_status.setVisible(False)

        grid.addWidget(label("Speed"), 2, 0)
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(80, 130)        # percent
        self.speed_slider.setValue(int(round(float(s["voice_speed"] or 1.0) * 100)))
        self.speed_slider.setToolTip("Faster voices make shorter videos. 1.10× to 1.20× "
                                     "is the usual TikTok pace.")
        self.speed_slider.valueChanged.connect(self._speed_changed)
        grid.addWidget(self.speed_slider, 2, 1)
        self.speed_label = label("")
        self.speed_label.setFixedWidth(60)
        self.speed_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(self.speed_label, 2, 2)

        grid.addWidget(label("Pause between lines"), 3, 0)
        self.pause_slider = QSlider(Qt.Horizontal)
        self.pause_slider.setRange(0, 150)          # hundredths of a second
        self.pause_slider.setValue(int(float(s["line_pause"]) * 100))
        self.pause_slider.valueChanged.connect(self._pause_changed)
        grid.addWidget(self.pause_slider, 3, 1)
        self.pause_label = label("")
        self.pause_label.setFixedWidth(60)
        self.pause_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(self.pause_label, 3, 2)
        self.pause_slider.setToolTip("Silence between lines. Inside a line, a comma adds a "
                                     "short breath and “...” a longer pause.")
        narr.body.addLayout(grid)
        self.root.addWidget(narr)

        # Thread: a voice for each post
        self.thread_card = Card()
        head = QHBoxLayout()
        head.addWidget(label("Voices for each post", "Section"))
        head.addStretch()
        head.addWidget(button("Give each post its own voice", "Link", self.auto_voices,
                              tip="Pick a different free voice for every post"))
        self.thread_card.body.addLayout(head)
        self.thread_card.body.addWidget(label(
            "This video is a thread. Post 1 uses the voice above; pick who reads the others.",
            "Hint", wrap=True))
        self.thread_rows = QGridLayout()
        self.thread_rows.setHorizontalSpacing(12)
        self.thread_rows.setColumnStretch(1, 1)
        self.thread_card.body.addLayout(self.thread_rows)
        self.thread_card.setVisible(False)
        self.root.addWidget(self.thread_card)

        # Music and the mix
        mixer = Card()
        mhead = QHBoxLayout()
        mhead.addWidget(label("Music & mix", "Section"))
        mhead.addSpacing(10)
        self.music_label = label("", "Muted")
        mhead.addWidget(self.music_label, 1)
        mhead.addWidget(button("Choose song…", on_click=self.choose_music))
        mhead.addWidget(button("Choose folder…", on_click=self.choose_music_folder,
                               tip="A folder of songs: every video gets a random one, "
                                   "from a random part"))
        self.clear_music_btn = button("No music", "Link", lambda: self.set_music(""))
        mhead.addWidget(self.clear_music_btn)
        mixer.body.addLayout(mhead)
        # a folder of songs: nothing to pick here, each video picks for itself
        self.folder_box = QWidget()
        self.folder_box.setObjectName("Transparent")
        fb = QHBoxLayout(self.folder_box)
        fb.setContentsMargins(0, 2, 0, 4)
        fcol = QVBoxLayout()
        fcol.setSpacing(4)
        self.folder_hint = label("", "Hint", wrap=True)
        fcol.addWidget(self.folder_hint)
        self.repeat_box = QCheckBox("Allow repeats (any song, even one that just played)")
        self.repeat_box.setChecked(bool(s["repeat_songs"]))
        self.repeat_box.toggled.connect(self._repeats_toggled)
        fcol.addWidget(self.repeat_box)
        fb.addLayout(fcol, 1)
        fb.addWidget(button("▶ Hear a random pick", "Link", self.hear_random,
                            tip="Play a random song from the folder, from a random part, "
                                "the way a video would"))
        mixer.body.addWidget(self.folder_box)
        # which part of the song plays
        from .song_strip import SongStrip
        from .song_strip import fmt as tfmt
        self._tfmt = tfmt
        self.music_start = float(s["music_start"] or 0)
        self.song_box = QWidget()
        self.song_box.setObjectName("Transparent")
        sb = QVBoxLayout(self.song_box)
        sb.setContentsMargins(0, 2, 0, 4)
        sb.setSpacing(4)
        self.strip = SongStrip()
        self.strip.start_changed.connect(self._song_moving)
        self.strip.start_picked.connect(self._song_picked)
        sb.addWidget(self.strip)
        srow = QHBoxLayout()
        self.song_label = label("", "Hint")
        srow.addWidget(self.song_label, 1)
        self.hear_btn = button("▶ Hear this part", "Link", self.hear_part,
                               tip="Play the song from the start of the highlighted part")
        srow.addWidget(self.hear_btn)
        self.song_reset_btn = button("From the start", "Link", lambda: self._song_picked(0.0, True))
        srow.addWidget(self.song_reset_btn)
        sb.addLayout(srow)
        self.song_box.setMinimumHeight(88)
        mixer.body.addWidget(self.song_box)
        vrow = QHBoxLayout()
        vrow.setSpacing(10)
        self.voice_slider, self.voice_pct = self._slider(vrow, "Voice", s["voice_volume"])
        vrow.addSpacing(14)
        self.music_slider, self.music_pct = self._slider(vrow, "Music", s["music_volume"])
        vrow.addSpacing(14)
        self.game_slider, self.game_pct = self._slider(vrow, "Video sound",
                                                       s["game_volume"] or 0)
        self.game_slider.setToolTip("The gameplay's or clip's own sound. Usually off under a "
                                    "narrator; turn it up for movie clips.")
        self.game_slider.valueChanged.connect(self._game_volume_changed)
        vrow.addSpacing(14)
        self.preview_btn = button("▶  Preview mix", "Primary", self.toggle_preview)
        vrow.addWidget(self.preview_btn)
        mixer.body.addLayout(vrow)
        self.preview_status = label("Sliders change the sound live while the preview plays.",
                                    "Hint")
        mixer.body.addWidget(self.preview_status)
        self.root.addWidget(mixer)
        self.root.addStretch()

        # Players: one for voice, one for music, one for samples
        self.voice_out, self.music_out, self.sample_out = QAudioOutput(), QAudioOutput(), QAudioOutput()
        self.voice_player, self.music_player, self.sample_player = QMediaPlayer(), QMediaPlayer(), QMediaPlayer()
        self.voice_player.setAudioOutput(self.voice_out)
        self.music_player.setAudioOutput(self.music_out)
        self.sample_player.setAudioOutput(self.sample_out)
        self.music_player.setLoops(QMediaPlayer.Infinite)
        self.music_player.mediaStatusChanged.connect(self._music_status)
        self.voice_player.mediaStatusChanged.connect(self._voice_status_changed)
        self.voice_slider.valueChanged.connect(self._volumes_changed)
        self.music_slider.valueChanged.connect(self._volumes_changed)
        self.playing = False
        self._volumes_changed()
        self._pause_changed()
        self._speed_changed()
        self._show_music()

    def _slider(self, row, name, value):
        lab = label(name)
        row.addWidget(lab)
        sl = QSlider(Qt.Horizontal)
        sl.setRange(0, 100)
        sl.setValue(int(value))
        row.addWidget(sl, 1)
        pct = label(f"{int(value)}%")
        pct.setFixedWidth(46)
        pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(pct)
        sl.parts = (lab, sl, pct)
        return sl, pct

    def _volume_key(self) -> str:
        """Clips and narrated videos keep their own "video sound" level (a movie clip
        wants its sound; gameplay under a narrator usually doesn't)."""
        return "clip_volume" if self.state.post_page.clip_mode() else "game_volume"

    def game_volume(self) -> int:
        return int(self.game_slider.value())

    def _game_volume_changed(self, v):
        self.game_pct.setText(f"{v}%" if v else "Off")
        if not getattr(self, "_loading_volume", False):
            self.state.settings[self._volume_key()] = int(v)
            self.changed.emit()

    def _load_game_volume(self):
        st = self.state.settings
        v = st[self._volume_key()]
        self._loading_volume = True
        self.game_slider.setValue(int(v if v is not None else 0))
        self._loading_volume = False
        self.game_pct.setText(f"{self.game_slider.value()}%" if self.game_slider.value()
                              else "Off")

    def show_clip_mode(self):
        """Just the video: no narrator, so only music and the video's own sound."""
        clip = self.state.post_page.clip_mode()
        self.narr_card.setVisible(not clip)
        for w in self.voice_slider.parts:
            w.setVisible(not clip)
        self.preview_btn.setVisible(not clip)
        self.preview_status.setVisible(not clip)
        if clip:
            self.thread_card.setVisible(False)
            self.banner.setVisible(False)

    # --- voices ------------------------------------------------------------
    def on_enter(self):
        self.fill_thread_voices()
        self._load_game_volume()
        self.strip.set_span(self._song_span())
        has_key = bool(get_key())
        self.banner.setVisible(not has_key)
        self.show_clip_mode()
        if has_key and not self.state.voices:
            self.load_voices()
        else:
            self.fill_voices()

    def reload(self):
        s = self.state.settings
        self.stop_preview()
        for sl, key in ((self.voice_slider, "voice_volume"), (self.music_slider, "music_volume")):
            sl.setValue(int(s[key]))
        self.pause_slider.setValue(int(float(s["line_pause"]) * 100))
        self.speed_slider.setValue(int(round(float(s["voice_speed"] or 1.0) * 100)))
        self.music = s["last_music"] if Path(s["last_music"] or "").is_file() else ""
        self.music_start = float(s["music_start"] or 0)
        self.music_folder = s["music_folder"] or ""
        self.music_mode = "folder" if s["music_mode"] == "folder" and self.music_folder else "song"
        self.repeat_box.blockSignals(True)
        self.repeat_box.setChecked(bool(s["repeat_songs"]))
        self.repeat_box.blockSignals(False)
        self._show_music()
        self.voice_box.blockSignals(True)
        self.voice_box.setCurrentIndex(-1)
        self.voice_box.blockSignals(False)
        self.fill_voices()

    def fill_voice_list(self, box: QComboBox, same_label: str | None = None):
        """Every voice the app knows (for the per-post pickers)."""
        def header(text):
            box.addItem(text, None)
            box.model().item(box.count() - 1).setEnabled(False)
        if same_label:
            box.addItem(same_label, "")
        from ..custom_voices import PREFIX as CUSTOM
        from ..custom_voices import all_voices
        mine = all_voices(self.state.settings)
        if mine:
            header("Your voices")
            for v in mine:
                box.addItem("   " + v["name"], CUSTOM + v["id"])
        if self.state.voices:
            header("ElevenLabs voices")
            for v in self.state.voices:
                box.addItem("   " + v["name"], v["id"])
        header("Free voices")
        for vid, name in free_tts.VOICES.items():
            box.addItem("   " + name, free_tts.PREFIX + vid)

    def fill_thread_voices(self):
        pp = self.state.post_page
        pp._store()
        while self.thread_rows.count():
            w = self.thread_rows.takeAt(0).widget()
            if w:
                w.deleteLater()
        posts = pp.posts
        self.thread_card.setVisible(len(posts) > 1)
        if len(posts) < 2:
            return
        for i, p in enumerate(posts[1:], start=1):
            first = next((l.strip(" >") for l in p["text"].splitlines() if l.strip()), "")
            self.thread_rows.addWidget(label(f"Post {i + 1}"), i, 0)
            box = QComboBox()
            self.fill_voice_list(box, "Same as the main voice")
            box.setCurrentIndex(max(0, box.findData(p.get("voice", ""))))
            box.currentIndexChanged.connect(
                lambda _=0, b=box, post=p: self._thread_voice(post, b.currentData()))
            self.thread_rows.addWidget(box, i, 1)
            self.thread_rows.addWidget(label(first[:40] + ("…" if len(first) > 40 else ""),
                                             "Muted"), i, 2)

    def _thread_voice(self, post, vid):
        if vid is None:
            return
        post["voice"] = vid
        self.stop_preview()

    def auto_voices(self):
        """A different free voice for each post (never the main one)."""
        main = self.voice_box.currentData() or ""
        pool = [free_tts.PREFIX + v for v in free_tts.VOICES if free_tts.PREFIX + v != main]
        for i, p in enumerate(self.state.post_page.posts[1:]):
            p["voice"] = pool[i % len(pool)] if pool else ""
        self.fill_thread_voices()

    def load_voices(self):
        self.voice_status.setText("Loading your ElevenLabs voices…")

        def done(voices):
            self.state.voices = voices
            self.voice_status.setText("")
            self.fill_voices()

        def fail(msg, e):
            self.voice_status.setText(f"⚠ {msg}")
            self.fill_voices()

        from ..voice import list_voices
        run_task(self, lambda emit: list_voices(), done, fail)

    def fill_voices(self):
        want = self.voice_box.currentData() or self.state.settings["last_voice_id"]
        box = self.voice_box
        box.blockSignals(True)
        box.clear()

        def header(text):
            box.addItem(text, None)
            box.model().item(box.count() - 1).setEnabled(False)

        if self.state.voices:
            header("ElevenLabs voices")
            for v in self.state.voices:
                tag = {"cloned": " · your clone", "generated": " · your design",
                       "professional": " · pro clone"}.get(v["category"], "")
                box.addItem("   " + v["name"] + tag, v["id"])
        header("Your voices")
        from ..custom_voices import PREFIX as CUSTOM
        from ..custom_voices import all_voices, describe
        for v in all_voices(self.state.settings):
            box.addItem(f"   {v['name']} · {describe(v)}", CUSTOM + v["id"])
        box.addItem("   ＋ Add your own voice…", ADD_VOICE)
        header("Free voices (run on your PC)")
        for vid, name in free_tts.VOICES.items():
            box.addItem("   " + name, free_tts.PREFIX + vid)
        header("Other")
        box.addItem("   No voice (silent, timed text)", NO_VOICE)
        idx = box.findData(want)
        if idx < 0 or want == ADD_VOICE:
            idx = box.findData(free_tts.DEFAULT)
        box.setCurrentIndex(idx)
        self._last_index = idx
        self.voice_box.blockSignals(False)
        self._voice_changed()

    def _voice_changed(self):
        vid = self.voice_box.currentData()
        if vid == ADD_VOICE:
            # not a voice: open the Add a voice window, then pick what was added
            box = self.voice_box
            box.blockSignals(True)
            box.setCurrentIndex(getattr(self, "_last_index", box.findData(free_tts.DEFAULT)))
            box.blockSignals(False)
            from .voices_ui import add_voice
            v = add_voice(self.state, self, self._play_sample_file)
            if v:
                from ..custom_voices import PREFIX
                self.state.settings["last_voice_id"] = PREFIX + v["id"]
                box.blockSignals(True)
                box.setCurrentIndex(-1)
                box.blockSignals(False)
                self.fill_voices()
            return
        self._last_index = self.voice_box.currentIndex()
        if vid and vid != NO_VOICE:
            self.state.settings["last_voice_id"] = vid
        self.sample_btn.setEnabled(bool(self._sample_url()) or is_free(vid or "")
                                   or (vid or "").startswith("custom:"))
        if vid and is_free(vid) and not free_tts.is_downloaded():
            self.voice_status.setText("Free voices download once (about 120 MB) the first time "
                                      "you use them. After that they work offline.")
        elif self.voice_status.text().startswith("Free voices download"):
            self.voice_status.setText("")
        self.stop_preview()

    def _sample_url(self):
        vid = self.voice_box.currentData()
        for v in self.state.voices:
            if v["id"] == vid:
                return v.get("preview_url")
        return None

    def play_sample(self):
        self.stop_preview()
        self.sample_out.setVolume(self.voice_slider.value() / 100)
        vid = self.voice_box.currentData() or ""
        if vid.startswith("custom:"):
            from ..custom_voices import get
            v = get(vid)
            if v:
                from .voices_ui import sample_voice
                sample_voice(self, self.state, v, self._play_sample_file)
            return
        if is_free(vid):
            wav = cache_dir() / f"sample_{vid.removeprefix(free_tts.PREFIX)}.wav"
            if wav.exists():
                self._play_sample_file(wav)
                return
            self.sample_btn.setEnabled(False)
            self.voice_status.setText("Getting the sample ready…")

            def done(path):
                self.sample_btn.setEnabled(True)
                self.voice_status.setText("")
                self._play_sample_file(path)

            def fail(msg, e):
                self.sample_btn.setEnabled(True)
                self.voice_status.setText(f"⚠ {msg}")

            run_task(self, lambda emit: free_tts.synthesize(
                "Be me. Find a post. Turn it into a video.", vid, wav, status=emit),
                done, fail, lambda m, f: self.voice_status.setText(m))
            return
        url = self._sample_url()
        if url:
            self.sample_player.setSource(QUrl(url))
            self.sample_player.play()

    def _play_sample_file(self, path):
        self.sample_player.setSource(QUrl.fromLocalFile(str(path)))
        self.sample_player.play()

    def speed(self) -> float:
        return self.speed_slider.value() / 100

    def _speed_changed(self, _=None):
        self.speed_label.setText(f"{self.speed():.2f}×")
        self.state.settings.values["voice_speed"] = self.speed()
        if self.playing:
            self.stop_preview()
            self.preview_status.setText("Speed changed. Hit Preview to hear it.")

    def pause_seconds(self) -> float:
        return self.pause_slider.value() / 100

    def _pause_changed(self):
        self.pause_label.setText(f"{self.pause_seconds():.2f}s")
        self.state.settings.values["line_pause"] = self.pause_seconds()
        if self.playing:
            self.stop_preview()
            self.preview_status.setText("Pause changed. Hit Preview to hear it.")

    def voice_name(self) -> str:
        return (self.voice_box.currentText() or "No voice").strip()

    # --- music ---------------------------------------------------------------
    def choose_music(self):
        f, _ = QFileDialog.getOpenFileName(self, "Choose background music",
                                           str(Path(self.music).parent) if self.music else "",
                                           AUDIO_FILTER)
        if f:
            self.set_music(f)

    def set_music(self, path, save=True):
        """One song (or "" for no music)."""
        self.stop_preview()
        changed = path != self.music
        self.music = path
        self.music_mode = "song"
        if save:
            if changed:
                self.music_start = 0.0
                self.state.settings.values["music_start"] = 0.0
            self.state.settings.values["music_mode"] = "song"
            self.state.settings["last_music"] = path
        self._show_music()

    def choose_music_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Choose a folder of songs",
                                             self.music_folder or "")
        if d:
            self.set_music_folder(d)

    def set_music_folder(self, folder, save=True):
        self.stop_preview()
        self.music_folder = folder
        self.music_mode = "folder"
        self._sample_song = None
        if save:
            self.state.settings.values["music_folder"] = folder
            self.state.settings["music_mode"] = "folder"
        self._show_music()

    def has_music(self) -> bool:
        return bool(self.music_folder if self.music_mode == "folder" else self.music)

    def job_music(self) -> dict:
        """The Job's music fields."""
        if self.music_mode == "folder":
            return dict(music_path="", music_start=0.0, music_folder=self.music_folder)
        return dict(music_path=self.music, music_start=float(self.music_start or 0),
                    music_folder="")

    def _show_music(self):
        from ..music import find_songs
        folder = self.music_mode == "folder"
        on = self.has_music()
        if folder:
            n = len(find_songs(self.music_folder))
            self.music_label.setText(f"📁 {Path(self.music_folder).name} · "
                                     + (f"{n} song{'s' * (n != 1)}" if n else "⚠ no songs"))
            self.folder_hint.setText(
                ("Every video gets a random song from this folder, starting at a random part."
                 + ("" if self.repeat_box.isChecked() else
                    " A song won't repeat until the others (up to 10) have had a turn."))
                if n else "No songs in this folder yet. Add some MP3, WAV, M4A or FLAC files.")
            self.repeat_box.setVisible(n > 1)
        else:
            self.music_label.setText(Path(self.music).name if self.music else "No music")
        self.clear_music_btn.setVisible(on)
        self.music_slider.setEnabled(on)
        self.folder_box.setVisible(folder)
        self.song_box.setVisible(not folder and bool(self.music))
        if not folder:
            self.strip.set_song(self.music, self.music_start)
            self._song_text()
        self.changed.emit()

    def _repeats_toggled(self, on):
        self.state.settings["repeat_songs"] = on
        self._show_music()

    def summary_music(self) -> str:
        if self.music_mode == "folder":
            return (f"Random song from {Path(self.music_folder).name}"
                    + (" (repeats allowed)" if self.repeat_box.isChecked() else ""))
        return Path(self.music).name if self.music else "No music"

    # --- which part of the song ---------------------------------------------
    def _song_span(self) -> float:
        g = getattr(self.state.render_page, "_length", None) if hasattr(
            self.state, "render_page") else None
        if g is not None:
            return g.seconds
        nr = self.state.narration
        return nr.length + 1.6 if nr is not None else 45.0

    def _song_text(self):
        t = self._tfmt
        self.song_label.setText(
            f"Song starts at {t(self.music_start)} · drag the highlighted part to pick another "
            "part" if self.music_start >= 0.5 else
            "Song starts at the beginning · drag the highlighted part to pick another part")
        self.song_reset_btn.setVisible(self.music_start >= 0.5)

    def _song_moving(self, start):
        self.music_start = start
        self._song_text()

    def _song_picked(self, start, move_strip=False):
        self.music_start = float(start)
        if move_strip:
            self.strip.start = self.music_start
            self.strip.update()
        self.state.settings["music_start"] = self.music_start
        self._song_text()
        if self.music_player.playbackState() == QMediaPlayer.PlayingState:
            self.music_player.setPosition(int(self.music_start * 1000))

    def hear_part(self):
        if self.playing:
            self.stop_preview()
        self.sample_player.stop()
        self.playing = True
        self.preview_btn.setText("■  Stop")
        self.preview_status.setText("Playing the music from your chosen part…")
        if not self._play_music():
            self.stop_preview(keep_status=True)

    def hear_random(self):
        self._sample_song = None
        self.hear_part()

    def _preview_song(self):
        """(song, start) the preview plays. In folder mode: a random pick, kept until
        you ask for another, so the sliders can be set against one song."""
        if self.music_mode != "folder":
            return self.music, self.music_start
        if self._sample_song is None:
            from ..music import pick
            try:
                self._sample_song = pick(self.music_folder, self._song_span(), record=False)
            except Exception as e:
                self.preview_status.setText(f"⚠ {e}")
                return None, 0.0
        return self._sample_song

    def _play_music(self) -> bool:
        song, start = self._preview_song()
        if not song:
            return False
        if self.music_mode == "folder":
            self.preview_status.setText(
                f"Playing {Path(song).name} from {self._tfmt(start)}. Each video picks its "
                "own song.")
        self._seek_ms = int(start * 1000)
        self.music_player.setSource(QUrl.fromLocalFile(str(song)))
        self.music_player.setPosition(self._seek_ms)
        self.music_player.play()
        return True

    def _music_status(self, status):
        if getattr(self, "_seek_ms", None) and status in (QMediaPlayer.LoadedMedia,
                                                          QMediaPlayer.BufferedMedia):
            self.music_player.setPosition(self._seek_ms)
            self._seek_ms = None

    # --- live preview ------------------------------------------------------
    def _volumes_changed(self):
        v, m = self.voice_slider.value(), self.music_slider.value()
        self.voice_pct.setText(f"{v}%")
        self.music_pct.setText(f"{m}%")
        self.voice_out.setVolume(v / 100)
        self.music_out.setVolume(m / 100)
        self.sample_out.setVolume(v / 100)
        self.state.settings.values.update(voice_volume=v, music_volume=m)

    def toggle_preview(self):
        if self.playing:
            self.stop_preview()
            return
        self.sample_player.stop()
        text = self.state.spoken_text()
        if not text.strip():
            self.preview_status.setText("Add the post's text first (step 2).")
            return
        vid = self.voice_box.currentData() or NO_VOICE
        if vid == NO_VOICE:
            self._start_playback(None)
            return
        job = self.state.build_job()
        if job.parts:                       # a thread: every post, each with its voice
            from ..pipeline import narrate_thread
            self.preview_btn.setEnabled(False)
            self.preview_status.setText("Making the voices…")

            def done_t(narration):
                self.preview_btn.setEnabled(True)
                self._start_playback(narration.audio)

            def fail_t(msg, e):
                self.preview_btn.setEnabled(True)
                self.preview_status.setText(f"⚠ {msg}")
            run_task(self, lambda emit: narrate_thread(job, self.state.cleanup, emit), done_t,
                     fail_t, lambda m, f: self.preview_status.setText(m))
            return
        if self.state.narration_matches(vid):
            self._start_playback(self.state.narration.audio)
            return
        self.preview_btn.setEnabled(False)
        if not vid_is_elevenlabs(vid):
            self.preview_status.setText("Making the voice…")
        else:
            self.preview_status.setText(f"Making the voice… (uses about {len(text)} ElevenLabs "
                                        "characters, only once per post)")
        model = self.state.settings["voice_model"]
        pause = self.pause_seconds()

        def done(narration):
            self.state.set_narration(narration, vid)
            self.preview_btn.setEnabled(True)
            self._start_playback(narration.audio)

        def fail(msg, e):
            self.preview_btn.setEnabled(True)
            self.preview_status.setText(f"⚠ {msg}")

        speed = self.speed()
        run_task(self, lambda emit: narrate(text, vid, model, pause, emit, speed=speed),
                 done, fail,
                 lambda m, f: self.preview_status.setText(m))

    def _start_playback(self, audio):
        self.playing = True
        self.preview_btn.setText("■  Stop")
        if audio:
            self.voice_player.setSource(QUrl.fromLocalFile(str(audio)))
            self.voice_player.play()
            self.preview_status.setText("Playing… drag the sliders to balance it.")
        else:
            self.preview_status.setText("No voice selected, playing music only.")
        if self.has_music():
            self._play_music()
        elif not audio:
            self.preview_status.setText("Nothing to play: pick a voice or some music.")
            self.stop_preview(keep_status=True)

    def _voice_status_changed(self, status):
        if status == QMediaPlayer.EndOfMedia and self.playing:
            self.stop_preview()
            self.preview_status.setText("Finished. Happy with the mix? Hit Next.")

    def stop_preview(self, keep_status=False):
        self.playing = False
        self.preview_btn.setText("▶  Preview mix")
        self.voice_player.stop()
        self.music_player.stop()
        if not keep_status:
            self.preview_status.setText("")

    def on_leave(self):
        self.state.settings.save()
        self.stop_preview()
        self.sample_player.stop()


# ----------------------------------------------------------------------------
class VideoPlayer(GlassFrame):
    """Player for previews and finished videos; its screen matches the video's shape."""

    def __init__(self):
        super().__init__(radius=20)
        from PySide6.QtMultimediaWidgets import QVideoWidget
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 10)
        lay.setSpacing(8)
        self.screen = QStackedWidget()
        self.screen.setFixedSize(QSize(252, 448))
        self.placeholder = label("Your preview plays here.\n\nHit “Quick preview” to see the "
                                 "first few seconds, or make the video.", "Hint", wrap=True)
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setStyleSheet("QLabel { background: rgba(0,0,0,0.35); border-radius: 12px;"
                                       " padding: 18px; }")
        self.video = QVideoWidget()
        self.video.setAspectRatioMode(Qt.KeepAspectRatio)
        self.screen.addWidget(self.placeholder)
        self.screen.addWidget(self.video)
        lay.addWidget(self.screen, 0, Qt.AlignHCenter)
        row = QHBoxLayout()
        self.play_btn = button("▶", "Icon", self.toggle, "Play / pause")
        self.play_btn.setEnabled(False)
        row.addWidget(self.play_btn)
        self.caption = label("", "Hint")
        row.addWidget(self.caption, 1)
        lay.addLayout(row)
        self.out = QAudioOutput()
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.out)
        self.player.setVideoOutput(self.video)
        self.player.playbackStateChanged.connect(self._state)
        self.set_aspect(9 / 16)

    def set_aspect(self, a: float):
        """Fit the screen to the video shape inside a 300 x 448 area."""
        w, h = (252, 448) if a < 0.6 else (min(300, 448 * a), min(300, 448 * a) / a)
        if a > 1:
            w, h = 300, 300 / a
        self.screen.setFixedSize(QSize(int(w), int(h)))
        self.setFixedWidth(int(w) + 24)
        self._set_caption(self.caption.toolTip())

    def _set_caption(self, text):
        self.caption.setToolTip(text)
        room = self.screen.width() - self.play_btn.sizeHint().width() - 14
        self.caption.setText(self.caption.fontMetrics().elidedText(text, Qt.ElideMiddle, room))

    def load(self, path, caption="", autoplay=True):
        self.player.stop()
        self.player.setSource(QUrl())                 # release the old file
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.screen.setCurrentIndex(1)
        self._set_caption(caption)
        self.play_btn.setEnabled(True)
        if autoplay:
            self.player.play()

    def toggle(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _state(self, s):
        self.play_btn.setText("❚❚" if s == QMediaPlayer.PlayingState else "▶")

    def stop(self):
        self.player.stop()

    def clear(self):
        self.player.stop()
        self.player.setSource(QUrl())
        self.screen.setCurrentIndex(0)
        self._set_caption("")
        self.play_btn.setEnabled(False)


STATUS_LOOK = {"reading": ("Reading…", "rgba(255,255,255,0.55)"),
               "ready": ("Ready", "rgba(255,255,255,0.75)"),
               "making": ("Making…", "#ffcf5c"),
               "done": ("Done", None),
               "failed": ("Failed", "#ff6b6b")}


MIN_LENGTHS = [(0, "Off"), (60, "1:00"), (65, "1:05 (over a minute, for TikTok rewards)"),
               (90, "1:30"), (120, "2:00")]


class RenderPage(WizardPage):
    another = Signal()

    def __init__(self, state):
        super().__init__(state)
        self.root.addLayout(page_header("Make the video",
                                        "Check everything, preview it, then make it."))
        cols = QHBoxLayout()
        cols.setSpacing(20)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("Transparent")
        left = QVBoxLayout(inner)
        left.setContentsMargins(0, 0, 6, 0)
        left.setSpacing(12)
        scroll.setWidget(inner)
        scroll.viewport().setAutoFillBackground(False)

        card = Card()
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(20)
        self.grid.setVerticalSpacing(4)
        self.rows = {}
        edits = {"Gameplay": lambda: self._edit(0), "Post": lambda: self._edit(1),
                 "Look": lambda: self._edit(2, 1),
                 "Brand": lambda: self._edit(2, 2), "Voice": lambda: self._edit(3),
                 "Music": lambda: self._edit(3), "Save to": self.choose_output}
        for i, (key, fn) in enumerate(edits.items()):
            self.grid.addWidget(label(key, "Muted"), i, 0, Qt.AlignTop)
            val = label("", wrap=True)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.grid.addWidget(val, i, 1)
            self.rows[key] = val
            self.grid.addWidget(button("Change…" if key == "Save to" else "Edit", "Link", fn),
                                i, 2, Qt.AlignTop)
        self.grid.setColumnStretch(1, 1)
        card.body.addLayout(self.grid)
        left.addWidget(card)

        # How long it'll be, and which apps take that length
        self.length_card = Card()
        head = QHBoxLayout()
        head.addWidget(label("Length", "Section"))
        self.length_value = label("", "Section")
        head.addWidget(self.length_value)
        self.length_note = label("", "Muted")
        head.addWidget(self.length_note)
        head.addStretch()
        head.addWidget(label("Making it for", "Hint"))
        self.target_box = QComboBox()
        self.target_box.addItem("Any app", "")
        from ..platforms import PLATFORMS
        for pl in PLATFORMS:
            self.target_box.addItem(pl.name, pl.key)
        self.target_box.setCurrentIndex(max(0, self.target_box.findData(
            state.settings["target_platform"] or "")))
        self.target_box.currentIndexChanged.connect(self._target_changed)
        head.addWidget(self.target_box)
        self.length_card.body.addLayout(head)
        self.fits_label = label("", wrap=True)
        self.fits_label.setTextFormat(Qt.RichText)
        self.length_card.body.addWidget(self.fits_label)
        frow = QHBoxLayout()
        self.length_warn = label("", wrap=True)
        self.length_warn.setTextFormat(Qt.RichText)
        frow.addWidget(self.length_warn, 1)
        self.fit_btn = button("Speed up to fit", on_click=self.speed_to_fit,
                              tip="Make the voice a little faster so the video fits")
        self.fit_btn.setVisible(False)
        frow.addWidget(self.fit_btn)
        self.length_card.body.addLayout(frow)
        mrow = QHBoxLayout()
        mrow.addWidget(label("Always at least", "Hint"))
        self.min_box = QComboBox()
        for secs, text in MIN_LENGTHS:
            self.min_box.addItem(text, secs)
        self.min_box.setCurrentIndex(max(0, self.min_box.findData(
            int(state.settings["min_length"] or 0))))
        self.min_box.setToolTip("Short stories keep going after the voice ends: the gameplay "
                                "and music carry on until the video reaches this length.\n"
                                "The voice is never slowed down.")
        self.min_box.currentIndexChanged.connect(self._min_changed)
        mrow.addWidget(self.min_box)
        self.min_note = label("", "Hint", wrap=True)
        mrow.addWidget(self.min_note, 1)
        self.length_card.body.addLayout(mrow)
        left.addWidget(self.length_card)
        self._length = None          # LengthGuess for the post on screen
        self._length_token = 0

        brow = QHBoxLayout()
        self.preview_btn = button("▶  Quick preview", on_click=self.preview,
                                  tip="Make the first 6 seconds, small and fast, to check the look")
        self.preview_btn.setMinimumHeight(46)
        brow.addWidget(self.preview_btn)
        self.make_btn = button("Make video", "Primary", self.make)
        self.make_btn.setMinimumHeight(46)
        brow.addWidget(self.make_btn, 1)
        # the buttons stay put under the scrolling summary, so they're always in view
        actions = QVBoxLayout()
        actions.setSpacing(8)
        actions.addLayout(brow)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setVisible(False)
        actions.addWidget(self.progress)
        self.status = label("", "Muted", wrap=True)
        from .errors import attach_copy_link
        attach_copy_link(self.status)
        actions.addWidget(self.status)

        self.done_row = QHBoxLayout()
        self.folder_btn = button("Show in folder", on_click=self.show_folder)
        self.open_btn = button("Open in player", on_click=self.play)
        self.another_btn = button("Make another  →", "Primary", lambda: self.another.emit())
        self.done_row.addWidget(self.folder_btn)
        self.done_row.addWidget(self.open_btn)
        self.done_row.addStretch()
        self.done_row.addWidget(self.another_btn)
        actions.addLayout(self.done_row)

        # batch queue
        self.batch_card = Card()
        head = QHBoxLayout()
        self.batch_title = label("", "Section")
        head.addWidget(self.batch_title)
        head.addStretch()
        self.clear_done_btn = button("Clear finished", "Link", self.clear_finished)
        head.addWidget(self.clear_done_btn)
        self.batch_card.body.addLayout(head)
        self.batch_list = QVBoxLayout()
        self.batch_list.setSpacing(6)
        self.batch_card.body.addLayout(self.batch_list)
        self.batch_hint = label("Every post uses the same gameplay library, voice and music. "
                                "Each one gets its own unused slice of footage.", "Hint", wrap=True)
        self.batch_card.body.addWidget(self.batch_hint)
        brow2 = QHBoxLayout()
        self.make_all_btn = button("", "Primary", self.make_all)
        self.make_all_btn.setMinimumHeight(42)
        brow2.addWidget(self.make_all_btn, 1)
        self.stop_btn = button("Stop after this one", on_click=self.stop_batch)
        self.stop_btn.setVisible(False)
        brow2.addWidget(self.stop_btn)
        self.batch_card.body.addLayout(brow2)
        left.addWidget(self.batch_card)
        left.addStretch()
        leftcol = QVBoxLayout()
        leftcol.setSpacing(10)
        leftcol.addWidget(scroll, 1)
        leftcol.addLayout(actions)
        cols.addLayout(leftcol, 1)

        self.player = VideoPlayer()
        cols.addWidget(self.player, 0, Qt.AlignTop)
        self.root.addLayout(cols, 1)

        self.output = None
        self.running = False
        self.stop_requested = False
        self._show_done(False)
        state.events.queue_changed.connect(self.refresh_batch)
        self.refresh_batch()

    # --- summary -------------------------------------------------------------
    def _show_done(self, on):
        for b in (self.folder_btn, self.open_btn, self.another_btn):
            b.setVisible(on)
            if on:
                fade_in(b, 420)

    def on_enter(self):
        st = self.state
        clip_mode = st.post_page.clip_mode()
        self.rows["Gameplay"].setText(
            st.gameplay_page.summary()
            + (" · skipping menus" if st.settings["skip_boring"] and not clip_mode else "")
            + (" · repeats allowed" if st.settings["reuse_footage"] and not clip_mode
               and st.gameplay_page.mode == "folder" else ""))
        pp = st.post_page
        has_post = pp.current_complete()
        clip = pp.clip_mode()
        if clip:
            hook = f" · hook “{pp.hook.text().strip()}”" if pp.hook.text().strip() else ""
            self.rows["Post"].setText(f"None: just the video{hook}")
        elif has_post:
            lines = [l for l in pp.text.toPlainText().splitlines() if l.strip()]
            hook = f" · hook “{pp.hook.text().strip()}”" if pp.hook.text().strip() else ""
            n = pp.thread_size()
            what = (f"Thread · {n} posts" if n > 1 else
                    f"{Path(pp.posts[0]['image']).name} · {len(lines)} lines")
            self.rows["Post"].setText(f"{what}{hook}")
        else:
            self.rows["Post"].setText("No single post (see the batch below)")
        vp = st.voice_page
        model = MODELS.get(st.settings["voice_model"], "")
        voice = vp.voice_name()
        vid = vp.voice_box.currentData() or NO_VOICE
        if vid != NO_VOICE:
            engine = "free" if is_free(vid) else "your voice" if vid.startswith("custom:") \
                and not vid_is_elevenlabs(vid) else model.split(' (')[0]
            voice += f" · {vp.voice_slider.value()}% · {engine}"
        voice += f" · {vp.pause_seconds():.2f}s between lines"
        if abs(vp.speed() - 1.0) > 0.005:
            voice += f" · {vp.speed():.2f}× speed"
        gv = int(st.settings["clip_volume"] if clip else st.settings["game_volume"] or 0)
        if clip:
            voice = "None"
        voice += f" · video sound {gv}%" if gv else (" · video sound off" if clip else "")
        self.rows["Voice"].setText(voice)
        if vp.music_mode == "folder" and vp.has_music():
            music = f"{vp.summary_music()} · {vp.music_slider.value()}%"
        elif vp.music:
            music = (f"{Path(vp.music).name} · {vp.music_slider.value()}%"
                     + (f" · from {vp._tfmt(vp.music_start)}" if vp.music_start >= 0.5 else ""))
        else:
            music = "None"
        self.rows["Music"].setText(music)
        self.rows["Save to"].setText(st.settings["output_dir"])
        lp = st.layout_page
        reveal = {"fade": "lines fade in", "slide": "slides down"}.get(
            pp.reveal_style(), "lines fade in") if pp.reveal_on() else "whole post shown"
        reveal = lp.caption_summary() or reveal
        look = (f"{lp.summary()} · {lp.picture_summary()}" if clip else
                f"{lp.summary()} · {lp.picture_summary()} · {lp.style_summary()} · {reveal}")
        self.rows["Look"].setText(look)
        self.rows["Brand"].setText(lp.brand_summary())
        from ..layout import aspect
        self.player.set_aspect(aspect(st.layout_page.fmt))
        self.make_btn.setVisible(has_post)
        self.preview_btn.setVisible(has_post)
        if not self.output and not self.running:
            self.status.setText("")
        self.refresh_batch()
        from .. import encoders
        found = encoders._found
        if found is not None:
            kind = encoders.resolve(st.settings["encoder"] or "auto")
            how = encoders.KINDS[kind][1] if kind in encoders.KINDS else "the processor"
            self.rows["Save to"].setText(st.settings["output_dir"] + f" · made on {how}")
        self.update_length()

    def on_leave(self):
        self.player.stop()

    def _edit(self, step, tab=None):
        self.state.window.go(step)
        if tab is not None:
            self.state.layout_page.tabs.setCurrentIndex(tab)

    def choose_output(self):
        d = QFileDialog.getExistingDirectory(self, "Where should videos be saved?",
                                             self.state.settings["output_dir"])
        if d:
            self.state.settings["output_dir"] = d
            self.rows["Save to"].setText(d)

    # --- running ---------------------------------------------------------------
    def _busy(self, on):
        self.running = on
        self.state.busy(on)
        for b in (self.make_btn, self.preview_btn, self.make_all_btn):
            b.setEnabled(not on)
        if on:
            self.progress.setVisible(True)
            self.progress.setValue(0)
            self._show_done(False)

    def _status(self, msg, frac):
        self.status.setText(msg)
        animate_value(self.progress, int(frac * 1000))

    def _error(self, msg):
        self.progress.setVisible(False)
        from .errors import COPY_LINK
        self.status.setText(f"<span style='color:{theme.RED}'>⚠ {msg}</span> &nbsp; {COPY_LINK}")

    def _offer_reset(self, e, job, retry):
        if isinstance(e, LibraryExhausted):
            if QMessageBox.question(self, "Out of footage",
                                    f"{e}\n\nReset the history and try again?") == QMessageBox.Yes:
                self.state.library.reset(gameplay_videos(job))
                retry()

    # --- length -----------------------------------------------------------------
    def update_length(self):
        """Work out how long the video will be (voices on your PC are made now,
        which also makes the real render quicker)."""
        st = self.state
        pp = st.post_page
        self._length_token += 1
        token = self._length_token
        if not pp.current_complete():
            self.length_card.setVisible(False)
            return
        self.length_card.setVisible(True)
        self._min_hint()
        self.length_value.setText("…")
        self.length_note.setText("working it out")
        self.fits_label.setText("")
        self.length_warn.setText("")
        self.fit_btn.setVisible(False)
        job = st.build_job()
        from ..pipeline import predict_length

        def done(guess):
            if token == self._length_token:
                self._length = guess
                self._show_length(job.fmt)

        def fail(msg, e):
            if token == self._length_token:
                self.length_value.setText("?")
                self.length_note.setText(msg[:80])

        run_task(self, lambda emit: predict_length(job, st.cleanup), done, fail)

    def _show_length(self, shape):
        from ..platforms import BY_KEY, check, speed_to_fit
        from ..platforms import fmt as tfmt
        g = self._length
        if g is None:
            return
        self.length_value.setText(("≈ " if not g.exact else "") + tfmt(g.seconds))
        note = "estimated (ElevenLabs voice not made yet)" if not g.exact else ""
        if g.padded >= 0.5:
            note = (f"story {tfmt(g.seconds - g.padded)} + {tfmt(g.padded)} more gameplay"
                    + (" and music" if self.state.voice_page.has_music() else "")
                    + (f" · {note}" if note else ""))
        self.length_note.setText(note)
        self._min_hint()
        res = check(g.seconds, shape)
        ok, bad = theme.primary(), theme.RED
        parts = [f"<span style='color:{ok}'>✓ {p.name}</span>" for p in res["fits"]]
        parts += [f"<span style='color:{bad}'>✕ {p.name} (max {tfmt(p.max_s)})</span>"
                  for p in res["too_long"]]
        parts += [f"<span style='color:#9aa0a6'>– {p.name} (needs vertical or square)</span>"
                  for p in res["wrong_shape"]]
        self.fits_label.setText(" &nbsp;·&nbsp; ".join(parts))
        key = self.target_box.currentData()
        target = BY_KEY.get(key)
        self.fit_btn.setVisible(False)
        warn = ""
        if target is not None:
            if target in res["wrong_shape"]:
                warn = (f"<span style='color:{bad}'>⚠ {target.name} only counts vertical or "
                        "square videos.</span> Change the shape on the Layout step.")
            elif g.seconds > target.max_s and g.padded >= 0.5:
                warn = (f"<span style='color:{bad}'>⚠ “Always at least {tfmt(g.seconds)}” is "
                        f"longer than {target.name} allows ({tfmt(target.max_s)}).</span> "
                        "Pick a shorter minimum.")
            elif g.seconds > target.max_s:
                speed = speed_to_fit(g.seconds, g.voice, target.max_s,
                                     self.state.voice_page.speed())
                warn = (f"<span style='color:{bad}'>⚠ {tfmt(g.seconds - target.max_s)} too long "
                        f"for {target.name} ({tfmt(target.max_s)} max).</span>")
                if speed:
                    self._fit_speed = speed
                    self.fit_btn.setText(f"Speed voice up to {speed:.2f}×")
                    self.fit_btn.setVisible(True)
                elif self.state.post_page.clip_mode():
                    warn += " Use a shorter clip, or cut it into parts."
                else:
                    warn += " Too long even with a faster voice: shorten the text, or split it "\
                            "into a part 1 and part 2."
            elif target.note:
                warn = f"<span style='color:#9aa0a6'>{target.note}</span>"
            if key == "tiktok" and g.seconds <= 60:
                warn = ("<span style='color:#9aa0a6'>Not over 1 minute: fine to post, but "
                        "TikTok Creator Rewards only pays on videos over 1 minute. Set "
                        "“Always at least” to 1:05.</span>")
        self.length_warn.setText(warn)

    def _min_changed(self, _=None):
        self.state.settings["min_length"] = int(self.min_box.currentData() or 0)
        self._min_hint()
        self.update_length()

    def _min_hint(self):
        on = bool(self.min_box.currentData())
        no_music = not self.state.voice_page.has_music()
        self.min_note.setText("No music picked (step 4): the extra time will only have the "
                              "gameplay." if on and no_music else
                              "The voice isn't slowed down; gameplay and music keep going."
                              if on else "")

    def reload_min(self):
        self.min_box.blockSignals(True)
        self.min_box.setCurrentIndex(max(0, self.min_box.findData(
            int(self.state.settings["min_length"] or 0))))
        self.min_box.blockSignals(False)

    def _target_changed(self, _=None):
        self.state.settings["target_platform"] = self.target_box.currentData() or ""
        self._show_length(self.state.layout_page.fmt)

    def speed_to_fit(self):
        vp = self.state.voice_page
        vp.speed_slider.setValue(int(round(getattr(self, "_fit_speed", 1.0) * 100 + 0.49)))
        self.on_enter()

    def length_ok(self, job) -> bool:
        """Ask before making a video that's too long for the chosen app."""
        from ..platforms import BY_KEY
        from ..platforms import fmt as tfmt
        target = BY_KEY.get(self.target_box.currentData())
        g = self._length
        if target is None or g is None or g.seconds <= target.max_s:
            return True
        return QMessageBox.question(
            self, "Too long",
            f"This video will be about {tfmt(g.seconds)}, longer than {target.name} allows "
            f"({tfmt(target.max_s)}).\n\nMake it anyway?") == QMessageBox.Yes

    def preview(self):
        st = self.state
        job = st.build_job()
        narration = st.narration if st.narration_matches(job.voice_id) else None
        self._busy(True)
        self.player.stop()

        def done(made):
            self._busy(False)
            st.preview = (st.job_key(job), made.segment, made.song, job.music_folder)
            self.progress.setVisible(False)
            self.status.setText("Preview ready. The real video will use this same footage.")
            self.player.load(made.path, "Preview · first 6 seconds")

        def fail(msg, e):
            self._busy(False)
            self._error(msg)
            self._offer_reset(e, job, self.preview)

        run_task(self, lambda emit: make_video(job, st.cleanup, st.library, emit, narration,
                                               preview=True), done, fail, self._status)

    def make(self, _=False):
        st = self.state
        job = st.build_job()
        if not self.length_ok(job):
            return
        narration = st.narration if st.narration_matches(job.voice_id) else None
        same = bool(st.preview and st.preview[0] == st.job_key(job) and not job.parts)
        seg = st.preview[1] if same else None
        # a random song from the folder: keep the one the preview played
        song = st.preview[2] if same and job.music_folder and st.preview[3] == job.music_folder \
            else None
        self.output = None
        self._busy(True)
        self.player.stop()

        made_key = st.post_page.current_key()

        def done(made):
            self._busy(False)
            st.preview = None
            st.post_page.made_key = made_key
            self.output = made.path
            animate_value(self.progress, 1000)
            self.status.setText(f"<span style='color:{theme.primary()}'><b>Video saved!</b>"
                                f"</span>  {made.path.name}")
            self._show_done(True)
            self.player.load(made.path, made.path.name)
            st.events.history_changed.emit()

        def fail(msg, e):
            self._busy(False)
            self._error(msg)
            self._offer_reset(e, job, self.make)

        run_task(self, lambda emit: make_video(job, st.cleanup, st.library, emit, narration,
                                               segment=seg, history=st.history,
                                               song=song),
                 done, fail, self._status)

    # --- batch -----------------------------------------------------------------
    def refresh_batch(self):
        q = self.state.queue
        while self.batch_list.count():
            item = self.batch_list.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.batch_card.setVisible(bool(q))
        if not q:
            return
        for i, it in enumerate(q):
            self.batch_list.addWidget(self._batch_row(i, it))
        todo = sum(1 for it in q if it["status"] in ("ready", "failed"))
        reading = sum(1 for it in q if it["status"] == "reading")
        self.batch_title.setText(f"Batch · {len(q)} post{'s' * (len(q) != 1)}")
        self.make_all_btn.setText(f"Make all {todo} video{'s' * (todo != 1)}" if todo
                                  else "All done")
        self.make_all_btn.setEnabled(bool(todo) and not reading and not self.running)
        self.clear_done_btn.setVisible(any(it["status"] == "done" for it in q))

    def _batch_row(self, i, it):
        row = QWidget()
        row.setObjectName("Transparent")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 2, 0, 2)
        h.setSpacing(10)
        thumb = QLabel()
        pix = QPixmap(it["image"]) if it.get("image") else QPixmap()
        if not pix.isNull():
            thumb.setPixmap(pix.scaled(46, 46, Qt.KeepAspectRatioByExpanding,
                                       Qt.SmoothTransformation).copy(0, 0, 46, 46))
        thumb.setFixedSize(46, 46)
        thumb.setStyleSheet("border-radius: 8px; background: rgba(255,255,255,0.06);")
        h.addWidget(thumb)
        first = next((l.strip(" >") for l in it.get("text", "").splitlines() if l.strip()), "")
        title = it.get("hook") or first or Path(it.get("image", "")).name
        t = label(title[:60] + ("…" if len(title) > 60 else ""), wrap=False)
        h.addWidget(t, 1)
        if it.get("parts"):
            h.addWidget(label(f"{len(it['parts']) + 1} posts", "Muted"))
        names = self.state.presets.names()
        if names and it["status"] in ("ready", "failed", "reading") and not self.running:
            look = QComboBox()
            look.addItem("Current look", "")
            for n in names:
                look.addItem(n, n)
            look.setCurrentIndex(max(0, look.findData(it.get("preset", ""))))
            look.setToolTip("Which preset this video uses")
            look.currentIndexChanged.connect(
                lambda _=0, b=look, item=it: item.__setitem__("preset", b.currentData()))
            h.addWidget(look)
        elif it.get("preset"):
            h.addWidget(label(it["preset"], "Muted"))
        text, color = STATUS_LOOK.get(it["status"], (it["status"], None))
        st = label(text)
        st.setStyleSheet(f"color: {color or theme.primary()}; font-weight: 600;")
        if it.get("error"):
            st.setToolTip(it["error"])
        h.addWidget(st)
        if it["status"] == "done" and it.get("result"):
            h.addWidget(button("▶", "Link", lambda _=False, p=it["result"]:
                               self.player.load(p, Path(p).name), "Play here"))
        elif it["status"] in ("ready", "failed") and not self.running:
            h.addWidget(button("Edit", "Link", lambda _=False, k=i: self.edit_item(k),
                               "Move back to step 2 to change it"))
        if not self.running or it["status"] != "making":
            h.addWidget(button("✕", "Link", lambda _=False, k=i: self.remove_item(k), "Remove"))
        return row

    def edit_item(self, i):
        it = self.state.queue.pop(i)
        self.state.events.queue_changed.emit()
        self.state.post_page.load_post(it["image"], it["text"], it["hook"], it["hook_spoken"],
                                       it["post_text"], parts=it.get("parts"))
        self.state.window.go(1)

    def remove_item(self, i):
        if 0 <= i < len(self.state.queue):
            self.state.queue.pop(i)
            self.state.events.queue_changed.emit()

    def clear_finished(self):
        self.state.queue[:] = [it for it in self.state.queue if it["status"] != "done"]
        self.state.events.queue_changed.emit()

    def stop_batch(self):
        self.stop_requested = True
        self.stop_btn.setEnabled(False)
        self.stop_btn.setText("Stopping after this one…")

    def make_all(self):
        st = self.state
        pp = st.post_page
        if pp.current_complete() and pp.made_key != pp.current_key():   # post on screen, not made yet
            st.add_to_queue(pp.snapshot())
            pp.reset()
        todo = [it for it in st.queue if it["status"] in ("ready", "failed")]
        if not todo:
            return
        jobs = [(it, st.build_job(it)) for it in todo]
        self.stop_requested = False
        self.stop_btn.setText("Stop after this one")
        self.stop_btn.setEnabled(True)
        self.stop_btn.setVisible(True)
        self._busy(True)

        def work(emit):
            made_count = 0
            for k, (it, job) in enumerate(jobs):
                if self.stop_requested:
                    break
                it["status"], it["error"] = "making", ""
                emit("@refresh", k / len(jobs))
                try:
                    made = make_video(job, st.cleanup, st.library,
                                      lambda m, f, k=k: emit(f"Video {k + 1} of {len(jobs)}: {m}",
                                                             (k + f) / len(jobs)),
                                      history=st.history)
                    it["status"], it["result"] = "done", str(made.path)
                    made_count += 1
                except LibraryExhausted:
                    it["status"], it["error"] = "failed", "Out of unused footage"
                    emit("@refresh", (k + 1) / len(jobs))
                    raise
                except Exception as e:
                    it["status"], it["error"] = "failed", str(e) or e.__class__.__name__
                emit("@refresh", (k + 1) / len(jobs))
            return made_count

        def status(msg, frac):
            if msg == "@refresh":
                self.refresh_batch()
                animate_value(self.progress, int(frac * 1000))
            else:
                self._status(msg, frac)

        def finish():
            self._busy(False)
            self.stop_btn.setVisible(False)
            self.refresh_batch()
            st.events.history_changed.emit()

        def done(n):
            finish()
            failed = sum(1 for it in st.queue if it["status"] == "failed")
            self.status.setText(f"<span style='color:{theme.primary()}'><b>Made {n} video"
                                f"{'s' * (n != 1)}.</b></span>"
                                + (f"  {failed} failed (hover for why)." if failed else ""))
            self.output = Path(st.settings["output_dir"]) if n else None
            self.folder_btn.setVisible(bool(n))
            last = next((it["result"] for it in reversed(st.queue) if it["status"] == "done"), "")
            if last:
                self.player.load(last, Path(last).name, autoplay=False)

        def fail(msg, e):
            finish()
            self._error(msg)
            if isinstance(e, LibraryExhausted) and QMessageBox.question(
                    self, "Out of footage", f"{msg}\n\nReset the history and continue?") == QMessageBox.Yes:
                st.library.reset(gameplay_videos(jobs[0][1]))
                self.make_all()

        run_task(self, work, done, fail, status)

    # --- after -----------------------------------------------------------------
    def play(self):
        if self.output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output)))

    def show_folder(self):
        if self.output:
            from ..appinfo import show_in_folder
            show_in_folder(self.output)

    def reset(self):
        self.output = None
        self.status.setText("")
        self.progress.setVisible(False)
        self._show_done(False)
